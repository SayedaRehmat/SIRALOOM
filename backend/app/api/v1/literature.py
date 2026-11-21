"""Explicit, governed PubMed citation-candidate retrieval for variant review."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.adapters.literature.pubmed import (
    PUBMED_PROVIDER_ID,
    PubMedLiteratureError,
)
from backend.app.auth.authorization import (
    CASE_WRITE_ROLES,
    get_accessible_analysis,
    get_analysis_variant,
    require_role,
)
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.domain.evidence import evidence_fingerprint
from backend.app.domain.upload_idempotency import idempotency_key_sha256
from backend.app.domain.provider_registry import ProviderRegistryError, register_builtin_providers
from backend.app.domain.resource_capabilities import CapabilityRequirement, ResourceCapability
from backend.app.domain.resource_execution import (
    ResourceExecutionError,
    complete_resource_execution,
    resolve_resource_execution,
    start_resource_execution,
)
from backend.app.domain.resource_execution_plan import build_resource_execution_plan
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import Analysis, Annotation, Case, Evidence, ResourceExecutionRecord
from backend.app.infrastructure.db.session import get_db

router = APIRouter(tags=["literature"])
_GENE_SYMBOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,30}$")
_RSID = re.compile(r"^rs[1-9][0-9]*$", re.IGNORECASE)
_ABANDONED_EXECUTION_AFTER = timedelta(seconds=60)


class PubMedSearchRequest(BaseModel):
    gene_symbol: str = Field(min_length=1, max_length=31)


def _annotated_gene_symbols(value) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in {"gene_symbol", "gene_name", "symbol"} and isinstance(item, str):
                normalized = item.strip()
                if _GENE_SYMBOL.fullmatch(normalized):
                    names.add(normalized.upper())
            elif isinstance(item, (dict, list, tuple)):
                names.update(_annotated_gene_symbols(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            names.update(_annotated_gene_symbols(item))
    return names


def _variant_rsids(variant) -> tuple[str, ...]:
    found: set[str] = set()

    def visit(value):
        if isinstance(value, str) and _RSID.fullmatch(value.strip()):
            found.add(value.strip().lower())
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(variant.identifiers or {})
    return tuple(sorted(found))


@router.post("/analyses/{analysis_id}/variants/{variant_id}/literature-search")
def search_pubmed_candidates(
    analysis_id: UUID,
    variant_id: UUID,
    body: PubMedSearchRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    """Persist bibliographic candidates; never infer or assert variant significance."""
    analysis = get_accessible_analysis(analysis_id, db, principal, "write")
    require_role(principal, CASE_WRITE_ROLES)
    try:
        idempotency_hash = idempotency_key_sha256(idempotency_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    variant = get_analysis_variant(analysis, variant_id, db)
    case = db.get(Case, analysis.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    annotation = db.scalar(
        select(Annotation).where(
            Annotation.analysis_id == analysis_id,
            Annotation.variant_id == variant_id,
        )
    )
    if annotation is None:
        raise HTTPException(status_code=404, detail="Variant annotation not found in analysis")
    gene = body.gene_symbol.strip().upper()
    annotated_genes = _annotated_gene_symbols(annotation.payload)
    if gene not in annotated_genes:
        raise HTTPException(
            status_code=422,
            detail="Search gene must match a gene symbol in this analysis's persisted annotation",
        )

    plan = build_resource_execution_plan(
        db,
        organization_id=case.organization_id,
        requirements=(CapabilityRequirement(ResourceCapability.LITERATURE),),
    )
    candidates = [
        item for item in plan.for_capability(ResourceCapability.LITERATURE)
        if item.resource.provider.strip().upper() == PUBMED_PROVIDER_ID
    ]
    if len(candidates) != 1:
        raise HTTPException(
            status_code=409,
            detail="Exactly one qualified, organization-approved PubMed resource must be selected before search",
        )
    resource = candidates[0].resource
    try:
        execution = resolve_resource_execution(db, resource=resource)
        implementation = register_builtin_providers().require(
            provider_id=execution.contract.provider_id,
            provider_version=execution.contract.provider_version,
        )
        provider = implementation.factory(execution.contract)
    except (ResourceExecutionError, ProviderRegistryError, PubMedLiteratureError, ValueError) as exc:
        detail = exc.code if isinstance(exc, PubMedLiteratureError) else "PUBMED_RESOURCE_CONFIGURATION_INVALID"
        raise HTTPException(status_code=409, detail=detail) from exc

    identifiers = _variant_rsids(variant)
    request_material = {
        "analysis_id": str(analysis_id),
        "variant_id": str(variant_id),
        "gene_symbol": gene,
        "variant_identifiers": list(identifiers),
        "resource_id": str(resource.id),
        "resource_version": resource.version,
        "contract_hash": execution.contract_hash,
    }
    request_fingerprint = hashlib.sha256(
        json.dumps(request_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    batch_key = f"pubmed:{variant_id}:{idempotency_hash}"

    # Serialize duplicate submissions on the analysis row, then commit the
    # STARTED execution before making the remote request.
    locked_analysis = db.get(Analysis, analysis_id, with_for_update=True)
    if locked_analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    existing = db.scalar(
        select(ResourceExecutionRecord)
        .where(
            ResourceExecutionRecord.analysis_id == analysis_id,
            ResourceExecutionRecord.step_id == "build_evidence",
            ResourceExecutionRecord.batch_key == batch_key,
        )
        .order_by(ResourceExecutionRecord.attempt.desc())
        .limit(1)
    )
    next_attempt = 0
    if existing is not None:
        existing_metadata = dict(existing.metadata_json or {})
        if existing_metadata.get("request_fingerprint") != request_fingerprint:
            raise HTTPException(
                status_code=409,
                detail="IDEMPOTENCY_KEY_REUSED: this key is already bound to a different PubMed search",
            )
        if existing.status in {"COMPLETED", "NO_MATCH"}:
            evidence_ids = [UUID(str(value)) for value in existing_metadata.get("evidence_ids", [])]
            evidence_filter = Evidence.id.in_(evidence_ids) if evidence_ids else Evidence.id.is_(None)
            rows = list(
                db.scalars(
                    select(Evidence).where(
                        Evidence.analysis_id == analysis_id,
                        Evidence.variant_id == variant_id,
                        evidence_filter,
                    )
                ).all()
            )
            if len(rows) != len(evidence_ids):
                raise HTTPException(status_code=503, detail="PUBMED_IDEMPOTENT_RESULT_RECOVERY_REQUIRED")
            return {
                "status": existing_metadata.get("search_status", "SUCCESS_NO_MATCH"),
                "gene_symbol": gene,
                "query": existing_metadata.get("query"),
                "retrieved_at": existing_metadata.get("retrieved_at"),
                "response_sha256": existing.response_sha256,
                "resource_id": str(existing.resource_id),
                "resource_version": existing.resource_version,
                "execution_id": str(existing.id),
                "candidates": [
                    {"evidence_id": str(row.id), **dict(row.payload or {})} for row in rows
                ],
                "interpretation": "Citation matches are unreviewed bibliographic candidates, not variant evidence or a clinical conclusion.",
                "idempotent_replay": True,
            }
        if existing.status == "STARTED":
            started_at = existing.started_at or datetime.now(UTC)
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=UTC)
            if datetime.now(UTC) - started_at < _ABANDONED_EXECUTION_AFTER:
                raise HTTPException(status_code=409, detail="PUBMED_SEARCH_IN_PROGRESS")
            complete_resource_execution(
                db,
                existing,
                status="RETRYABLE_FAILURE",
                request_fingerprint=request_fingerprint,
                error_code="PUBMED_EXECUTION_ABANDONED",
                error_message="Previous search remained STARTED beyond the recovery interval.",
            )
            AuditService(db).record(
                event_type="PUBMED_LITERATURE_SEARCH_RECOVERED",
                case_id=case.id,
                analysis_id=analysis_id,
                actor_type="HUMAN",
                actor_id=str(principal.user_id),
                subject_type="VARIANT",
                subject_id=str(variant_id),
                operation="RETRY_ABANDONED_LITERATURE_SEARCH",
                before_state={"execution_id": str(existing.id), "status": "STARTED"},
                after_state={
                    "execution_id": str(existing.id),
                    "status": "RETRYABLE_FAILURE",
                    "error_code": "PUBMED_EXECUTION_ABANDONED",
                },
                workflow={"domain": "literature", "organization_id": str(case.organization_id)},
                resource_versions={
                    "pubmed": {
                        "resource_id": str(existing.resource_id),
                        "resource_version": existing.resource_version,
                        "qualification_id": str(existing.qualification_id),
                        "qualification_version": existing.qualification_version,
                    }
                },
            )
            next_attempt = existing.attempt + 1
        elif existing.status == "RETRYABLE_FAILURE":
            next_attempt = existing.attempt + 1
        else:
            raise HTTPException(
                status_code=409,
                detail=f"PUBMED_SEARCH_NOT_RETRYABLE: previous attempt ended as {existing.status}",
            )

    execution_record = start_resource_execution(
        db,
        analysis_id=analysis_id,
        step_id="build_evidence",
        attempt=next_attempt,
        resolved=execution,
        requested_resource_id=resource.id,
        fallback_resource_id=None,
        batch_key=batch_key,
        metadata={
            "operation": "PUBMED_CITATION_CANDIDATE_SEARCH",
            "variant_id": str(variant_id),
            "gene_symbol": gene,
            "variant_identifiers": list(identifiers),
            "request_fingerprint": request_fingerprint,
            "idempotency_key_sha256": idempotency_hash,
            "interpretive_use": "BIBLIOGRAPHIC_DISCOVERY_ONLY",
        },
    )
    db.commit()

    try:
        search = provider.search_gene(gene_symbol=gene, identifiers=identifiers)
    except PubMedLiteratureError as exc:
        complete_resource_execution(
            db,
            execution_record,
            status="RETRYABLE_FAILURE" if exc.retryable else "INVALID_RESPONSE",
            request_fingerprint=request_fingerprint,
            error_code=exc.code,
            error_message=str(exc),
        )
        AuditService(db).record(
            event_type="PUBMED_LITERATURE_SEARCH_FAILED",
            case_id=case.id,
            analysis_id=analysis_id,
            actor_type="HUMAN",
            actor_id=str(principal.user_id),
            subject_type="VARIANT",
            subject_id=str(variant_id),
            operation="SEARCH_LITERATURE",
            after_state={"status": execution_record.status, "error_code": exc.code},
            workflow={"domain": "literature", "organization_id": str(case.organization_id)},
            resource_versions={"pubmed": {"resource_id": str(resource.id), "version": resource.version}},
        )
        db.commit()
        raise HTTPException(status_code=503 if exc.retryable else 502, detail=exc.code) from exc

    # Recheck case access and serialize candidate persistence against report sign-out.
    analysis = get_accessible_analysis(analysis_id, db, principal, "write")
    analysis = db.get(Analysis, analysis_id, with_for_update=True)
    db.refresh(analysis, with_for_update=True)
    db.refresh(execution_record, with_for_update=True)
    if execution_record.status != "STARTED":
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="PUBMED_SEARCH_ATTEMPT_SUPERSEDED: retry the same idempotency key to retrieve the current result",
        )
    inserted = []
    for candidate in search.candidates:
        candidate_payload = {
            **candidate.as_dict(),
            "query": search.query,
            "retrieved_at": search.retrieved_at,
            "response_sha256": search.response_sha256,
            "result_count": search.result_count,
            "search_status": search.status,
            "resource_id": str(resource.id),
            "resource_version": resource.version,
            "qualification_id": str(execution.qualification_id),
            "qualification_version": execution.qualification_version,
            "interpretive_use": "BIBLIOGRAPHIC_CANDIDATE_REQUIRES_HUMAN_CURATION",
        }
        statement = (
            f"PubMed citation candidate for annotated gene {gene}; article content, "
            "variant relevance, and disease association have not been reviewed. "
            "Human curation is required."
        )
        fingerprint = evidence_fingerprint(
            variant_id=variant_id,
            analysis_id=analysis_id,
            evidence_type="LITERATURE",
            statement=statement,
            direction="UNKNOWN",
            source_name="PUBMED",
            source_version=resource.version,
            observation_ids=(),
            payload=candidate_payload,
        )
        row = db.scalar(
            select(Evidence).where(
                Evidence.analysis_id == analysis_id,
                Evidence.evidence_fingerprint == fingerprint,
            )
        )
        if row is None:
            row = Evidence(
                id=uuid4(),
                variant_id=variant_id,
                analysis_id=analysis_id,
                evidence_type="LITERATURE",
                statement=statement,
                direction="UNKNOWN",
                source_name="PUBMED",
                source_version=resource.version,
                resource_id=resource.id,
                source_record_id=candidate.pmid,
                request_fingerprint=request_fingerprint,
                response_sha256=search.response_sha256,
                request_metadata={
                    "provider_version": search.provider_version,
                    "query": search.query,
                    "retrieved_at": search.retrieved_at,
                    "variant_identifiers": list(identifiers),
                },
                observed_at=None,
                observation_ids=[],
                payload=candidate_payload,
                created_by_type="SYSTEM",
                created_by_id="PUBMED_CANDIDATE_RETRIEVAL",
                evidence_fingerprint=fingerprint,
            )
            db.add(row)
            db.flush()
        inserted.append(row)

    complete_resource_execution(
        db,
        execution_record,
        status="COMPLETED" if search.candidates else "NO_MATCH",
        request_fingerprint=request_fingerprint,
        response_sha256=search.response_sha256,
    )
    execution_record.metadata_json = {
        **dict(execution_record.metadata_json or {}),
        "search_status": search.status,
        "result_count": search.result_count,
        "citation_candidate_count": len(search.candidates),
        "evidence_ids": [str(item.id) for item in inserted],
        "retrieved_at": search.retrieved_at,
        "query": search.query,
        "request_fingerprint": request_fingerprint,
        "content_policy": "CITATION_METADATA_ONLY_NO_ABSTRACTS",
    }
    AuditService(db).record(
        event_type="PUBMED_LITERATURE_CANDIDATES_RETRIEVED",
        case_id=case.id,
        analysis_id=analysis_id,
        actor_type="HUMAN",
        actor_id=str(principal.user_id),
        subject_type="VARIANT",
        subject_id=str(variant_id),
        operation="SEARCH_LITERATURE",
        after_state={
            "execution_status": execution_record.status,
            "search_status": search.status,
            "candidate_count": len(search.candidates),
            "response_sha256": search.response_sha256,
        },
        workflow={"domain": "literature", "organization_id": str(case.organization_id)},
        resource_versions={
            "pubmed": {
                "resource_id": str(resource.id),
                "resource_version": resource.version,
                "qualification_id": str(execution.qualification_id),
                "qualification_version": execution.qualification_version,
                "contract_hash": execution.contract_hash,
            }
        },
    )
    db.commit()
    return {
        "status": search.status,
        "gene_symbol": gene,
        "query": search.query,
        "retrieved_at": search.retrieved_at,
        "response_sha256": search.response_sha256,
        "resource_id": str(resource.id),
        "resource_version": resource.version,
        "execution_id": str(execution_record.id),
        "candidates": [
            {"evidence_id": str(row.id), **dict(row.payload or {})}
            for row in inserted
        ],
        "interpretation": "Citation matches are unreviewed bibliographic candidates, not variant evidence or a clinical conclusion.",
    }
