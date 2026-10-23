from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.reproducibility import (
    ReanalysisComparisonError,
    compare_reanalysis_outputs,
)
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AnalysisResourceSnapshot,
    Case,
    Classification,
    Organization,
    User,
    Variant,
)


def _seed_analysis(db, *, organization_id, user_id, case_id, analysis_id, parent_id, version):
    db.add(Analysis(
        id=analysis_id,
        case_id=case_id,
        parent_analysis_id=parent_id,
        assay_id=None,
        analysis_type="VARIANT_INTERPRETATION",
        workflow_id="variant-v1",
        workflow_version=f"workflow-{version}",
        status="SUCCEEDED",
        queue_task_id=None,
        reference_build="GRCh38",
        configuration={},
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        created_by=user_id,
        analysis_version=version,
    ))
    db.flush()
    db.add(AnalysisResourceSnapshot(
        id=uuid4(),
        analysis_id=analysis_id,
        resource_id=None,
        resource_kind="ACMG_RULE",
        resource_name="ACMG/AMP",
        provider="ClinGen",
        version="2015.1",
        checksum="a" * 64,
        genome_build="GRCh38",
        metadata_json={"ruleset": "pinned-fixture"},
    ))
    db.flush()


def test_reanalysis_manifest_matches_across_different_row_ids_and_workflow_versions(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'reproducibility-match.db'}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, parent_id, child_id, variant_id = (
        uuid4() for _ in range(6)
    )
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name="Reproducibility Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="Reproducibility Test",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"REPRO-{case_id}",
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.add(Variant(
                id=variant_id,
                genome_build="GRCh38",
                chromosome="1",
                position=12345,
                reference="A",
                alternate="G",
                normalization_status="NORMALIZED",
                canonical_key="GRCh38:1:12345:A:G",
                identifiers={},
            ))
            db.flush()
            _seed_analysis(
                db, organization_id=organization_id, user_id=user_id,
                case_id=case_id, analysis_id=parent_id, parent_id=None, version=1,
            )
            _seed_analysis(
                db, organization_id=organization_id, user_id=user_id,
                case_id=case_id, analysis_id=child_id, parent_id=parent_id, version=2,
            )
            for analysis_id in (parent_id, child_id):
                db.add(Classification(
                    id=uuid4(),
                    variant_id=variant_id,
                    analysis_id=analysis_id,
                    framework_name="ACMG/AMP",
                    framework_version="2015",
                    specification_provider="ClinGen",
                    specification_id="fixture-spec",
                    specification_version="1.0",
                    result="LIKELY_PATHOGENIC",
                    criterion_ids=["PM2", "PP3"],
                    metadata_json={"evidence_model": "fixture-v1"},
                    state="PROPOSED",
                    review_status="PENDING",
                    version=1,
                    review_version=0,
                ))
            db.commit()

            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["resource_snapshots_match"] is True
            assert result["scientific_outputs_match"] is True
            assert result["reproducible"] is True
            assert result["decision"] == "MATCH"
            assert result["parent"]["workflow_version"] != result["child"]["workflow_version"]
    finally:
        engine.dispose()


def test_reanalysis_manifest_flags_scientific_output_drift(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'reproducibility-drift.db'}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, parent_id, child_id, variant_id = (
        uuid4() for _ in range(6)
    )
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name="Output Drift Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="Output Drift Test",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"DRIFT-{case_id}",
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.add(Variant(
                id=variant_id,
                genome_build="GRCh38",
                chromosome="1",
                position=67890,
                reference="C",
                alternate="T",
                normalization_status="NORMALIZED",
                canonical_key="GRCh38:1:67890:C:T",
                identifiers={},
            ))
            db.flush()
            _seed_analysis(
                db, organization_id=organization_id, user_id=user_id,
                case_id=case_id, analysis_id=parent_id, parent_id=None, version=1,
            )
            _seed_analysis(
                db, organization_id=organization_id, user_id=user_id,
                case_id=case_id, analysis_id=child_id, parent_id=parent_id, version=2,
            )
            parent_classification = Classification(
                id=uuid4(), variant_id=variant_id, analysis_id=parent_id,
                framework_name="ACMG/AMP", framework_version="2015",
                specification_provider="ClinGen", specification_id="fixture-spec",
                specification_version="1.0", result="LIKELY_PATHOGENIC",
                criterion_ids=["PM2"], metadata_json={}, state="PROPOSED",
                review_status="PENDING", version=1, review_version=0,
            )
            child_classification = Classification(
                id=uuid4(), variant_id=variant_id, analysis_id=child_id,
                framework_name="ACMG/AMP", framework_version="2015",
                specification_provider="ClinGen", specification_id="fixture-spec",
                specification_version="1.0", result="UNCERTAIN_SIGNIFICANCE",
                criterion_ids=["PM2"], metadata_json={}, state="PROPOSED",
                review_status="PENDING", version=1, review_version=0,
            )
            db.add_all([parent_classification, child_classification])
            db.commit()

            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["resource_snapshots_match"] is True
            assert result["scientific_outputs_match"] is False
            assert result["reproducible"] is False
            assert result["decision"] == "MISMATCH"
    finally:
        engine.dispose()


def test_reanalysis_manifest_is_ineligible_without_checksums(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'reproducibility-unpinned.db'}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, parent_id, child_id = (
        uuid4() for _ in range(5)
    )
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name="Unpinned Resource Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="Unpinned Test",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"UNPINNED-{case_id}",
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.flush()
            db.add(Analysis(
                id=parent_id,
                case_id=case_id,
                parent_analysis_id=None,
                assay_id=None,
                analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1",
                workflow_version="1",
                status="SUCCEEDED",
                queue_task_id=None,
                reference_build="GRCh38",
                configuration={},
                started_at=None,
                completed_at=datetime.now(UTC),
                created_by=user_id,
                analysis_version=1,
            ))
            db.flush()
            db.add(Analysis(
                id=child_id,
                case_id=case_id,
                parent_analysis_id=parent_id,
                assay_id=None,
                analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1",
                workflow_version="2",
                status="SUCCEEDED",
                queue_task_id=None,
                reference_build="GRCh38",
                configuration={},
                started_at=None,
                completed_at=datetime.now(UTC),
                created_by=user_id,
                analysis_version=2,
            ))
            db.add(AnalysisResourceSnapshot(
                id=uuid4(),
                analysis_id=parent_id,
                resource_id=None,
                resource_kind="ANNOTATION",
                resource_name="Example provider",
                provider="Example provider",
                version="1.0",
                checksum=None,
                genome_build="GRCh38",
                metadata_json={},
            ))
            db.add(AnalysisResourceSnapshot(
                id=uuid4(),
                analysis_id=child_id,
                resource_id=None,
                resource_kind="ANNOTATION",
                resource_name="Example provider",
                provider="Example provider",
                version="1.0",
                checksum=None,
                genome_build="GRCh38",
                metadata_json={},
            ))
            db.commit()

            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["reproducible"] is False
            assert result["decision"] == "INELIGIBLE_UNPINNED_RESOURCES"
            assert result["parent"]["unpinned_resources"] == ["ANNOTATION:Example provider"]
    finally:
        engine.dispose()


@pytest.mark.parametrize("invalid_relation", ["not_direct_parent", "different_case"])
def test_reanalysis_comparison_rejects_unrelated_analysis_pairs(
    tmp_path, invalid_relation
):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / f'reproducibility-{invalid_relation}.db'}"
    )
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, other_case_id, parent_id, child_id = (
        uuid4() for _ in range(6)
    )
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name="Comparison Relationship Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="Comparison Relationship Test",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            for row_case_id in (case_id, other_case_id):
                db.add(Case(
                    id=row_case_id,
                    organization_id=organization_id,
                    case_identifier=f"RELATION-{row_case_id}",
                    status="OPEN",
                    clinical_context={},
                    language="en",
                    created_by=user_id,
                ))
            db.flush()
            db.add_all([
                Analysis(
                    id=parent_id,
                    case_id=case_id,
                    parent_analysis_id=None,
                    assay_id=None,
                    analysis_type="VARIANT_INTERPRETATION",
                    workflow_id="variant-v1",
                    workflow_version="1",
                    status="SUCCEEDED",
                    queue_task_id=None,
                    reference_build="GRCh38",
                    configuration={},
                    started_at=None,
                    completed_at=datetime.now(UTC),
                    created_by=user_id,
                    analysis_version=1,
                ),
                Analysis(
                    id=child_id,
                    case_id=(other_case_id if invalid_relation == "different_case" else case_id),
                    parent_analysis_id=(None if invalid_relation == "not_direct_parent" else parent_id),
                    assay_id=None,
                    analysis_type="VARIANT_INTERPRETATION",
                    workflow_id="variant-v1",
                    workflow_version="2",
                    status="SUCCEEDED",
                    queue_task_id=None,
                    reference_build="GRCh38",
                    configuration={},
                    started_at=None,
                    completed_at=datetime.now(UTC),
                    created_by=user_id,
                    analysis_version=2,
                ),
            ])
            db.commit()

            with pytest.raises(ReanalysisComparisonError):
                compare_reanalysis_outputs(
                    db,
                    parent_analysis_id=parent_id,
                    child_analysis_id=child_id,
                )
    finally:
        engine.dispose()
