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
    Analysis, Artifact, Case, PedigreeMember, PedigreeSampleBinding, Specimen, WorkflowStep,
)


class _Audit:
    def __init__(self, _db):
        pass

    def record(self, **_kwargs):
        pass


class _BindingDB:
    def __init__(self, *, case, member, specimen, analysis, artifact, previous=None, workflow=None):
        self.objects = {
            Case: case,
            PedigreeMember: member,
            Specimen: specimen,
            Analysis: analysis,
            Artifact: artifact,
            PedigreeSampleBinding: previous,
        }
        self.workflow = workflow
        self.scalar_results = []
        self.added = []
        self.commits = 0

    def get(self, model, _identifier, **_kwargs):
        return self.objects.get(model)

    def refresh(self, *_args, **_kwargs):
        return None

    def scalar(self, _statement):
        if self.scalar_results:
            return self.scalar_results.pop(0)
        if self.workflow is not None:
            result, self.workflow = self.workflow, None
            return result
        return None

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
        with pytest.raises(Exception):
            connection.execute(text(
                "UPDATE pedigree_sample_bindings SET binding_status='VERIFIED' "
                "WHERE sample_name='FAM-01'"
            ))
    with pytest.raises(RuntimeError, match="Refusing to downgrade"):
        command.downgrade(config, "0062_phenotype_observation_amendments")
    engine.dispose()
