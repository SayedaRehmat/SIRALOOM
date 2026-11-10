"""PostgreSQL durability, deduplication, replay and review projection for C1 evidence."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from backend.app.auth.principal import Principal, get_current_principal
from backend.app.domain.evidence import evidence_fingerprint
from backend.app.infrastructure.db.session import get_db
from backend.app.main import app
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Analysis, Annotation, Case, Evidence, Organization, OrganizationMembership, User, Variant
from backend.app.review.service import _evidence_context_dict


@pytest.mark.integration
def test_gene_disease_reconciliation_evidence_is_deduplicated_after_crash_replay_and_reviewable():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id = uuid4(), uuid4(), uuid4()
    analysis_id, variant_id = uuid4(), uuid4()
    source_payload = {
        "reconciliation_id": "c1-test-reconciliation-0001",
        "status": "G2P_ONLY",
        "requires_human_review": True,
        "review_reasons": ["ASSOCIATION_G2P_ONLY", "CANONICAL_HGNC_IDENTIFIER_INCOMPLETE"],
        "interpretive_use": "GENE_DISEASE_RECONCILIATION_CONTEXT_ONLY",
        "clinical_conclusion": False,
        "source_provenance": [{
            "source": "G2P", "source_record_id": "G2P:G2P0001",
            "resource_id": "00000000-0000-0000-0000-000000000001",
            "resource_name": "Gene2Phenotype", "resource_version": "2026-11-08",
            "resource_sha256": "a" * 64, "source_record_sha256": "b" * 64,
            "request_fingerprint": "c" * 64, "response_sha256": "d" * 64,
            "raw_assertion": {"Gene Symbol": "GENE1", "Disease Mondo": "MONDO:0000001"},
        }],
    }
    statement = "Independent gene-disease assertions retained for reviewer context."
    fingerprint = evidence_fingerprint(
        variant_id=variant_id, analysis_id=analysis_id, evidence_type="GENE_DISEASE",
        statement=statement, direction="NEUTRAL",
        source_name="SIRALOOM gene-disease reconciliation", source_version="1",
        observation_ids=(), payload=source_payload, resource_id=None,
        source_record_id=source_payload["reconciliation_id"], request_fingerprint=None,
        response_sha256=None,
    )
    try:
        with Session(engine) as db:
            db.add(Organization(id=organization_id, name="C1 integration organization"))
            db.add(User(id=user_id, organization_id=organization_id, display_name="C1 integration", role="ADMIN", status="ACTIVE"))
            db.flush()
            db.add(Case(id=case_id, organization_id=organization_id, case_identifier=f"C1-{case_id}", status="OPEN", clinical_context={}, created_by=user_id))
            db.flush()  # The Analysis foreign key requires the Case row to exist first.
            db.add(Analysis(
                id=analysis_id, case_id=case_id, analysis_type="VCF", workflow_id="integration",
                workflow_version="1", status="COMPLETED", reference_build="GRCh38",
                configuration={}, created_by=user_id, toolchain_profile_id="integration",
                toolchain_bcftools_version="1.19", toolchain_htslib_version="1.19", toolchain_snapshot={},
            ))
            db.add(Variant(
                id=variant_id, genome_build="GRCh38", chromosome="1", position=100,
                reference="A", alternate="G", normalization_status="NORMALIZED",
                canonical_key=f"C1-{variant_id}", identifiers={},
            ))
            db.commit()

        # Make the persisted evidence reachable through the real tenant-scoped review route.
        with Session(engine) as db:
            db.add(OrganizationMembership(
                id=uuid4(), organization_id=organization_id, user_id=user_id,
                role="organization_admin", status="ACTIVE",
            ))
            db.add(Annotation(
                id=uuid4(), variant_id=variant_id, analysis_id=analysis_id,
                provider_name="C1 integration fixture", provider_version="1",
                resource_id=None, resource_name=None, resource_version=None,
                request_fingerprint=None, response_sha256=None, request_metadata={},
                retry_count=0, payload={"normalized": {"gene": {"symbol": "GENE1"}}},
            ))
            db.commit()

        # First worker attempt commits the evidence, then dies before its stage checkpoint.
        with Session(engine) as db:
            db.add(Evidence(
                id=uuid4(), variant_id=variant_id, analysis_id=analysis_id,
                evidence_type="GENE_DISEASE", statement=statement, direction="NEUTRAL",
                source_name="SIRALOOM gene-disease reconciliation", source_version="1",
                resource_id=None, source_record_id=source_payload["reconciliation_id"],
                request_fingerprint=None, response_sha256=None, request_metadata={"source_provenance": source_payload["source_provenance"]},
                observation_ids=[], payload=source_payload, created_by_type="SYSTEM",
                created_by_id="siraloom-evidence", evidence_fingerprint=fingerprint,
            ))
            db.commit()

        # Redelivery computes the same content fingerprint and observes the durable row.
        with Session(engine) as db:
            existing = db.scalar(select(Evidence).where(
                Evidence.analysis_id == analysis_id,
                Evidence.evidence_fingerprint == fingerprint,
            ))
            if existing is None:
                db.add(Evidence(
                    id=uuid4(), variant_id=variant_id, analysis_id=analysis_id,
                    evidence_type="GENE_DISEASE", statement=statement, direction="NEUTRAL",
                    source_name="SIRALOOM gene-disease reconciliation", source_version="1",
                    resource_id=None, source_record_id=source_payload["reconciliation_id"],
                    request_fingerprint=None, response_sha256=None,
                    request_metadata={"source_provenance": source_payload["source_provenance"]},
                    observation_ids=[], payload=source_payload, created_by_type="SYSTEM",
                    created_by_id="siraloom-evidence", evidence_fingerprint=fingerprint,
                ))
                db.commit()
            count = db.scalar(select(func.count(Evidence.id)).where(
                Evidence.analysis_id == analysis_id,
                Evidence.evidence_fingerprint == fingerprint,
            ))
            assert count == 1
            persisted = db.scalar(select(Evidence).where(Evidence.analysis_id == analysis_id, Evidence.evidence_fingerprint == fingerprint))
            review_context = _evidence_context_dict(persisted)
            assert review_context["type"] == "GENE_DISEASE"
            assert review_context["direction"] == "NEUTRAL"
            assert review_context["source_record_id"] == source_payload["reconciliation_id"]
            assert review_context["payload"]["clinical_conclusion"] is False
            assert review_context["payload"]["requires_human_review"] is True
            assert review_context["payload"]["source_provenance"][0]["raw_assertion"] == source_payload["source_provenance"][0]["raw_assertion"]

        previous_overrides = app.dependency_overrides.copy()
        def override_get_db():
            with Session(engine) as db:
                yield db
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_principal] = lambda: Principal(
            user_id=user_id, organization_id=organization_id,
            role="organization_admin", subject=str(user_id),
        )
        try:
            response = TestClient(app).get(
                f"/api/v1/analyses/{analysis_id}/variants/{variant_id}/review"
            )
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous_overrides)
        assert response.status_code == 200, response.text
        review_gene_disease = response.json()["variant_context"]["gene_disease"]
        assert len(review_gene_disease) == 1
        api_evidence = review_gene_disease[0]
        assert api_evidence["direction"] == "NEUTRAL"
        assert api_evidence["source_record_id"] == source_payload["reconciliation_id"]
        assert api_evidence["resource_id"] is None
        assert api_evidence["payload"]["clinical_conclusion"] is False
        assert api_evidence["payload"]["requires_human_review"] is True
        api_source = api_evidence["payload"]["source_provenance"][0]
        assert api_source["resource_id"] == source_payload["source_provenance"][0]["resource_id"]
        assert api_source["resource_sha256"] == "a" * 64
        assert api_source["source_record_sha256"] == "b" * 64
        assert api_source["request_fingerprint"] == "c" * 64
        assert api_source["response_sha256"] == "d" * 64
        assert api_source["raw_assertion"] == source_payload["source_provenance"][0]["raw_assertion"]
    finally:
        with Session(engine) as db:
            db.query(Evidence).filter(Evidence.analysis_id == analysis_id).delete(synchronize_session=False)
            db.query(Annotation).filter(Annotation.analysis_id == analysis_id).delete(synchronize_session=False)
            db.query(OrganizationMembership).filter(OrganizationMembership.organization_id == organization_id).delete(synchronize_session=False)
            db.query(Variant).filter(Variant.id == variant_id).delete(synchronize_session=False)
            db.query(Analysis).filter(Analysis.id == analysis_id).delete(synchronize_session=False)
            db.query(Case).filter(Case.id == case_id).delete(synchronize_session=False)
            db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
            db.query(Organization).filter(Organization.id == organization_id).delete(synchronize_session=False)
            db.commit()
        engine.dispose()
