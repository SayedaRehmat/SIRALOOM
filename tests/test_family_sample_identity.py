from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text

from backend.app.api.v1 import pedigree
from backend.app.infrastructure.db.models import (
    Analysis, Artifact, Case, PedigreeMember, PedigreeSampleBinding,
    PedigreeSampleIdentityEvidence, Specimen,
)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Audit:
    def __init__(self, _db):
        pass

    def record(self, **_kwargs):
        pass


class _BindingDB:
    def __init__(self, *, case, member, specimen, analysis, artifact, previous=None, evidence=None, workflow=None):
        self.objects = {
            Case: case,
            PedigreeMember: member,
            Specimen: specimen,
            Analysis: analysis,
            Artifact: artifact,
            PedigreeSampleBinding: previous,
            PedigreeSampleIdentityEvidence: evidence,
        }
        self.workflow = workflow
        self.scalar_results = []
        self.added = []
        self.commits = 0
        self.refresh_calls = []
        self.query_rows = []

    def get(self, model, _identifier, **_kwargs):
        return self.objects.get(model)

    def refresh(self, *args, **kwargs):
        self.refresh_calls.append((args, kwargs))
        return None

    def scalar(self, _statement):
        if self.scalar_results:
            return self.scalar_results.pop(0)
        if self.workflow is not None:
            result, self.workflow = self.workflow, None
            return result
        return None

    def scalars(self, _statement):
        return _Rows(self.query_rows.pop(0))

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.commits += 1


def _context():
    case_id, member_id, specimen_id, analysis_id, artifact_id = (uuid4() for _ in range(5))
    user_id = uuid4()
    case = SimpleNamespace(id=case_id)
    member = SimpleNamespace(id=member_id, case_id=case_id)
    specimen = SimpleNamespace(
        id=specimen_id, case_id=case_id, metadata_json={"vcf_sample_name": "FAM-01"},
    )
    artifact = SimpleNamespace(
        id=artifact_id, case_id=case_id, artifact_type="VCF", sha256="a" * 64,
    )
    analysis = SimpleNamespace(
        id=analysis_id, case_id=case_id,
        configuration={
            "input_artifact_id": str(artifact_id),
            "vcf_sample_name": "FAM-01",
        },
    )
    principal = SimpleNamespace(user_id=user_id)
    return case, member, specimen, analysis, artifact, principal


def _patch_auth(monkeypatch):
    monkeypatch.setattr(pedigree, "require_case_permission", lambda *_args: None)
    monkeypatch.setattr(pedigree, "require_role", lambda *_args: None)
    monkeypatch.setattr(pedigree, "AuditService", _Audit)
    monkeypatch.setattr(pedigree, "create_case_change_candidates", lambda *_args, **_kwargs: [])


def test_sample_binding_create_is_unverified_and_pins_source_digest(monkeypatch):
    _patch_auth(monkeypatch)
    case, member, specimen, analysis, artifact, principal = _context()
    db = _BindingDB(case=case, member=member, specimen=specimen, analysis=analysis, artifact=artifact)

    result = pedigree.create_sample_binding(
        case.id,
        pedigree.SampleBindingInput(
            member_id=member.id, specimen_id=specimen.id, analysis_id=analysis.id,
            artifact_id=artifact.id, sample_name="FAM-01",
            binding_method="LAB_SAMPLE_SHEET", evidence_reference="LIMS-ACCESSION-1",
        ),
        db, principal,
    )

    row = next(value for value in db.added if isinstance(value, PedigreeSampleBinding))
    assert result["binding_status"] == "UNVERIFIED"
    assert row.source_artifact_sha256 == artifact.sha256
    assert row.recorded_by == principal.user_id
    assert db.commits == 1


def test_sample_binding_rejects_cross_case_member(monkeypatch):
    _patch_auth(monkeypatch)
    case, member, specimen, analysis, artifact, principal = _context()
    member.case_id = uuid4()
    db = _BindingDB(case=case, member=member, specimen=specimen, analysis=analysis, artifact=artifact)

    with pytest.raises(HTTPException) as exc:
        pedigree.create_sample_binding(
            case.id,
            pedigree.SampleBindingInput(
                member_id=member.id, specimen_id=specimen.id, analysis_id=analysis.id,
                artifact_id=artifact.id, sample_name="FAM-01", binding_method="LAB_SAMPLE_SHEET",
            ),
            db, principal,
        )
    assert exc.value.status_code == 404
    assert db.added == []


def test_sample_binding_rejects_sample_name_or_source_artifact_mismatch(monkeypatch):
    _patch_auth(monkeypatch)
    case, member, specimen, analysis, artifact, principal = _context()
    analysis.configuration["vcf_sample_name"] = "OTHER"
    db = _BindingDB(case=case, member=member, specimen=specimen, analysis=analysis, artifact=artifact)

    with pytest.raises(HTTPException) as exc:
        pedigree.create_sample_binding(
            case.id,
            pedigree.SampleBindingInput(
                member_id=member.id, specimen_id=specimen.id, analysis_id=analysis.id,
                artifact_id=artifact.id, sample_name="FAM-01", binding_method="LAB_SAMPLE_SHEET",
            ),
            db, principal,
        )
    assert exc.value.status_code == 409


def test_sample_binding_verification_requires_source_hash_and_successful_normalization(monkeypatch):
    _patch_auth(monkeypatch)
    case, member, specimen, analysis, artifact, principal = _context()
    previous = PedigreeSampleBinding(
        id=uuid4(), case_id=case.id, pedigree_member_id=member.id,
        specimen_id=specimen.id, analysis_id=analysis.id, artifact_id=artifact.id,
        source_artifact_sha256="b" * 64, sample_name="FAM-01",
        binding_status="UNVERIFIED", binding_method="LAB_SAMPLE_SHEET",
        evidence_reference="LIMS-ACCESSION-1", version=1,
        binding_fingerprint="c" * 64, recorded_by=principal.user_id,
    )
    db = _BindingDB(
        case=case, member=member, specimen=specimen, analysis=analysis,
        artifact=artifact, previous=previous,
    )
    db.scalar_results = [None]
    with pytest.raises(HTTPException) as exc:
        pedigree.review_sample_binding(
            case.id, previous.id,
            pedigree.SampleBindingReviewInput(decision="VERIFIED", reason="Reviewed LIMS record"),
            db, principal,
        )
    assert exc.value.status_code == 409
    assert "digest" in exc.value.detail
    assert db.added == []


def test_sample_binding_review_appends_verified_revision_only_after_normalization(monkeypatch):
    _patch_auth(monkeypatch)
    case, member, specimen, analysis, artifact, principal = _context()
    previous = PedigreeSampleBinding(
        id=uuid4(), case_id=case.id, pedigree_member_id=member.id,
        specimen_id=specimen.id, analysis_id=analysis.id, artifact_id=artifact.id,
        source_artifact_sha256=artifact.sha256, sample_name="FAM-01",
        binding_status="UNVERIFIED", binding_method="LAB_SAMPLE_SHEET",
        evidence_reference="LIMS-ACCESSION-1", version=1,
        binding_fingerprint="d" * 64, recorded_by=principal.user_id,
    )
    workflow = SimpleNamespace(
        status="SUCCEEDED", input_artifacts=[str(artifact.id)],
    )
    db = _BindingDB(
        case=case, member=member, specimen=specimen, analysis=analysis,
        artifact=artifact, previous=previous, workflow=workflow,
    )
    db.scalar_results = [None]
    db.query_rows = [[
        SimpleNamespace(
            id=uuid4(), evidence_type="CHAIN_OF_CUSTODY", result="PASS",
            method="LIMS_CHAIN_OF_CUSTODY", method_version="1",
            evidence_reference="LIMS-ACCESSION-1", evidence_fingerprint="e" * 64,
            review_status="ACCEPTED", reviewed_by=principal.user_id, reviewed_at=None,
            supersedes_evidence_id=None,
        ),
        SimpleNamespace(
            id=uuid4(), evidence_type="SAMPLE_IDENTITY_QC", result="PASS",
            method="SNP_FINGERPRINT_CONCORDANCE", method_version="2",
            evidence_reference="IDENTITY-QC-REPORT-1", evidence_fingerprint="f" * 64,
            review_status="ACCEPTED", reviewed_by=principal.user_id, reviewed_at=None,
            supersedes_evidence_id=None,
        ),
    ]]
    monkeypatch.setattr(
        pedigree, "get_analysis_sample_calls",
        lambda *_args: {uuid4(): {"sample_name": "FAM-01", "genotype": "./."}},
    )

    result = pedigree.review_sample_binding(
        case.id, previous.id,
        pedigree.SampleBindingReviewInput(decision="VERIFIED", reason="Reviewed LIMS record"),
        db, principal,
    )

    revision = next(value for value in db.added if isinstance(value, PedigreeSampleBinding))
    assert result["binding_status"] == "VERIFIED"
    assert revision.version == 2
    assert revision.supersedes_binding_id == previous.id
    assert revision.source_artifact_sha256 == artifact.sha256
    assert revision.reviewed_by == principal.user_id
    assert revision.review_reason == "Reviewed LIMS record"


def test_sample_binding_migration_is_append_only_and_refuses_data_loss(tmp_path, monkeypatch):
    database = tmp_path / "family-sample-bindings.sqlite"
    url = f"sqlite:///{database}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    engine = create_engine(url)
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("pedigree_sample_bindings")}
        assert {
            "case_id", "pedigree_member_id", "specimen_id", "analysis_id",
            "artifact_id", "source_artifact_sha256", "sample_name",
            "binding_status", "version", "supersedes_binding_id",
        }.issubset(columns)
        connection.execute(text("""
            INSERT INTO pedigree_sample_bindings (
                id, case_id, pedigree_member_id, specimen_id, analysis_id, artifact_id,
                source_artifact_sha256, sample_name, binding_status, binding_method,
                version, binding_fingerprint, recorded_by, created_at
            ) VALUES (
                '10000000-0000-0000-0000-000000000001',
                '20000000-0000-0000-0000-000000000001',
                '30000000-0000-0000-0000-000000000001',
                '40000000-0000-0000-0000-000000000001',
                '50000000-0000-0000-0000-000000000001',
                '60000000-0000-0000-0000-000000000001',
                :digest, 'FAM-01', 'UNVERIFIED', 'LAB_SAMPLE_SHEET',
                1, :fingerprint,
                '70000000-0000-0000-0000-000000000001', CURRENT_TIMESTAMP
            )
        """), {"digest": "a" * 64, "fingerprint": "b" * 64})
        connection.execute(text("""
            INSERT INTO pedigree_sample_bindings (
                id, case_id, pedigree_member_id, specimen_id, analysis_id, artifact_id,
                source_artifact_sha256, sample_name, binding_status, binding_method,
                review_reason, version, supersedes_binding_id, binding_fingerprint,
                recorded_by, reviewed_by, reviewed_at, created_at
            ) VALUES (
                '10000000-0000-0000-0000-000000000002',
                '20000000-0000-0000-0000-000000000001',
                '30000000-0000-0000-0000-000000000001',
                '40000000-0000-0000-0000-000000000001',
                '50000000-0000-0000-0000-000000000001',
                '60000000-0000-0000-0000-000000000001',
                :digest, 'FAM-01', 'VERIFIED', 'LAB_SAMPLE_SHEET',
                'Reviewed', 2, '10000000-0000-0000-0000-000000000001',
                :fingerprint,
                '70000000-0000-0000-0000-000000000001',
                '70000000-0000-0000-0000-000000000001', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """), {"digest": "a" * 64, "fingerprint": "c" * 64})
        with pytest.raises(Exception):
            connection.execute(text("""
                INSERT INTO pedigree_sample_bindings (
                    id, case_id, pedigree_member_id, specimen_id, analysis_id, artifact_id,
                    source_artifact_sha256, sample_name, binding_status, binding_method,
                    review_reason, version, supersedes_binding_id, binding_fingerprint,
                    recorded_by, reviewed_by, reviewed_at, created_at
                ) VALUES (
                    '10000000-0000-0000-0000-000000000003',
                    '20000000-0000-0000-0000-000000000001',
                    '30000000-0000-0000-0000-000000000001',
                    '40000000-0000-0000-0000-000000000001',
                    '50000000-0000-0000-0000-000000000001',
                    '60000000-0000-0000-0000-000000000001',
                    :digest, 'FAM-01', 'VERIFIED', 'LAB_SAMPLE_SHEET',
                    'Conflicting review', 2, '10000000-0000-0000-0000-000000000001',
                    :fingerprint,
                    '70000000-0000-0000-0000-000000000001',
                    '70000000-0000-0000-0000-000000000001', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """), {"digest": "a" * 64, "fingerprint": "d" * 64})
        with pytest.raises(Exception):
            connection.execute(text(
                "UPDATE pedigree_sample_bindings SET binding_status='VERIFIED' "
                "WHERE id='10000000-0000-0000-0000-000000000001'"
            ))
        connection.execute(text("""
            INSERT INTO pedigree_sample_identity_evidence (
                id, case_id, binding_id, evidence_type, result, method, method_version,
                evidence_reference, metrics, review_status, version, evidence_fingerprint,
                recorded_by, created_at
            ) VALUES (
                '80000000-0000-0000-0000-000000000001',
                '20000000-0000-0000-0000-000000000001',
                '10000000-0000-0000-0000-000000000001',
                'CHAIN_OF_CUSTODY', 'PASS', 'LIMS_CHAIN_OF_CUSTODY', '1',
                'LIMS-ACCESSION-1', '{}', 'PENDING', 1, :fingerprint,
                '70000000-0000-0000-0000-000000000001', CURRENT_TIMESTAMP
            )
        """), {"fingerprint": "e" * 64})
        with pytest.raises(Exception):
            connection.execute(text(
                "UPDATE pedigree_sample_identity_evidence SET review_status='ACCEPTED' "
                "WHERE evidence_reference='LIMS-ACCESSION-1'"
            ))
    with pytest.raises(RuntimeError, match="Refusing to downgrade"):
        command.downgrade(config, "0062_phenotype_observation_amendments")
    engine.dispose()






def test_reviewed_sample_binding_correction_appends_new_unverified_successor(monkeypatch):
    _patch_auth(monkeypatch)
    case, member, specimen, analysis, artifact, principal = _context()
    previous = PedigreeSampleBinding(
        id=uuid4(), case_id=case.id, pedigree_member_id=member.id,
        specimen_id=specimen.id, analysis_id=analysis.id, artifact_id=artifact.id,
        source_artifact_sha256="b" * 64, sample_name="OLD-SAMPLE",
        binding_status="VERIFIED", binding_method="LAB_SAMPLE_SHEET",
        evidence_reference="OLD-ACCESSION", version=2,
        binding_fingerprint="a" * 64, recorded_by=principal.user_id,
        reviewed_by=principal.user_id,
    )
    db = _BindingDB(
        case=case, member=member, specimen=specimen, analysis=analysis,
        artifact=artifact, previous=previous,
    )
    db.scalar_results = [None, None]

    result = pedigree.supersede_sample_binding(
        case.id, previous.id,
        pedigree.SampleBindingInput(
            member_id=member.id, specimen_id=specimen.id, analysis_id=analysis.id,
            artifact_id=artifact.id, sample_name="FAM-01",
            binding_method="LAB_SAMPLE_SHEET", evidence_reference="NEW-ACCESSION",
        ),
        db, principal,
    )
    revision = next(item for item in db.added if isinstance(item, PedigreeSampleBinding))
    assert result["binding_status"] == "UNVERIFIED"
    assert revision.version == 3
    assert revision.supersedes_binding_id == previous.id
    assert revision.source_artifact_sha256 == artifact.sha256
    assert db.commits == 1


def test_identity_evidence_is_recorded_pending_with_method_and_provenance(monkeypatch):
    _patch_auth(monkeypatch)
    case, member, specimen, analysis, artifact, principal = _context()
    binding = SimpleNamespace(
        id=uuid4(), case_id=case.id, analysis_id=analysis.id, binding_status="UNVERIFIED",
    )
    db = _BindingDB(
        case=case, member=member, specimen=specimen, analysis=analysis,
        artifact=artifact, previous=binding,
    )
    db.scalar_results = [None, None]

    result = pedigree.create_sample_identity_evidence(
        case.id, binding.id,
        pedigree.SampleIdentityEvidenceInput(
            evidence_type="SAMPLE_IDENTITY_QC", result="PASS",
            method="SNP_FINGERPRINT_CONCORDANCE", method_version="2.1",
            evidence_reference="IDENTITY-QC-REPORT-1",
            metrics={"concordance": 0.9998},
        ),
        db, principal,
    )
    row = next(item for item in db.added if isinstance(item, PedigreeSampleIdentityEvidence))
    assert result["review_status"] == "PENDING"
    assert result["result"] == "PASS"
    assert row.metrics_json == {"concordance": 0.9998}
    assert row.recorded_by == principal.user_id


def test_identity_evidence_review_appends_immutable_acceptance_revision(monkeypatch):
    _patch_auth(monkeypatch)
    case, member, specimen, analysis, artifact, principal = _context()
    binding = SimpleNamespace(id=uuid4(), case_id=case.id, analysis_id=analysis.id)
    previous = SimpleNamespace(
        id=uuid4(), case_id=case.id, binding_id=binding.id,
        evidence_type="CHAIN_OF_CUSTODY", result="PASS",
        method="LIMS_CHAIN_OF_CUSTODY", method_version="1",
        evidence_reference="LIMS-ACCESSION-1", source_artifact_id=None,
        metrics_json={}, review_status="PENDING", review_reason=None, version=1,
        supersedes_evidence_id=None, evidence_fingerprint="a" * 64,
        recorded_by=principal.user_id, reviewed_by=None, reviewed_at=None,
    )
    db = _BindingDB(
        case=case, member=member, specimen=specimen, analysis=analysis,
        artifact=artifact, previous=binding, evidence=previous,
    )
    db.scalar_results = [None]

    result = pedigree.review_sample_identity_evidence(
        case.id, binding.id, previous.id,
        pedigree.SampleIdentityEvidenceReviewInput(
            decision="ACCEPTED", reason="Matched accession and custody log",
        ),
        db, principal,
    )
    revision = next(item for item in db.added if isinstance(item, PedigreeSampleIdentityEvidence))
    assert result["review_status"] == "ACCEPTED"
    assert revision.version == 2
    assert revision.supersedes_evidence_id == previous.id
    assert revision.reviewed_by == principal.user_id


def test_binding_verification_requires_both_accepted_identity_evidence_types(monkeypatch):
    _patch_auth(monkeypatch)
    case, member, specimen, analysis, artifact, principal = _context()
    previous = PedigreeSampleBinding(
        id=uuid4(), case_id=case.id, pedigree_member_id=member.id,
        specimen_id=specimen.id, analysis_id=analysis.id, artifact_id=artifact.id,
        source_artifact_sha256=artifact.sha256, sample_name="FAM-01",
        binding_status="UNVERIFIED", binding_method="LAB_SAMPLE_SHEET",
        evidence_reference="LIMS-ACCESSION-1", version=1,
        binding_fingerprint="e" * 64, recorded_by=principal.user_id,
    )
    workflow = SimpleNamespace(status="SUCCEEDED", input_artifacts=[str(artifact.id)])
    db = _BindingDB(
        case=case, member=member, specimen=specimen, analysis=analysis,
        artifact=artifact, previous=previous, workflow=workflow,
    )
    db.scalar_results = [None]
    db.query_rows = [[]]
    monkeypatch.setattr(
        pedigree, "get_analysis_sample_calls",
        lambda *_args: {uuid4(): {"sample_name": "FAM-01", "genotype": "0/1"}},
    )

    with pytest.raises(HTTPException) as exc:
        pedigree.review_sample_binding(
            case.id, previous.id,
            pedigree.SampleBindingReviewInput(decision="VERIFIED", reason="Review"),
            db, principal,
        )
    assert exc.value.status_code == 409
    assert "CHAIN_OF_CUSTODY" in exc.value.detail
    assert db.added == []


def test_sample_binding_write_requires_case_write_authorization(monkeypatch):
    case, member, specimen, analysis, artifact, principal = _context()
    db = _BindingDB(case=case, member=member, specimen=specimen, analysis=analysis, artifact=artifact)

    def deny(*_args):
        raise HTTPException(403, "write permission required")

    monkeypatch.setattr(pedigree, "require_case_permission", deny)
    with pytest.raises(HTTPException) as exc:
        pedigree.create_sample_binding(
            case.id,
            pedigree.SampleBindingInput(
                member_id=member.id, specimen_id=specimen.id, analysis_id=analysis.id,
                artifact_id=artifact.id, sample_name="FAM-01", binding_method="LAB_SAMPLE_SHEET",
            ),
            db, principal,
        )
    assert exc.value.status_code == 403
    assert db.added == []


def test_sample_binding_create_retry_returns_existing_binding_without_duplicate_audit(monkeypatch):
    _patch_auth(monkeypatch)
    case, member, specimen, analysis, artifact, principal = _context()
    existing = SimpleNamespace(
        id=uuid4(), case_id=case.id, pedigree_member_id=member.id,
        specimen_id=specimen.id, analysis_id=analysis.id, artifact_id=artifact.id,
        source_artifact_sha256=artifact.sha256, sample_name="FAM-01",
        binding_status="UNVERIFIED", binding_method="LAB_SAMPLE_SHEET",
        evidence_reference=None, review_reason=None, version=1,
        supersedes_binding_id=None, recorded_by=principal.user_id,
        reviewed_by=None, reviewed_at=None,
    )
    db = _BindingDB(case=case, member=member, specimen=specimen, analysis=analysis, artifact=artifact)
    db.scalar_results = [existing]

    result = pedigree.create_sample_binding(
        case.id,
        pedigree.SampleBindingInput(
            member_id=member.id, specimen_id=specimen.id, analysis_id=analysis.id,
            artifact_id=artifact.id, sample_name="FAM-01", binding_method="LAB_SAMPLE_SHEET",
        ),
        db, principal,
    )
    assert result["binding_id"] == str(existing.id)
    assert db.added == []
    assert db.commits == 0


def test_sample_binding_review_retry_is_idempotent_and_conflicts_are_rejected(monkeypatch):
    _patch_auth(monkeypatch)
    case, member, specimen, analysis, artifact, principal = _context()
    previous = SimpleNamespace(
        id=uuid4(), case_id=case.id, pedigree_member_id=member.id,
        specimen_id=specimen.id, analysis_id=analysis.id, artifact_id=artifact.id,
        source_artifact_sha256=artifact.sha256, sample_name="FAM-01",
        binding_status="UNVERIFIED", binding_method="LAB_SAMPLE_SHEET",
        evidence_reference=None, review_reason=None, version=1,
        supersedes_binding_id=None, recorded_by=principal.user_id,
        reviewed_by=None, reviewed_at=None,
    )
    revision = SimpleNamespace(
        id=uuid4(), case_id=case.id, pedigree_member_id=member.id,
        specimen_id=specimen.id, analysis_id=analysis.id, artifact_id=artifact.id,
        source_artifact_sha256=artifact.sha256, sample_name="FAM-01",
        binding_status="VERIFIED", binding_method="LAB_SAMPLE_SHEET",
        evidence_reference=None, review_reason="Confirmed against LIMS",
        version=2, supersedes_binding_id=previous.id, recorded_by=principal.user_id,
        reviewed_by=principal.user_id, reviewed_at=None,
    )
    db = _BindingDB(
        case=case, member=member, specimen=specimen, analysis=analysis,
        artifact=artifact, previous=previous,
    )
    db.scalar_results = [revision]
    result = pedigree.review_sample_binding(
        case.id, previous.id,
        pedigree.SampleBindingReviewInput(decision="VERIFIED", reason="Confirmed against LIMS"),
        db, principal,
    )
    assert result["binding_id"] == str(revision.id)
    assert db.added == []

    db = _BindingDB(
        case=case, member=member, specimen=specimen, analysis=analysis,
        artifact=artifact, previous=previous,
    )
    db.scalar_results = [revision]
    with pytest.raises(HTTPException) as exc:
        pedigree.review_sample_binding(
            case.id, previous.id,
            pedigree.SampleBindingReviewInput(decision="REJECTED", reason="Conflicting review"),
            db, principal,
        )
    assert exc.value.status_code == 409


def test_sample_binding_revision_serializes_case_mutation(monkeypatch):
    _patch_auth(monkeypatch)
    case, member, specimen, analysis, artifact, principal = _context()
    db = _BindingDB(case=case, member=member, specimen=specimen, analysis=analysis, artifact=artifact)
    pedigree.create_sample_binding(
        case.id,
        pedigree.SampleBindingInput(
            member_id=member.id, specimen_id=specimen.id, analysis_id=analysis.id,
            artifact_id=artifact.id, sample_name="FAM-01", binding_method="LAB_SAMPLE_SHEET",
        ),
        db, principal,
    )
    assert any(kwargs.get("with_for_update") is True for _args, kwargs in db.refresh_calls)


def test_identity_evidence_history_endpoint_returns_all_immutable_revisions(monkeypatch):
    case_id, binding_id = uuid4(), uuid4()
    case = SimpleNamespace(id=case_id)
    binding = SimpleNamespace(id=binding_id, case_id=case_id)
    rows = [
        SimpleNamespace(
            id=uuid4(), case_id=case_id, binding_id=binding_id,
            evidence_type="CHAIN_OF_CUSTODY", result="PASS", method="LIMS",
            method_version="1", evidence_reference="COC-1", source_artifact_id=None,
            metrics_json={}, review_status="PENDING", review_reason=None, version=1,
            supersedes_evidence_id=None, recorded_by=uuid4(), reviewed_by=None,
            reviewed_at=None,
        ),
        SimpleNamespace(
            id=uuid4(), case_id=case_id, binding_id=binding_id,
            evidence_type="CHAIN_OF_CUSTODY", result="PASS", method="LIMS",
            method_version="1", evidence_reference="COC-1", source_artifact_id=None,
            metrics_json={}, review_status="ACCEPTED", review_reason="Verified", version=2,
            supersedes_evidence_id=uuid4(), recorded_by=uuid4(), reviewed_by=uuid4(),
            reviewed_at=None,
        ),
    ]

    class ReadDB:
        def get(self, model, identifier):
            if model is Case and identifier == case_id:
                return case
            if model is PedigreeSampleBinding and identifier == binding_id:
                return binding
            return None

        def scalars(self, _statement):
            return _Rows(rows)

    monkeypatch.setattr(pedigree, "require_case_permission", lambda *_args: None)
    result = pedigree.list_sample_identity_evidence(
        case_id, binding_id, ReadDB(), SimpleNamespace(user_id=uuid4()),
    )
    assert result["case_id"] == str(case_id)
    assert result["binding_id"] == str(binding_id)
    assert [item["version"] for item in result["evidence"]] == [1, 2]
    assert result["evidence"][1]["review_status"] == "ACCEPTED"
