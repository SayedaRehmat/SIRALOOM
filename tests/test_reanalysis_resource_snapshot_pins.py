from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker, create_engine

from backend.app.domain.reanalysis import snapshot_analysis_resources
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    Analysis,
    AnalysisResourceSnapshot,
    Annotation,
    Case,
    Evidence,
    Organization,
    Resource,
    User,
    Variant,
)


def test_resource_snapshots_retain_registered_checksums_for_annotation_evidence_and_acmg(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'resource-snapshot-pins.db'}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, analysis_id, variant_id = (
        uuid4() for _ in range(5)
    )
    resource_ids = [uuid4(), uuid4(), uuid4()]
    resource_specs = [
        ("VEP cache", "VEP", "ANNOTATION", "115", "a" * 64),
        ("ClinVar release", "ClinVar", "EVIDENCE", "2026-10", "b" * 64),
        ("fixture-spec", "ClinGen", "ACMG_RULE", "1.0", "c" * 64),
    ]
    now = datetime.now(timezone.utc)
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name="Snapshot Pin Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="Snapshot Pin Test",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"SNAPSHOT-PIN-{case_id}",
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.flush()
            db.add(Variant(
                id=variant_id,
                genome_build="GRCh38",
                chromosome="1",
                position=123,
                reference="A",
                alternate="C",
                normalization_status="NORMALIZED",
                canonical_key="GRCh38:1:123:A:C",
                identifiers={},
            ))
            db.flush()
            db.add(Analysis(
                id=analysis_id,
                case_id=case_id,
                parent_analysis_id=None,
                assay_id=None,
                analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1",
                workflow_version="snapshot-test",
                status="SUCCEEDED",
                queue_task_id=None,
                reference_build="GRCh38",
                configuration={},
                started_at=now,
                completed_at=now,
                created_by=user_id,
                analysis_version=1,
            ))
            db.flush()
            resources = []
            for resource_id, (name, provider, resource_type, version, checksum) in zip(resource_ids, resource_specs):
                resource = Resource(
                    id=resource_id,
                    organization_id=organization_id,
                    name=name,
                    provider=provider,
                    resource_type=resource_type,
                    version=version,
                    genome_build="GRCh38",
                    access_method="LOCAL",
                    license_text=None,
                    checksum=checksum,
                    location=f"/resources/{name}",
                    status="ACTIVE",
                    population_definition=None,
                    metadata_json={},
                )
                db.add(resource)
                resources.append(resource)
            db.flush()

            db.add(Annotation(
                id=uuid4(),
                variant_id=variant_id,
                analysis_id=analysis_id,
                provider_name="VEP",
                provider_version="115",
                resource_id=resource_ids[0],
                resource_name="VEP cache",
                resource_version="115",
                request_fingerprint="annotation-request",
                response_sha256="annotation-response",
                request_metadata={"assembly": "GRCh38"},
                observed_at=now,
                retry_count=0,
                payload={"consequence": "missense_variant"},
            ))
            db.add(Evidence(
                id=uuid4(),
                variant_id=variant_id,
                analysis_id=analysis_id,
                evidence_type="CLINVAR",
                statement="Registered ClinVar assertion",
                direction="PATHOGENIC",
                source_name="ClinVar release",
                source_version="2026-10",
                resource_id=resource_ids[1],
                source_record_id="VCV000000001",
                request_fingerprint="evidence-request",
                response_sha256="evidence-response",
                request_metadata={"release": "2026-10"},
                observed_at=now,
                observation_ids=[],
                payload={"significance": "Pathogenic"},
                created_by_type="SYSTEM",
                created_by_id="evidence-engine",
                evidence_fingerprint="evidence-fingerprint",
            ))
            db.add(ACMGAssessment(
                id=uuid4(),
                variant_id=variant_id,
                analysis_id=analysis_id,
                framework_name="ACMG/AMP",
                framework_version="2015",
                specification_provider="ClinGen",
                specification_id="fixture-spec",
                specification_version="1.0",
                criterion="PM2",
                automated_assessment={"status": "PROPOSED"},
                reviewed_assessment=None,
                final_assessment=None,
                state="DRAFT",
                review_version=0,
            ))
            db.commit()

            count = snapshot_analysis_resources(db, db.get(Analysis, analysis_id))
            snapshots = db.scalars(select(AnalysisResourceSnapshot).where(
                AnalysisResourceSnapshot.analysis_id == analysis_id
            )).all()

            assert count == 3
            assert {row.resource_kind for row in snapshots} == {
                "ANNOTATION", "EVIDENCE", "ACMG_RULE"
            }
            for snapshot, resource in zip(
                sorted(snapshots, key=lambda row: row.resource_kind),
                sorted(resources, key=lambda row: row.resource_type),
            ):
                assert snapshot.resource_id == resource.id
                assert snapshot.checksum == resource.checksum
                assert snapshot.version == resource.version
    finally:
        engine.dispose()
