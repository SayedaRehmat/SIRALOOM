from datetime import UTC, datetime, timedelta
import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain.evidence_response_retention import (
    approve_provider_retention,
    revoke_provider_retention,
    retain_provider_response_bytes,
    verify_evidence_response_artifact,
)
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis, Artifact, Case, Evidence, Organization, OrganizationMembership, Resource,
    ProviderRetentionApproval, ProviderRetentionApprovalAction, Report,
    ResourceDiscovery, User, Variant,
)


def _seed(tmp_path, monkeypatch, *, license_status="NOT_REQUIRED", retention_permission="PERMITTED", database_url=None):
    import backend.app.domain.evidence_response_retention as retention

    engine = create_engine(database_url or "sqlite+pysqlite:///:memory:", pool_pre_ping=True)
    Base.metadata.create_all(engine)
    db = Session(engine)
    organization = Organization(id=uuid4(), name="Retention test lab")
    user = User(
        id=uuid4(), organization_id=organization.id, display_name="Reviewer",
        role="LAB_ADMIN", status="ACTIVE",
    )
    membership = OrganizationMembership(
        id=uuid4(), organization_id=organization.id, user_id=user.id,
        role="LAB_ADMIN", status="ACTIVE",
    )
    case = Case(
        id=uuid4(), organization_id=organization.id, case_identifier="CASE-1",
        status="ACTIVE", clinical_context={}, language="en", created_by=user.id,
    )
    analysis = Analysis(
        id=uuid4(), case_id=case.id, parent_analysis_id=None, assay_id=None,
        analysis_type="RESEARCH", workflow_id="variant-v1", workflow_version="test",
        status="COMPLETED", queue_task_id=None, reference_build="GRCh38",
        configuration={"workflow_purpose": "RESEARCH", "research_justification": "Retention integrity test"},
        started_at=None, completed_at=None, created_by=user.id, analysis_version=1,
    )
    variant = Variant(
        id=uuid4(), genome_build="GRCh38", chromosome="1", position=101,
        reference="A", alternate="G", normalization_status="NORMALIZED",
        canonical_key=f"GRCh38:1:101:A:G:{uuid4()}", identifiers={},
    )
    resource = Resource(
        id=uuid4(), organization_id=None, name="Test provider release",
        provider="TestProvider", resource_type="EVIDENCE", version="release-1",
        genome_build="GRCh38", access_method="HTTPS", license_text=None,
        checksum=None, location="https://provider.example/api", status="ACTIVE",
        population_definition=None, metadata_json={},
    )
    discovery = ResourceDiscovery(
        id=uuid4(), resource_id=resource.id, publisher="Test Publisher",
        canonical_source_url="https://provider.example/",
        artifact_url="https://provider.example/api/release-1",
        release_identity=resource.version, access_mode="PUBLIC",
        license_status=license_status,
        license_url="https://provider.example/license" if license_status == "VERIFIED" else None,
        terms_url="https://provider.example/terms", checksum_status="NOT_PUBLISHED", expected_sha256=None,
        expected_size_bytes=None, authority_evidence_url="https://provider.example/about",
        status="DISCOVERED", metadata_json={
            "raw_response_retention": retention_permission,
            "raw_response_retention_reviewed_by": "test-reviewer",
            "raw_response_retention_reviewed_at": "2026-11-11T00:00:00Z",
        },
    )
    db.add_all([organization, user, membership, case, analysis, variant, resource, discovery])
    db.flush()
    store = ArtifactStore(tmp_path / "artifact-store")
    monkeypatch.setattr(retention, "artifact_store_for_organization", lambda *_args, **_kwargs: store)
    monkeypatch.setattr(retention, "artifact_store_for_uri", lambda *_args, **_kwargs: store)
    if retention_permission == "PERMITTED" and license_status in {"VERIFIED", "NOT_REQUIRED"}:
        import hashlib
        terms_path = tmp_path / f"terms-{uuid4().hex}.txt"
        terms_bytes = b"Reviewed provider license and raw response retention terms."
        terms_path.write_bytes(terms_bytes)
        terms_artifact = store.put_file(
            db=db, case_id=case.id, analysis_id=None, source_path=terms_path,
            filename="provider-terms.txt", artifact_type="LICENSE_TERMS_EVIDENCE",
            media_type="text/plain", genome_build=None, validation_status="VALIDATED",
            metadata={"resource_id": str(resource.id), "release_identity": resource.version},
        )
        approve_provider_retention(
            db, organization_id=organization.id, resource_discovery_id=discovery.id,
            reviewer_id=user.id, permission_scope=["RAW_PROVIDER_RESPONSE_RETENTION"],
            reason="Reviewed exact provider terms for retention scope.",
            terms_evidence_artifact_id=terms_artifact.id,
            terms_evidence_sha256=hashlib.sha256(terms_bytes).hexdigest(),
        )
    return db, store, case, analysis, variant, resource


def _persist_raw(store, db, case, analysis, resource, tmp_path, raw=b'{"source":"exact"}'):
    source = tmp_path / f"source-{uuid4().hex}.bin"
    source.write_bytes(raw)
    import hashlib

    digest = hashlib.sha256(raw).hexdigest()
    approval = db.scalar(select(ProviderRetentionApproval).where(
        ProviderRetentionApproval.resource_id == resource.id,
        ProviderRetentionApproval.status == "APPROVED",
    ))
    artifact = store.put_file(
        db=db, case_id=case.id, analysis_id=analysis.id, source_path=source,
        filename="provider-response.bin", artifact_type="PROVIDER_RESPONSE_RAW",
        media_type="application/json", genome_build="GRCh38",
        validation_status="VALIDATED",
        metadata={
            "resource_id": str(resource.id), "request_fingerprint": "request-1",
            "raw_response_sha256": digest, "raw_response_size_bytes": len(raw),
            "retention_approval_id": str(approval.id),
            "retention_approval_version": approval.version,
            "retention_approval_terms_evidence_artifact_id": str(approval.terms_evidence_artifact_id),
            "retention_approval_terms_evidence_sha256": approval.terms_evidence_sha256,
        },
    )
    return artifact, digest, len(raw)


def _evidence(analysis, variant, resource, artifact, digest, size):
    return Evidence(
        id=uuid4(), variant_id=variant.id, analysis_id=analysis.id,
        evidence_type="CLINICAL_ASSERTION", statement="Test assertion",
        direction="SUPPORTS", source_name="TestProvider", source_version="release-1",
        resource_id=resource.id, source_record_id="record-1",
        request_fingerprint="request-1", response_sha256=None,
        response_artifact_id=artifact.id, response_artifact_sha256=digest,
        response_artifact_size_bytes=size, response_retention_status="RETAINED",
        response_retention_reason="License permits retention.", request_metadata={},
        observed_at=None, observation_ids=[], payload={},
        created_by_type="SYSTEM", created_by_id="test", evidence_fingerprint=uuid4().hex,
    )


def test_verified_response_artifact_passes_byte_and_lineage_verification(tmp_path, monkeypatch):
    db, store, case, analysis, variant, resource = _seed(tmp_path, monkeypatch)
    artifact, digest, size = _persist_raw(store, db, case, analysis, resource, tmp_path)
    evidence = _evidence(analysis, variant, resource, artifact, digest, size)
    db.add(evidence)
    db.flush()
    assert verify_evidence_response_artifact(db, evidence) is True


def test_missing_response_artifact_reference_fails_closed(tmp_path, monkeypatch):
    db, _store, _case, analysis, variant, resource = _seed(tmp_path, monkeypatch)
    evidence = _evidence(analysis, variant, resource, type("Missing", (), {"id": None})(), None, None)
    db.add(evidence)
    db.flush()
    with pytest.raises(ValueError, match="missing its artifact ID"):
        verify_evidence_response_artifact(db, evidence)


def test_substituted_response_artifact_fails_digest_binding(tmp_path, monkeypatch):
    db, store, case, analysis, variant, resource = _seed(tmp_path, monkeypatch)
    artifact, digest, size = _persist_raw(store, db, case, analysis, resource, tmp_path)
    other, _other_digest, _other_size = _persist_raw(
        store, db, case, analysis, resource, tmp_path, raw=b'{"source":"substituted"}'
    )
    evidence = _evidence(analysis, variant, resource, artifact, digest, size)
    evidence.response_artifact_id = other.id
    db.add(evidence)
    db.flush()
    with pytest.raises(ValueError, match="identity, case, analysis, digest or size"):
        verify_evidence_response_artifact(db, evidence)


def test_corrupted_response_bytes_fail_verification(tmp_path, monkeypatch):
    db, store, case, analysis, variant, resource = _seed(tmp_path, monkeypatch)
    artifact, digest, size = _persist_raw(store, db, case, analysis, resource, tmp_path)
    evidence = _evidence(analysis, variant, resource, artifact, digest, size)
    db.add(evidence)
    db.flush()
    store.local_path(artifact.storage_uri).write_bytes(b"tampered")
    with pytest.raises(Exception):
        verify_evidence_response_artifact(db, evidence)


def test_cross_case_response_artifact_reference_fails(tmp_path, monkeypatch):
    db, store, case, analysis, variant, resource = _seed(tmp_path, monkeypatch)
    other_case = Case(
        id=uuid4(), organization_id=case.organization_id, case_identifier="CASE-2",
        status="ACTIVE", clinical_context={}, language="en", created_by=case.created_by,
    )
    db.add(other_case)
    db.flush()
    artifact, digest, size = _persist_raw(store, db, case, analysis, resource, tmp_path)
    foreign, _foreign_digest, _foreign_size = _persist_raw(
        store, db, other_case, analysis, resource, tmp_path, raw=b'{"foreign":true}'
    )
    evidence = _evidence(analysis, variant, resource, artifact, digest, size)
    evidence.response_artifact_id = foreign.id
    db.add(evidence)
    db.flush()
    with pytest.raises(ValueError, match="identity, case, analysis, digest or size"):
        verify_evidence_response_artifact(db, evidence)


def test_unreviewed_license_never_persists_raw_response(tmp_path, monkeypatch):
    db, _store, _case, analysis, _variant, resource = _seed(
        tmp_path, monkeypatch, license_status="REVIEW_REQUIRED"
    )
    result = retain_provider_response_bytes(
        db, analysis=analysis, resource=resource,
        provider_id="TestProvider", provider_version="1",
        request_fingerprint="request-1", raw_response_bytes=b"do-not-retain",
    )
    assert result.status == "REVIEW_REQUIRED"
    assert result.artifact_id is None
    assert result.sha256 is None
    assert result.size_bytes is None


def test_permitted_license_retains_exact_response_bytes(tmp_path, monkeypatch):
    db, store, case, analysis, _variant, resource = _seed(
        tmp_path, monkeypatch, license_status="VERIFIED"
    )
    result = retain_provider_response_bytes(
        db, analysis=analysis, resource=resource,
        provider_id="TestProvider", provider_version="1",
        request_fingerprint="request-1", raw_response_bytes=b'{"raw":"provider bytes"}',
        media_type="application/json",
    )
    assert result.status == "RETAINED"
    assert result.artifact_id is not None
    artifact = db.get(__import__("backend.app.infrastructure.db.models", fromlist=["Artifact"]).Artifact, result.artifact_id)
    assert artifact.case_id == case.id
    assert artifact.analysis_id == analysis.id
    assert store.local_path(artifact.storage_uri).read_bytes() == b'{"raw":"provider bytes"}'

def test_restricted_license_marks_response_not_permitted_without_storage(tmp_path, monkeypatch):
    db, _store, _case, analysis, _variant, resource = _seed(
        tmp_path, monkeypatch, license_status="RESTRICTED"
    )
    result = retain_provider_response_bytes(
        db, analysis=analysis, resource=resource,
        provider_id="TestProvider", provider_version="1",
        request_fingerprint="request-1", raw_response_bytes=b"restricted-provider-bytes",
    )
    assert result.status == "NOT_PERMITTED"
    assert result.artifact_id is None
    assert result.sha256 is None
    assert result.size_bytes is None

def test_verified_license_without_explicit_raw_retention_scope_requires_review(tmp_path, monkeypatch):
    db, _store, _case, analysis, _variant, resource = _seed(
        tmp_path, monkeypatch, license_status="VERIFIED", retention_permission="UNKNOWN"
    )
    result = retain_provider_response_bytes(
        db, analysis=analysis, resource=resource,
        provider_id="TestProvider", provider_version="1",
        request_fingerprint="request-1", raw_response_bytes=b"not-approved-for-retention",
    )
    assert result.status == "REVIEW_REQUIRED"
    assert result.artifact_id is None



def test_revoked_approval_blocks_future_evidence_verification(tmp_path, monkeypatch):
    db, store, case, analysis, variant, resource = _seed(tmp_path, monkeypatch)
    artifact, digest, size = _persist_raw(store, db, case, analysis, resource, tmp_path)
    evidence = _evidence(analysis, variant, resource, artifact, digest, size)
    db.add(evidence)
    db.flush()
    approval = db.scalar(select(ProviderRetentionApproval).where(
        ProviderRetentionApproval.resource_id == resource.id,
    ))
    revoke_provider_retention(
        db, approval_id=approval.id, actor_id=approval.reviewer_id,
        reason="Source terms review was withdrawn.",
    )
    db.flush()
    with pytest.raises(ValueError, match="missing, revoked, or out of scope"):
        verify_evidence_response_artifact(db, evidence)


def test_expired_approval_prevents_new_raw_response_retention(tmp_path, monkeypatch):
    db, _store, _case, analysis, _variant, resource = _seed(tmp_path, monkeypatch)
    approval = db.scalar(select(ProviderRetentionApproval).where(
        ProviderRetentionApproval.resource_id == resource.id,
    ))
    approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()
    result = retain_provider_response_bytes(
        db, analysis=analysis, resource=resource, provider_id="TestProvider",
        provider_version="1", request_fingerprint="expired-request",
        raw_response_bytes=b"must-not-be-retained",
    )
    assert result.status == "REVIEW_REQUIRED"
    assert result.artifact_id is None
    assert approval.status == "EXPIRED"
    expiry_action = db.scalar(select(ProviderRetentionApprovalAction).where(
        ProviderRetentionApprovalAction.approval_id == approval.id,
        ProviderRetentionApprovalAction.action == "EXPIRE",
    ))
    assert expiry_action is not None
    assert expiry_action.actor_id is None



def test_provider_response_retry_is_idempotent_and_write_once(tmp_path, monkeypatch):
    db, _store, _case, analysis, _variant, resource = _seed(tmp_path, monkeypatch)
    first = retain_provider_response_bytes(
        db, analysis=analysis, resource=resource, provider_id="TestProvider",
        provider_version="1", request_fingerprint="retry-stable",
        raw_response_bytes=b'{"stable":"bytes"}',
    )
    retry = retain_provider_response_bytes(
        db, analysis=analysis, resource=resource, provider_id="TestProvider",
        provider_version="1", request_fingerprint="retry-stable",
        raw_response_bytes=b'{"stable":"bytes"}',
    )
    assert retry.status == "RETAINED"
    assert retry.artifact_id == first.artifact_id
    with pytest.raises(ValueError, match="Write-once provider response identity"):
        retain_provider_response_bytes(
            db, analysis=analysis, resource=resource, provider_id="TestProvider",
            provider_version="1", request_fingerprint="retry-stable",
            raw_response_bytes=b'{"stable":"changed"}',
        )


def test_reanalysis_creates_distinct_analysis_bound_response_artifact(tmp_path, monkeypatch):
    db, _store, _case, parent, _variant, resource = _seed(tmp_path, monkeypatch)
    first = retain_provider_response_bytes(
        db, analysis=parent, resource=resource, provider_id="TestProvider",
        provider_version="1", request_fingerprint="same-provider-query",
        raw_response_bytes=b'{"same":"release"}',
    )
    child = Analysis(
        id=uuid4(), case_id=parent.case_id, parent_analysis_id=parent.id,
        assay_id=None, analysis_type="RESEARCH", workflow_id="variant-v1",
        workflow_version="test", status="COMPLETED", queue_task_id=None,
        reference_build="GRCh38",
        configuration={"workflow_purpose": "RESEARCH", "research_justification": "Reanalysis lineage test"},
        started_at=None, completed_at=None, created_by=parent.created_by,
        analysis_version=2,
    )
    db.add(child)
    db.flush()
    second = retain_provider_response_bytes(
        db, analysis=child, resource=resource, provider_id="TestProvider",
        provider_version="1", request_fingerprint="same-provider-query",
        raw_response_bytes=b'{"same":"release"}',
    )
    assert first.artifact_id != second.artifact_id
    first_artifact = db.get(__import__("backend.app.infrastructure.db.models", fromlist=["Artifact"]).Artifact, first.artifact_id)
    second_artifact = db.get(__import__("backend.app.infrastructure.db.models", fromlist=["Artifact"]).Artifact, second.artifact_id)
    assert first_artifact.analysis_id == parent.id
    assert second_artifact.analysis_id == child.id



def test_expired_approval_can_be_replaced_with_audited_new_version(tmp_path, monkeypatch):
    db, _store, case, _analysis, _variant, resource = _seed(tmp_path, monkeypatch)
    approval = db.scalar(select(ProviderRetentionApproval).where(
        ProviderRetentionApproval.resource_id == resource.id,
    ))
    terms_artifact = db.get(
        __import__("backend.app.infrastructure.db.models", fromlist=["Artifact"]).Artifact,
        approval.terms_evidence_artifact_id,
    )
    reviewer = db.get(User, approval.reviewer_id)
    discovery = db.get(ResourceDiscovery, approval.resource_discovery_id)
    import hashlib
    terms_sha256 = terms_artifact.sha256
    approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()
    renewed = approve_provider_retention(
        db, organization_id=case.organization_id,
        resource_discovery_id=discovery.id, reviewer_id=reviewer.id,
        permission_scope=["RAW_PROVIDER_RESPONSE_RETENTION"],
        reason="Renewed after expiry and a fresh terms review.",
        terms_evidence_artifact_id=terms_artifact.id,
        terms_evidence_sha256=terms_sha256,
    )
    assert approval.status == "EXPIRED"
    assert renewed.version == approval.version + 1
    actions = db.scalars(select(ProviderRetentionApprovalAction).where(
        ProviderRetentionApprovalAction.approval_id == approval.id,
    )).all()
    assert any(action.action == "EXPIRE" for action in actions)

def test_tampered_terms_evidence_blocks_new_response_retention(tmp_path, monkeypatch):
    db, store, _case, analysis, _variant, resource = _seed(tmp_path, monkeypatch)
    approval = db.scalar(select(ProviderRetentionApproval).where(
        ProviderRetentionApproval.resource_id == resource.id,
        ProviderRetentionApproval.status == "APPROVED",
    ))
    terms = db.get(Artifact, approval.terms_evidence_artifact_id)
    store.local_path(terms.storage_uri).write_bytes(b"tampered terms")
    result = retain_provider_response_bytes(
        db, analysis=analysis, resource=resource, provider_id="TestProvider",
        provider_version="1", request_fingerprint="tampered-terms",
        raw_response_bytes=b"must-not-be-retained", store=store,
    )
    assert result.status == "REVIEW_REQUIRED"
    assert approval.status == "APPROVED"

def test_local_evidence_source_without_release_snapshot_fails_closed(tmp_path, monkeypatch):
    db, store, case, analysis, variant, resource = _seed(tmp_path, monkeypatch)
    resource.access_method = "LOCAL"
    artifact, digest, size = _persist_raw(store, db, case, analysis, resource, tmp_path)
    evidence = _evidence(analysis, variant, resource, artifact, digest, size)
    db.add(evidence)
    db.flush()
    with pytest.raises(ValueError, match="missing its immutable source-release artifact"):
        verify_evidence_response_artifact(db, evidence)



def test_worker_retry_after_approval_expiry_cannot_reuse_retained_response(tmp_path, monkeypatch):
    db, _store, _case, analysis, _variant, resource = _seed(tmp_path, monkeypatch)
    first = retain_provider_response_bytes(
        db, analysis=analysis, resource=resource, provider_id="TestProvider",
        provider_version="1", request_fingerprint="retry-after-expiry",
        raw_response_bytes=b'{"immutable":"response"}',
    )
    assert first.status == "RETAINED"

    approval = db.scalar(select(ProviderRetentionApproval).where(
        ProviderRetentionApproval.resource_id == resource.id,
    ))
    approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()

    retry = retain_provider_response_bytes(
        db, analysis=analysis, resource=resource, provider_id="TestProvider",
        provider_version="1", request_fingerprint="retry-after-expiry",
        raw_response_bytes=b'{"immutable":"response"}',
    )

    assert retry.status == "REVIEW_REQUIRED"
    assert retry.artifact_id is None
    assert approval.status == "EXPIRED"


@pytest.mark.integration
def test_postgres_two_workers_expire_one_approval_once(tmp_path, monkeypatch):
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    db, _store, _case, analysis, _variant, resource = _seed(
        tmp_path, monkeypatch, database_url=database_url
    )
    engine = db.get_bind()
    approval = db.scalar(select(ProviderRetentionApproval).where(
        ProviderRetentionApproval.resource_id == resource.id,
        ProviderRetentionApproval.status == "APPROVED",
    ))
    approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    analysis_id, resource_id = analysis.id, resource.id
    db.commit()
    db.close()

    barrier = threading.Barrier(2)
    results = []
    errors = []

    def worker():
        try:
            with Session(engine) as session:
                local_analysis = session.get(Analysis, analysis_id)
                local_resource = session.get(Resource, resource_id)
                barrier.wait(timeout=5)
                result = retain_provider_response_bytes(
                    session, analysis=local_analysis, resource=local_resource,
                    provider_id="TestProvider", provider_version="1",
                    request_fingerprint="parallel-expiry",
                    raw_response_bytes=b'{"parallel":"same"}',
                )
                results.append(result)
                session.commit()
        except Exception as exc:  # surfaced in the main test thread  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    try:
        assert all(not thread.is_alive() for thread in threads)
        assert not errors
        assert len(results) == 2
        assert all(result.status == "REVIEW_REQUIRED" for result in results)
        with Session(engine) as session:
            final_approval = session.get(ProviderRetentionApproval, approval.id)
            actions = list(session.scalars(select(ProviderRetentionApprovalAction).where(
                ProviderRetentionApprovalAction.approval_id == approval.id,
                ProviderRetentionApprovalAction.action == "EXPIRE",
            )))
            assert final_approval.status == "EXPIRED"
            assert len(actions) == 1
    finally:
        engine.dispose()


@pytest.mark.integration
def test_postgres_revocation_serializes_with_worker_retry(tmp_path, monkeypatch):
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    import backend.app.domain.evidence_response_retention as retention

    db, _store, _case, analysis, _variant, resource = _seed(
        tmp_path, monkeypatch, database_url=database_url
    )
    engine = db.get_bind()
    approval = db.scalar(select(ProviderRetentionApproval).where(
        ProviderRetentionApproval.resource_id == resource.id,
        ProviderRetentionApproval.status == "APPROVED",
    ))
    approval_id, actor_id = approval.id, approval.reviewer_id
    analysis_id, resource_id = analysis.id, resource.id
    db.commit()
    db.close()

    revoker_has_lock = threading.Event()
    allow_revocation = threading.Event()
    worker_query_started = threading.Event()
    original_authorized_reviewer = retention._authorized_reviewer

    def pause_revoker(session, *, organization_id, reviewer_id):
        if threading.current_thread().name == "approval-revoker":
            revoker_has_lock.set()
            if not allow_revocation.wait(timeout=10):
                raise TimeoutError("revocation test gate was not released")
        return original_authorized_reviewer(
            session, organization_id=organization_id, reviewer_id=reviewer_id
        )

    monkeypatch.setattr(retention, "_authorized_reviewer", pause_revoker)

    from sqlalchemy import event

    def observe_worker_select(_conn, _cursor, statement, _parameters, _context, _many):
        if (
            threading.current_thread().name == "retention-worker"
            and "provider_retention_approvals" in statement.lower()
        ):
            worker_query_started.set()

    event.listen(engine, "before_cursor_execute", observe_worker_select)
    results = []
    errors = []

    def revoke():
        try:
            with Session(engine) as session:
                retention.revoke_provider_retention(
                    session, approval_id=approval_id, actor_id=actor_id,
                    reason="Concurrent revocation integration test",
                )
                session.commit()
        except Exception as exc:  # surfaced in the main test thread  # noqa: BLE001
            errors.append(exc)

    def retry():
        try:
            with Session(engine) as session:
                local_analysis = session.get(Analysis, analysis_id)
                local_resource = session.get(Resource, resource_id)
                result = retain_provider_response_bytes(
                    session, analysis=local_analysis, resource=local_resource,
                    provider_id="TestProvider", provider_version="1",
                    request_fingerprint="retry-racing-revocation",
                    raw_response_bytes=b'{"must":"not-reuse"}',
                )
                results.append(result)
                session.commit()
        except Exception as exc:  # surfaced in the main test thread  # noqa: BLE001
            errors.append(exc)

    revoker = threading.Thread(target=revoke, name="approval-revoker")
    worker = threading.Thread(target=retry, name="retention-worker")
    try:
        revoker.start()
        assert revoker_has_lock.wait(timeout=5)
        worker.start()
        assert worker_query_started.wait(timeout=5)
        allow_revocation.set()
        revoker.join(timeout=10)
        worker.join(timeout=10)
        assert not revoker.is_alive()
        assert not worker.is_alive()
        assert not errors
        assert len(results) == 1
        assert results[0].status == "REVIEW_REQUIRED"
        with Session(engine) as session:
            assert session.get(ProviderRetentionApproval, approval_id).status == "REVOKED"
    finally:
        allow_revocation.set()
        event.remove(engine, "before_cursor_execute", observe_worker_select)
        revoker.join(timeout=2)
        worker.join(timeout=2)
        engine.dispose()


@pytest.mark.integration
def test_postgres_evidence_verification_racing_expiry_fails_closed(tmp_path, monkeypatch):
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    db, store, case, analysis, variant, resource = _seed(
        tmp_path, monkeypatch, database_url=database_url
    )
    engine = db.get_bind()
    artifact, digest, size = _persist_raw(
        store, db, case, analysis, resource, tmp_path,
        raw=b'{"evidence":"must-be-revalidated"}',
    )
    evidence = _evidence(analysis, variant, resource, artifact, digest, size)
    db.add(evidence)
    db.flush()
    evidence_id, analysis_id, resource_id = evidence.id, analysis.id, resource.id
    approval = db.scalar(select(ProviderRetentionApproval).where(
        ProviderRetentionApproval.resource_id == resource.id,
        ProviderRetentionApproval.status == "APPROVED",
    ))
    approval_id = approval.id
    approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    db.close()

    barrier = threading.Barrier(2)
    outcomes = []
    errors = []

    def verify():
        try:
            with Session(engine) as session:
                row = session.get(Evidence, evidence_id)
                barrier.wait(timeout=5)
                try:
                    verify_evidence_response_artifact(session, row)
                    outcomes.append("VERIFIED")
                except ValueError:
                    outcomes.append("REJECTED")
                session.commit()
        except Exception as exc:  # surfaced in the main test thread  # noqa: BLE001
            errors.append(exc)

    def retry():
        try:
            with Session(engine) as session:
                local_analysis = session.get(Analysis, analysis_id)
                local_resource = session.get(Resource, resource_id)
                barrier.wait(timeout=5)
                result = retain_provider_response_bytes(
                    session, analysis=local_analysis, resource=local_resource,
                    provider_id="TestProvider", provider_version="1",
                    request_fingerprint="evidence-expiry-race",
                    raw_response_bytes=b'{"new":"response"}',
                )
                outcomes.append(result.status)
                session.commit()
        except Exception as exc:  # surfaced in the main test thread  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=verify, name="evidence-verifier"),
        threading.Thread(target=retry, name="expiry-retry"),
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        assert all(not thread.is_alive() for thread in threads)
        assert not errors
        assert sorted(outcomes) == ["REJECTED", "REVIEW_REQUIRED"]
        with Session(engine) as session:
            assert session.get(ProviderRetentionApproval, approval_id).status == "EXPIRED"
    finally:
        engine.dispose()


@pytest.mark.integration
def test_postgres_report_signout_waits_for_source_retention_revocation(tmp_path, monkeypatch):
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    import backend.app.domain.evidence_response_retention as retention
    from backend.app.domain import clinical_authorization
    from backend.app.reporting import finalization

    db, store, case, analysis, variant, resource = _seed(
        tmp_path, monkeypatch, database_url=database_url
    )
    engine = db.get_bind()
    response_artifact, digest, size = _persist_raw(
        store, db, case, analysis, resource, tmp_path,
        raw=b'{"report":"must-recheck-authorization"}',
    )
    evidence = _evidence(
        analysis, variant, resource, response_artifact, digest, size
    )
    db.add(evidence)
    db.flush()

    draft_path = tmp_path / "draft-report.pdf"
    draft_path.write_bytes(b"%PDF-1.4 test draft")
    draft_artifact = Artifact(
        id=uuid4(), case_id=case.id, analysis_id=analysis.id,
        artifact_type="REPORT_PDF", filename="draft.pdf",
        media_type="application/pdf", size_bytes=draft_path.stat().st_size,
        sha256=__import__("hashlib").sha256(draft_path.read_bytes()).hexdigest(),
        storage_uri="file:///draft-report.pdf", genome_build="GRCh38",
        validation_status="VALID", metadata_json={},
    )
    db.add(draft_artifact)
    report = Report(
        id=uuid4(), case_id=case.id, analysis_id=analysis.id,
        report_version=1, language="en", report_type="CLINICAL_INTERPRETATION",
        status="DRAFT", artifact_id=draft_artifact.id,
        content_json={"findings": []},
    )
    db.add(report)
    approval = db.scalar(select(ProviderRetentionApproval).where(
        ProviderRetentionApproval.resource_id == resource.id,
        ProviderRetentionApproval.status == "APPROVED",
    ))
    approval_id, actor_id = approval.id, approval.reviewer_id
    report_id, evidence_id = report.id, evidence.id
    db.commit()
    db.close()

    revoker_has_lock = threading.Event()
    allow_revocation = threading.Event()
    signout_query_started = threading.Event()
    original_authorized_reviewer = retention._authorized_reviewer

    def pause_revoker(session, *, organization_id, reviewer_id):
        if threading.current_thread().name == "report-approval-revoker":
            revoker_has_lock.set()
            if not allow_revocation.wait(timeout=10):
                raise TimeoutError("report/revocation test gate was not released")
        return original_authorized_reviewer(
            session, organization_id=organization_id, reviewer_id=reviewer_id
        )

    monkeypatch.setattr(retention, "_authorized_reviewer", pause_revoker)
    monkeypatch.setattr(
        clinical_authorization, "assert_analysis_clinical_authorization",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(finalization, "final_report_eligibility", lambda *_args, **_kwargs: (True, []))
    monkeypatch.setattr(
        finalization, "_verify_report_snapshot",
        lambda session, _report: verify_evidence_response_artifact(
            session, session.get(Evidence, evidence_id)
        ),
    )
    monkeypatch.setattr(
        finalization, "_persist_pdf_artifact",
        lambda _session, *, report, **_kwargs: _session.get(Artifact, report.artifact_id),
    )

    from sqlalchemy import event

    def observe_signout_approval_lock(_conn, _cursor, statement, _parameters, _context, _many):
        if (
            threading.current_thread().name == "report-signout"
            and "provider_retention_approvals" in statement.lower()
        ):
            signout_query_started.set()

    event.listen(engine, "before_cursor_execute", observe_signout_approval_lock)
    outcomes = []
    errors = []

    def revoke():
        try:
            with Session(engine) as session:
                retention.revoke_provider_retention(
                    session, approval_id=approval_id, actor_id=actor_id,
                    reason="Revoke source authorization during report sign-out test",
                )
                session.commit()
        except Exception as exc:  # surfaced in the main test thread  # noqa: BLE001
            errors.append(exc)

    def signout():
        try:
            with Session(engine) as session:
                finalization.finalize_report(
                    session, report_id=report_id, approver_id=actor_id,
                    reason="Source authorization race integration test",
                )
                session.commit()
                outcomes.append("FINALIZED")
        except finalization.ReportFinalizationError:
            outcomes.append("BLOCKED")
        except Exception as exc:  # surfaced in the main test thread  # noqa: BLE001
            errors.append(exc)

    revoker = threading.Thread(target=revoke, name="report-approval-revoker")
    signer = threading.Thread(target=signout, name="report-signout")
    try:
        revoker.start()
        assert revoker_has_lock.wait(timeout=5)
        signer.start()
        assert signout_query_started.wait(timeout=5)
        allow_revocation.set()
        revoker.join(timeout=10)
        signer.join(timeout=10)
        assert not revoker.is_alive()
        assert not signer.is_alive()
        assert not errors
        assert outcomes == ["BLOCKED"]
        with Session(engine) as session:
            assert session.get(ProviderRetentionApproval, approval_id).status == "REVOKED"
            assert session.get(Report, report_id).status == "DRAFT"
    finally:
        allow_revocation.set()
        event.remove(engine, "before_cursor_execute", observe_signout_approval_lock)
        revoker.join(timeout=2)
        signer.join(timeout=2)
        engine.dispose()
