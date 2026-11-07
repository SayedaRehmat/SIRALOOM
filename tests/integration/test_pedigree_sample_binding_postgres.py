from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import (
    Analysis, Artifact, Case, Organization, PedigreeMember, PedigreeSampleBinding,
    PedigreeSampleIdentityEvidence, Specimen, User,
)


@pytest.mark.integration
def test_postgres_family_sample_binding_is_immutable_and_has_single_successor():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id, user_id, case_id = uuid4(), uuid4(), uuid4()
    specimen_id, member_id, analysis_id, artifact_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    binding_id = uuid4()
    now = datetime.now(timezone.utc)

    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id, name=f"sample-binding-{organization_id}",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@example.test",
                display_name="Sample Binding Integration", role="lab_director",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"SB-{case_id}", status="ACTIVE",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.flush()
            db.add(Specimen(
                id=specimen_id, case_id=case_id, specimen_identifier=f"SP-{specimen_id}",
                specimen_type="BLOOD", metadata_json={},
            ))
            db.flush()
            db.add(PedigreeMember(
                id=member_id, case_id=case_id, member_identifier="PROBAND",
                sex="UNKNOWN", affected_status="AFFECTED", is_proband=True,
                sampled=True, specimen_id=specimen_id, metadata_json={},
            ))
            db.add(Analysis(
                id=analysis_id, case_id=case_id,
                analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1",
                workflow_version="1", status="REQUIRES_REVIEW",
                reference_build="GRCh38",
                configuration={"input_artifact_id": str(artifact_id), "vcf_sample_name": "FAM-01"},
                created_by=user_id,
            ))
            db.flush()
            db.add(Artifact(
                id=artifact_id, analysis_id=None, case_id=case_id,
                artifact_type="VCF", filename="family.vcf", media_type="text/plain",
                size_bytes=100, sha256="a" * 64, storage_uri=f"test://{artifact_id}",
                genome_build="GRCh38", specimen_id=specimen_id,
                validation_status="VALID", metadata_json={},
            ))
            db.flush()
            db.add(PedigreeSampleBinding(
                id=binding_id, case_id=case_id, pedigree_member_id=member_id,
                specimen_id=specimen_id, analysis_id=analysis_id, artifact_id=artifact_id,
                source_artifact_sha256="a" * 64, sample_name="FAM-01",
                binding_status="UNVERIFIED", binding_method="LAB_SAMPLE_SHEET",
                version=1, binding_fingerprint="b" * 64, recorded_by=user_id,
            ))
            db.flush()
            evidence_id = uuid4()
            db.add(PedigreeSampleIdentityEvidence(
                id=evidence_id, case_id=case_id, binding_id=binding_id,
                evidence_type="CHAIN_OF_CUSTODY", result="PASS",
                method="LIMS_CHAIN_OF_CUSTODY", method_version="1",
                evidence_reference="LIMS-ACCESSION-1", source_artifact_id=None,
                metrics_json={}, review_status="PENDING", version=1,
                evidence_fingerprint="e" * 64, recorded_by=user_id,
            ))
            db.flush()

            with pytest.raises(DBAPIError):
                with db.begin_nested():
                    db.execute(
                        update(PedigreeSampleIdentityEvidence)
                        .where(PedigreeSampleIdentityEvidence.id == evidence_id)
                        .values(review_status="ACCEPTED")
                    )

            with pytest.raises(DBAPIError):
                with db.begin_nested():
                    db.execute(
                        update(PedigreeSampleBinding)
                        .where(PedigreeSampleBinding.id == binding_id)
                        .values(binding_status="REJECTED")
                    )

            first_revision = PedigreeSampleBinding(
                id=uuid4(), case_id=case_id, pedigree_member_id=member_id,
                specimen_id=specimen_id, analysis_id=analysis_id, artifact_id=artifact_id,
                source_artifact_sha256="a" * 64, sample_name="FAM-01",
                binding_status="VERIFIED", binding_method="LAB_SAMPLE_SHEET",
                review_reason="Integration test review", version=2,
                supersedes_binding_id=binding_id, binding_fingerprint="c" * 64,
                recorded_by=user_id, reviewed_by=user_id, reviewed_at=now,
            )
            competing_revision = PedigreeSampleBinding(
                id=uuid4(), case_id=case_id, pedigree_member_id=member_id,
                specimen_id=specimen_id, analysis_id=analysis_id, artifact_id=artifact_id,
                source_artifact_sha256="a" * 64, sample_name="FAM-01",
                binding_status="REJECTED", binding_method="LAB_SAMPLE_SHEET",
                review_reason="Conflicting integration test review", version=2,
                supersedes_binding_id=binding_id, binding_fingerprint="d" * 64,
                recorded_by=user_id, reviewed_by=user_id, reviewed_at=now,
            )
            with pytest.raises(IntegrityError):
                with db.begin_nested():
                    db.add_all([first_revision, competing_revision])
                    db.flush()
            db.rollback()
    finally:
        engine.dispose()


@pytest.mark.integration
def test_postgres_binding_and_identity_evidence_successor_races_have_one_winner():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id, user_id, case_id = uuid4(), uuid4(), uuid4()
    specimen_id, member_id, analysis_id, artifact_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    binding_id, evidence_id = uuid4(), uuid4()
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id, name=f"successor-race-{organization_id}",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@example.test",
                display_name="Successor Race Integration", role="lab_director",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"SR-{case_id}", status="ACTIVE",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.flush()
            db.add(Specimen(
                id=specimen_id, case_id=case_id,
                specimen_identifier=f"SP-{specimen_id}", specimen_type="BLOOD",
                metadata_json={},
            ))
            db.flush()
            db.add(PedigreeMember(
                id=member_id, case_id=case_id, member_identifier="PROBAND",
                sex="UNKNOWN", affected_status="AFFECTED", is_proband=True,
                sampled=True, specimen_id=specimen_id, metadata_json={},
            ))
            db.add(Analysis(
                id=analysis_id, case_id=case_id,
                analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1",
                workflow_version="1", status="REQUIRES_REVIEW",
                reference_build="GRCh38",
                configuration={"input_artifact_id": str(artifact_id), "vcf_sample_name": "FAM-01"},
                created_by=user_id,
            ))
            db.flush()
            db.add(Artifact(
                id=artifact_id, analysis_id=None, case_id=case_id,
                artifact_type="VCF", filename="family.vcf", media_type="text/plain",
                size_bytes=100, sha256="a" * 64, storage_uri=f"test://{artifact_id}",
                genome_build="GRCh38", specimen_id=specimen_id,
                validation_status="VALID", metadata_json={},
            ))
            db.add(PedigreeSampleBinding(
                id=binding_id, case_id=case_id, pedigree_member_id=member_id,
                specimen_id=specimen_id, analysis_id=analysis_id, artifact_id=artifact_id,
                source_artifact_sha256="a" * 64, sample_name="FAM-01",
                binding_status="UNVERIFIED", binding_method="LAB_SAMPLE_SHEET",
                version=1, binding_fingerprint="b" * 64, recorded_by=user_id,
            ))
            db.add(PedigreeSampleIdentityEvidence(
                id=evidence_id, case_id=case_id, binding_id=binding_id,
                evidence_type="CHAIN_OF_CUSTODY", result="PASS",
                method="LIMS_CHAIN_OF_CUSTODY", method_version="1",
                evidence_reference="LIMS-ACCESSION-1", metrics_json={},
                review_status="PENDING", version=1, evidence_fingerprint="e" * 64,
                recorded_by=user_id,
            ))
            db.commit()

        def race_binding(status: str, fingerprint: str, barrier: Barrier):
            with Session(engine) as db:
                db.add(PedigreeSampleBinding(
                    id=uuid4(), case_id=case_id, pedigree_member_id=member_id,
                    specimen_id=specimen_id, analysis_id=analysis_id, artifact_id=artifact_id,
                    source_artifact_sha256="a" * 64, sample_name="FAM-01",
                    binding_status="UNVERIFIED", binding_method="LAB_SAMPLE_SHEET",
                    version=2, supersedes_binding_id=binding_id,
                    binding_fingerprint=fingerprint, recorded_by=user_id,
                ))
                barrier.wait(timeout=20)
                try:
                    db.commit()
                    return "COMMITTED"
                except IntegrityError:
                    db.rollback()
                    return "CONFLICT"

        binding_barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            binding_results = list(pool.map(
                lambda args: race_binding(*args),
                [
                    ("UNVERIFIED", "c" * 64, binding_barrier),
                    ("UNVERIFIED", "d" * 64, binding_barrier),
                ],
            ))
        assert sorted(binding_results) == ["COMMITTED", "CONFLICT"]

        def race_evidence(fingerprint: str, barrier: Barrier):
            with Session(engine) as db:
                db.add(PedigreeSampleIdentityEvidence(
                    id=uuid4(), case_id=case_id, binding_id=binding_id,
                    evidence_type="CHAIN_OF_CUSTODY", result="PASS",
                    method="LIMS_CHAIN_OF_CUSTODY", method_version="1",
                    evidence_reference="LIMS-ACCESSION-1", metrics_json={},
                    review_status="PENDING", version=2, supersedes_evidence_id=evidence_id,
                    evidence_fingerprint=fingerprint, recorded_by=user_id,
                ))
                barrier.wait(timeout=20)
                try:
                    db.commit()
                    return "COMMITTED"
                except IntegrityError:
                    db.rollback()
                    return "CONFLICT"

        evidence_barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            evidence_results = list(pool.map(
                lambda fingerprint: race_evidence(fingerprint, evidence_barrier),
                ["f" * 64, "9" * 64],
            ))
        assert sorted(evidence_results) == ["COMMITTED", "CONFLICT"]
    finally:
        # These records are intentionally append-only. The PostgreSQL integration
        # workflow provisions a disposable database for this test run; deleting
        # immutable identity evidence/bindings would invalidate the contract under test.
        engine.dispose()
