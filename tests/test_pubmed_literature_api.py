from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException


class _DB:
    def __init__(self, case, annotation):
        self.case = case
        self.annotation = annotation
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self._scalar_calls = 0

    def get(self, model, _identifier, **_kwargs):
        from backend.app.infrastructure.db.models import Analysis, Case

        if model is Case:
            return self.case
        assert model is Analysis
        return self.analysis

    def scalar(self, _statement):
        self._scalar_calls += 1
        return self.annotation if self._scalar_calls == 1 else None

    def add(self, row):
        self.added.append(row)

    def flush(self):
        pass

    def commit(self):
        self.commits += 1

    def refresh(self, *_args, **_kwargs):
        pass

    def rollback(self):
        self.rollbacks += 1


@pytest.mark.parametrize(
    ("gene", "expected_status"),
    [("PAH", 409), ("CFTR", 422)],
)
def test_literature_search_requires_approved_pubmed_resource_and_annotated_gene(
    monkeypatch, gene, expected_status
):
    from backend.app.api.v1 import literature

    analysis_id, variant_id, organization_id = uuid4(), uuid4(), uuid4()
    analysis = SimpleNamespace(id=analysis_id, case_id=uuid4())
    case = SimpleNamespace(id=analysis.case_id, organization_id=organization_id)
    annotation = SimpleNamespace(payload={"transcript_consequences": [{"gene_symbol": "PAH"}]})
    db = _DB(case, annotation)
    principal = SimpleNamespace(user_id=uuid4(), role="bioinformatician")

    monkeypatch.setattr(literature, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(literature, "require_role", lambda *_args: None)
    monkeypatch.setattr(literature, "get_analysis_variant", lambda *_args: SimpleNamespace(identifiers={}))

    def no_resource_plan(*_args, **_kwargs):
        return SimpleNamespace(for_capability=lambda _capability: ())

    monkeypatch.setattr(literature, "build_resource_execution_plan", no_resource_plan)

    with pytest.raises(HTTPException) as exc:
        literature.search_pubmed_candidates(
            analysis_id,
            variant_id,
            literature.PubMedSearchRequest(gene_symbol=gene),
            db,
            principal,
            idempotency_key="literature-test-key-0001",
        )

    assert exc.value.status_code == expected_status
    assert "approved PubMed" in exc.value.detail if expected_status == 409 else "gene symbol" in exc.value.detail


def _successful_route_context(monkeypatch, *, provider_error=None, execution_status_on_search=None):
    from backend.app.adapters.literature.pubmed import (
        PubMedLiteratureCandidate,
        PubMedSearchResult,
    )
    from backend.app.api.v1 import literature

    analysis_id, variant_id, organization_id = uuid4(), uuid4(), uuid4()
    case_id, resource_id = uuid4(), uuid4()
    analysis = SimpleNamespace(id=analysis_id, case_id=case_id)
    case = SimpleNamespace(id=case_id, organization_id=organization_id)
    annotation = SimpleNamespace(payload={"transcript_consequences": [{"gene_symbol": "PAH"}]})
    db = _DB(case, annotation)
    db.analysis = analysis
    principal = SimpleNamespace(user_id=uuid4(), role="bioinformatician")
    variant = SimpleNamespace(identifiers={"dbsnp": "rs5030858"})
    resource = SimpleNamespace(id=resource_id, provider="PUBMED", version="2026-01")
    candidate_row = SimpleNamespace(resource=resource)
    plan = SimpleNamespace(for_capability=lambda _capability: (candidate_row,))
    execution = SimpleNamespace(
        contract=SimpleNamespace(provider_id="PUBMED", provider_version="ncbi-eutils-pubmed-v1"),
        contract_hash="contract-hash",
        qualification_id=uuid4(),
        qualification_version="qualification-1",
    )
    execution_record = SimpleNamespace(id=uuid4(), status="STARTED", metadata_json={})
    candidate = PubMedLiteratureCandidate(
        pmid="12345678",
        title="A relevant study",
        citation="Author. Journal. 2024",
        publication_year=2024,
        doi="10.1000/example",
        source_url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
    )
    result = PubMedSearchResult(
        status="SUCCESS",
        query='("PAH"[Title/Abstract]) AND ("rs5030858"[Title/Abstract])',
        candidates=(candidate,),
        retrieved_at="2026-11-17T00:00:00+00:00",
        response_sha256="a" * 64,
        result_count=1,
    )

    class _Provider:
        def search_gene(self, **_kwargs):
            if provider_error is not None:
                raise provider_error
            if execution_status_on_search is not None:
                execution_record.status = execution_status_on_search
            return result

    implementation = SimpleNamespace(factory=lambda _contract: _Provider())
    registry = SimpleNamespace(require=lambda **_kwargs: implementation)
    monkeypatch.setattr(literature, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(literature, "require_role", lambda *_args: None)
    monkeypatch.setattr(literature, "get_analysis_variant", lambda *_args: variant)
    monkeypatch.setattr(literature, "build_resource_execution_plan", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(literature, "resolve_resource_execution", lambda *_args, **_kwargs: execution)
    monkeypatch.setattr(literature, "register_builtin_providers", lambda: registry)
    monkeypatch.setattr(literature, "start_resource_execution", lambda *_args, **_kwargs: execution_record)

    def complete(_db, record, *, status, **_kwargs):
        record.status = status

    monkeypatch.setattr(literature, "complete_resource_execution", complete)

    class _Audit:
        def __init__(self, _db):
            pass

        def record(self, **_kwargs):
            pass

    monkeypatch.setattr(literature, "AuditService", _Audit)
    return literature, analysis_id, variant_id, db, principal, execution_record


def test_literature_search_persists_candidate_as_unreviewed_provenanced_context(monkeypatch):
    from backend.app.infrastructure.db.models import Evidence

    literature, analysis_id, variant_id, db, principal, execution_record = _successful_route_context(monkeypatch)
    response = literature.search_pubmed_candidates(
        analysis_id,
        variant_id,
        literature.PubMedSearchRequest(gene_symbol="PAH"),
        db,
        principal,
        idempotency_key="literature-test-key-0002",
    )

    assert response["status"] == "SUCCESS"
    assert response["candidates"][0]["pmid"] == "12345678"
    assert response["candidates"][0]["curation_status"] == "UNASSESSED_CANDIDATE"
    assert "not variant evidence" in response["interpretation"]
    assert len(db.added) == 1
    evidence = db.added[0]
    assert isinstance(evidence, Evidence)
    assert evidence.evidence_type == "LITERATURE"
    assert evidence.direction == "UNKNOWN"
    assert evidence.source_record_id == "12345678"
    assert evidence.payload["response_sha256"] == "a" * 64
    assert evidence.payload["interpretive_use"] == "BIBLIOGRAPHIC_CANDIDATE_REQUIRES_HUMAN_CURATION"
    assert "abstract" not in evidence.payload
    assert execution_record.status == "COMPLETED"
    assert db.commits == 2


def test_literature_provider_outage_is_persisted_as_retryable_failure(monkeypatch):
    from backend.app.adapters.literature.pubmed import PubMedLiteratureError

    error = PubMedLiteratureError("PUBMED_TIMEOUT", "timed out", retryable=True)
    literature, analysis_id, variant_id, db, principal, execution_record = _successful_route_context(
        monkeypatch,
        provider_error=error,
    )

    with pytest.raises(HTTPException) as exc:
        literature.search_pubmed_candidates(
            analysis_id,
            variant_id,
            literature.PubMedSearchRequest(gene_symbol="PAH"),
            db,
            principal,
            idempotency_key="literature-test-key-0003",
        )

    assert exc.value.status_code == 503
    assert execution_record.status == "RETRYABLE_FAILURE"
    assert db.added == []
    assert db.commits == 2


def test_late_provider_result_cannot_overwrite_a_superseded_attempt(monkeypatch):
    literature, analysis_id, variant_id, db, principal, execution_record = _successful_route_context(
        monkeypatch,
        execution_status_on_search="RETRYABLE_FAILURE",
    )

    with pytest.raises(HTTPException) as exc:
        literature.search_pubmed_candidates(
            analysis_id,
            variant_id,
            literature.PubMedSearchRequest(gene_symbol="PAH"),
            db,
            principal,
            idempotency_key="literature-late-attempt-0006",
        )

    assert exc.value.status_code == 409
    assert "ATTEMPT_SUPERSEDED" in exc.value.detail
    assert db.added == []
    assert db.rollbacks == 1


def test_literature_search_commits_evidence_execution_and_audit_to_database(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from backend.app.adapters.literature.pubmed import (
        PubMedLiteratureCandidate,
        PubMedSearchResult,
    )
    from backend.app.api.v1 import literature
    from backend.app.infrastructure.db.base import Base
    from backend.app.infrastructure.db.models import (
        Analysis,
        Annotation,
        AuditEvent,
        Case,
        Evidence,
        Organization,
        Resource,
        ResourceExecutionRecord,
        ResourceQualification,
        User,
        Variant,
    )

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'literature.db'}")
    Base.metadata.create_all(engine)
    analysis_id, variant_id, organization_id = uuid4(), uuid4(), uuid4()
    case_id, user_id, resource_id, qualification_id = uuid4(), uuid4(), uuid4(), uuid4()
    contract = {
        "provider_id": "PUBMED",
        "provider_version": "ncbi-eutils-pubmed-v1",
        "access_method": "HTTPS",
        "endpoint": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        "execution_scope": "ORGANIZATION_MANAGED",
        "toolchain": {"contact_email": "lab@example.org"},
    }
    with Session(engine, expire_on_commit=False) as db:
        organization = Organization(id=organization_id, name="Literature Lab", external_identifier=str(organization_id))
        user = User(
            id=user_id,
            organization_id=organization_id,
            external_subject=str(user_id),
            email="reviewer@example.org",
            display_name="Reviewer",
            role="bioinformatician",
            status="ACTIVE",
        )
        case = Case(
            id=case_id,
            organization_id=organization_id,
            case_identifier="LIT-001",
            status="OPEN",
            clinical_context={},
            language="en",
            created_by=user_id,
        )
        analysis = Analysis(
            id=analysis_id,
            case_id=case_id,
            analysis_type="VARIANT_INTERPRETATION",
            workflow_id="variant-v1",
            workflow_version="1",
            status="SUCCEEDED",
            reference_build="GRCh38",
            configuration={},
            created_by=user_id,
        )
        variant = Variant(
            id=variant_id,
            genome_build="GRCh38",
            chromosome="12",
            position=103232123,
            reference="G",
            alternate="A",
            normalization_status="NORMALIZED",
            canonical_key="GRCh38:12:103232123:G:A",
            identifiers={"dbsnp": "rs5030858"},
        )
        annotation = Annotation(
            id=uuid4(),
            analysis_id=analysis_id,
            variant_id=variant_id,
            provider_name="VEP",
            provider_version="test-v1",
            payload={"transcript_consequences": [{"gene_symbol": "PAH"}]},
        )
        resource = Resource(
            id=resource_id,
            organization_id=organization_id,
            name="NCBI PubMed E-utilities",
            provider="PUBMED",
            resource_type="EVIDENCE",
            version="2026-01",
            genome_build=None,
            access_method="HTTPS",
            license_text="NCBI E-utilities metadata terms",
            checksum=None,
            location=contract["endpoint"],
            status="ACTIVE",
            population_definition=None,
            metadata_json={"capabilities": ["LITERATURE"]},
        )
        qualification = ResourceQualification(
            id=qualification_id,
            resource_id=resource_id,
            qualification_version="qualification-1",
            status="QUALIFIED",
            checks_json={"execution_contract": contract},
            qualified_by=user_id,
        )
        db.add_all([organization, user, case, analysis, variant, annotation, resource, qualification])
        db.commit()

        principal = SimpleNamespace(user_id=user_id, role="bioinformatician")
        monkeypatch.setattr(literature, "get_accessible_analysis", lambda *_args: analysis)
        monkeypatch.setattr(literature, "require_role", lambda *_args: None)
        monkeypatch.setattr(literature, "get_analysis_variant", lambda *_args: variant)
        monkeypatch.setattr(
            literature,
            "build_resource_execution_plan",
            lambda *_args, **_kwargs: SimpleNamespace(
                for_capability=lambda _capability: (SimpleNamespace(resource=resource),)
            ),
        )
        candidate = PubMedLiteratureCandidate(
            pmid="12345678",
            title="A study",
            citation="Example Author. Journal. 2024",
            publication_year=2024,
            doi="10.1000/example",
            source_url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
        )
        result = PubMedSearchResult(
            status="SUCCESS",
            query='("PAH"[Title/Abstract]) AND ("rs5030858"[Title/Abstract])',
            candidates=(candidate,),
            retrieved_at="2026-11-17T00:00:00+00:00",
            response_sha256="b" * 64,
            result_count=1,
        )
        provider_calls = []
        provider_state = {"crash_next": False}

        def search_gene(**_kwargs):
            provider_calls.append(True)
            if provider_state["crash_next"]:
                provider_state["crash_next"] = False
                raise KeyboardInterrupt("simulated worker interruption")
            return result

        implementation = SimpleNamespace(factory=lambda _contract: SimpleNamespace(search_gene=search_gene))
        monkeypatch.setattr(
            literature,
            "register_builtin_providers",
            lambda: SimpleNamespace(require=lambda **_kwargs: implementation),
        )

        response = literature.search_pubmed_candidates(
            analysis_id,
            variant_id,
            literature.PubMedSearchRequest(gene_symbol="PAH"),
            db,
            principal,
            idempotency_key="literature-test-key-0004",
        )
        assert response["status"] == "SUCCESS"
        replay = literature.search_pubmed_candidates(
            analysis_id,
            variant_id,
            literature.PubMedSearchRequest(gene_symbol="PAH"),
            db,
            principal,
            idempotency_key="literature-test-key-0004",
        )
        assert replay["idempotent_replay"] is True
        assert replay["execution_id"] == response["execution_id"]
        assert replay["candidates"][0]["evidence_id"] == response["candidates"][0]["evidence_id"]
        assert len(provider_calls) == 1

        # Simulate process loss after the STARTED record commits but before the
        # provider returns, then verify the same key recovers as attempt 1.
        recovery_key = "literature-recovery-key-0005"
        provider_state["crash_next"] = True
        with pytest.raises(KeyboardInterrupt):
            literature.search_pubmed_candidates(
                analysis_id,
                variant_id,
                literature.PubMedSearchRequest(gene_symbol="PAH"),
                db,
                principal,
                idempotency_key=recovery_key,
            )
        # Idempotency keys are hashed before persistence, so retrieve the row by
        # its saved query metadata instead of looking for the raw key.
        abandoned = db.scalar(
            select(ResourceExecutionRecord).where(
                ResourceExecutionRecord.analysis_id == analysis_id,
                ResourceExecutionRecord.status == "STARTED",
            )
        )
        assert abandoned is not None
        with pytest.raises(literature.HTTPException) as in_progress:
            literature.search_pubmed_candidates(
                analysis_id,
                variant_id,
                literature.PubMedSearchRequest(gene_symbol="PAH"),
                db,
                principal,
                idempotency_key=recovery_key,
            )
        assert in_progress.value.status_code == 409
        assert in_progress.value.detail == "PUBMED_SEARCH_IN_PROGRESS"
        assert len(provider_calls) == 2
        abandoned.started_at = datetime.now(UTC) - timedelta(minutes=2)
        db.commit()
        recovered = literature.search_pubmed_candidates(
            analysis_id,
            variant_id,
            literature.PubMedSearchRequest(gene_symbol="PAH"),
            db,
            principal,
            idempotency_key=recovery_key,
        )
        assert recovered["status"] == "SUCCESS"
        assert len(provider_calls) == 3

    # Verify committed state from a fresh session rather than the writer's identity map.
    with Session(engine) as verification_db:
        evidence = verification_db.scalar(select(Evidence).where(Evidence.analysis_id == analysis_id))
        assert evidence is not None
        assert evidence.source_record_id == "12345678"
        assert evidence.payload["response_sha256"] == "b" * 64
        executions = list(
            verification_db.scalars(
                select(ResourceExecutionRecord)
                .where(ResourceExecutionRecord.analysis_id == analysis_id)
                .order_by(ResourceExecutionRecord.attempt)
            ).all()
        )
        assert len(executions) == 3
        assert sorted(item.attempt for item in executions) == [0, 0, 1]
        assert sorted(item.status for item in executions) == ["COMPLETED", "COMPLETED", "RETRYABLE_FAILURE"]
        assert any(item.attempt == 1 and item.status == "COMPLETED" for item in executions)
        assert all(item.resource_id == resource_id for item in executions)
        assert all(item.qualification_id == qualification_id for item in executions)
        assert executions[-1].response_sha256 == "b" * 64
        audits = list(
            verification_db.scalars(
                select(AuditEvent).where(
                    AuditEvent.analysis_id == analysis_id,
                    AuditEvent.event_type.in_(
                        {
                            "PUBMED_LITERATURE_CANDIDATES_RETRIEVED",
                            "PUBMED_LITERATURE_SEARCH_RECOVERED",
                        }
                    ),
                )
            ).all()
        )
        assert len(audits) == 3
        assert any(item.event_type == "PUBMED_LITERATURE_SEARCH_RECOVERED" for item in audits)
        assert all(item.resource_versions["pubmed"]["qualification_id"] == str(qualification_id) for item in audits)
    engine.dispose()
