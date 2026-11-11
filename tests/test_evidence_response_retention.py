from datetime import UTC, datetime, timedelta
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
    Analysis, Case, Evidence, Organization, OrganizationMembership, Resource,
    ProviderRetentionApproval, ResourceDiscovery, User, Variant,
)


def _seed(tmp_path, monkeypatch, *, license_status="NOT_REQUIRED", retention_permission="PERMITTED"):
    import backend.app.domain.evidence_response_retention as retention

    engine = create_engine("sqlite+pysqlite:///:memory:")
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
