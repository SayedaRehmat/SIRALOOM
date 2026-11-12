from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import backend.app.domain.artifact_validation as validation
from backend.app.domain.enums import ArtifactType
from backend.app.domain.ingestion import ValidationResult
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Artifact, AuditEvent, Case, Organization, Specimen, User


@pytest.fixture
def validation_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'artifact-validation.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    organization_id, case_id, user_id, specimen_id = uuid4(), uuid4(), uuid4(), uuid4()
    with factory() as db:
        organization = Organization(
            id=organization_id,
            name="Validation Lab",
            external_identifier=str(organization_id),
        )
        user = User(
            id=user_id,
            organization_id=organization_id,
            external_subject=str(user_id),
            email=f"{user_id}@test.local",
            display_name="Validation Worker Test",
            role="organization_admin",
            status="ACTIVE",
        )
        case = Case(
            id=case_id,
            organization_id=organization_id,
            case_identifier=f"VALIDATION-{case_id}",
            status="VALIDATING",
            clinical_context={},
            language="en",
            created_by=user_id,
        )
        specimen = Specimen(
            id=specimen_id,
            case_id=case_id,
            specimen_identifier=f"SPECIMEN-{specimen_id}",
            specimen_type="BLOOD",
            metadata_json={"vcf_sample_name": "SAMPLE1"},
        )
        db.add_all([organization, user, case, specimen])
        db.commit()

    storage_root = tmp_path / "artifacts"
    store = ArtifactStore(storage_root)
    source = tmp_path / "sample.vcf"
    source.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t10\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    with factory() as db:
        artifact = store.put_file(
            db=db,
            case_id=case_id,
            analysis_id=None,
            source_path=source,
            filename="sample.vcf",
            artifact_type=ArtifactType.VCF,
            media_type="text/vcf",
            genome_build="GRCh38",
            metadata={"ingestion": {"file_kind": "VCF"}},
            validation_status="PENDING",
        )
        artifact.specimen_id = specimen_id
        artifact_id = artifact.id
        db.commit()

    monkeypatch.setattr(validation, "SessionLocal", factory)
    monkeypatch.setattr(validation, "artifact_store_for_uri", lambda *args, **kwargs: store)
    monkeypatch.setattr(validation.settings, "worker_scratch_root", str(tmp_path / "scratch"))
    yield {"factory": factory, "artifact_id": artifact_id, "case_id": case_id}
    engine.dispose()


def test_worker_validates_persisted_vcf_and_records_site_only_eligibility(
    validation_runtime, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        validation,
        "validate_vcf",
        lambda path: (
            calls.append(Path(path).read_bytes())
            or ValidationResult(
                status="VALID",
                file_kind="VCF",
                record_count=1,
                sample_names=[],
                detected_build=None,
                errors=[],
                warnings=[],
                fileformat="VCFv4.2",
                metadata={"bcftools_version": "1.25", "htslib_version": "1.25"},
            )
        ),
    )

    first = validation.validate_persisted_artifact(validation_runtime["artifact_id"])
    second = validation.validate_persisted_artifact(validation_runtime["artifact_id"])

    assert first["status"] == "VALID_SITE_ONLY"
    assert second["idempotent"] is True
    assert len(calls) == 1

    with validation_runtime["factory"]() as db:
        artifact = db.get(Artifact, validation_runtime["artifact_id"])
        case = db.get(Case, validation_runtime["case_id"])
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.case_id == validation_runtime["case_id"],
                AuditEvent.event_type == "ARTIFACT_VALIDATION_COMPLETED",
            )
        )
        assert artifact.validation_status == "VALID_SITE_ONLY"
        assert artifact.metadata_json["workflow_eligibility"] == "SITE_LEVEL_ONLY"
        assert case.status == "ARTIFACT_UPLOADED"
        assert audit is not None


def test_worker_tool_unavailability_does_not_classify_vcf_as_invalid(
    validation_runtime, monkeypatch
):
    from backend.app.domain.ingestion import VCFValidationUnavailable

    def unavailable(_path):
        raise VCFValidationUnavailable("temporary BCFtools outage")

    monkeypatch.setattr(validation, "validate_vcf", unavailable)

    with pytest.raises(VCFValidationUnavailable, match="temporary BCFtools outage"):
        validation.validate_persisted_artifact(validation_runtime["artifact_id"])

    with validation_runtime["factory"]() as db:
        artifact = db.get(Artifact, validation_runtime["artifact_id"])
        assert artifact.validation_status == "PENDING"
        assert artifact.metadata_json["ingestion"]["file_kind"] == "VCF"
        assert db.scalar(
            select(AuditEvent).where(
                AuditEvent.case_id == validation_runtime["case_id"],
                AuditEvent.event_type.in_(
                    ("ARTIFACT_VALIDATION_COMPLETED", "ARTIFACT_VALIDATION_FAILED")
                ),
            )
        ) is None

def test_worker_persists_caller_review_gate_without_marking_structural_vcf_invalid(
    validation_runtime, monkeypatch
):
    caller_provenance = {
        "caller_profile_id": "deepvariant_germline",
        "caller_semantic_compatibility_status": "MISSING_REQUIRED_FORMAT_FIELD",
        "caller_semantic_compatibility_review_required": True,
        "required_format_field_violations": [{
            "field_id": "GT",
            "reason": "MISSING_FROM_SAMPLE_RECORD_FORMAT",
            "record_count": 1,
        }],
        "field_declaration_mismatches": [],
        "field_semantic_deviations": [],
    }
    monkeypatch.setattr(
        validation,
        "validate_vcf",
        lambda _path: ValidationResult(
            status="VALID",
            file_kind="VCF",
            record_count=1,
            sample_names=["SAMPLE1"],
            detected_build=None,
            errors=[],
            warnings=[
                "Caller semantic compatibility requires review before genotype-based clinical analysis "
                "(status=MISSING_REQUIRED_FORMAT_FIELD)."
            ],
            fileformat="VCFv4.3",
            metadata={"caller_provenance": caller_provenance},
        ),
    )

    result = validation.validate_persisted_artifact(validation_runtime["artifact_id"])

    assert result["status"] == "VALID"
    with validation_runtime["factory"]() as db:
        artifact = db.get(Artifact, validation_runtime["artifact_id"])
        case = db.get(Case, validation_runtime["case_id"])
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.case_id == validation_runtime["case_id"],
                AuditEvent.event_type == "ARTIFACT_VALIDATION_COMPLETED",
            )
        )
        assert artifact.validation_status == "VALID"
        assert artifact.metadata_json["validation"]["caller_provenance"] == caller_provenance
        assert artifact.metadata_json["workflow_eligibility"] == "REVIEW_REQUIRED"
        assert artifact.metadata_json["workflow_eligibility_reason"]["code"] == (
            "CALLER_SEMANTIC_COMPATIBILITY_REVIEW_REQUIRED"
        )
        assert artifact.metadata_json["workflow_eligibility_reason"]["compatibility_status"] == (
            "MISSING_REQUIRED_FORMAT_FIELD"
        )
        assert case.status == "ARTIFACT_UPLOADED"
        assert audit is not None
        assert audit.payload["validation"]["caller_provenance"] == caller_provenance

