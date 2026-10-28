from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain.clinical_input_snapshot import (
    build_case_clinical_input_snapshot,
    capture_or_reuse_case_clinical_input_snapshot,
    clinical_input_snapshot_digest,
    inherit_reused_case_clinical_input_snapshot,
    validate_case_clinical_input_snapshot,
)
from backend.app.domain.reproducibility import (
    ReanalysisComparisonError,
    build_reproducibility_manifest,
    compare_reanalysis_outputs,
)
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AnalysisPartition,
    AnalysisResourceSnapshot,
    Artifact,
    Case,
    Classification,
    ConfirmationRecord,
    InheritanceAssessment,
    Organization,
    PedigreeMember,
    PedigreeRelationship,
    PhenotypeObservation,
    QCAssessment,
    ReportabilityDecision,
    ReviewAction,
    SecondaryFindingDecision,
    SegregationObservation,
    TechnicalQCObservation,
    ToolRun,
    User,
    Variant,
    WorkflowDecisionRecord,
    WorkflowStep,
)


def _seed_analysis(db, *, organization_id, user_id, case_id, analysis_id, parent_id, version):
    source_artifact_id = uuid4()
    db.add(Artifact(
        id=source_artifact_id, analysis_id=None, case_id=case_id,
        artifact_type="SOURCE_VCF", filename="source.vcf", media_type="text/vcf",
        size_bytes=12, sha256="b" * 64, storage_uri="file:///fixture/source.vcf",
        genome_build="GRCh38", specimen_id=None, paired_artifact_id=None,
        validation_status="VALIDATED", metadata_json={},
    ))
    db.flush()
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
        configuration={"input_artifact_id": str(source_artifact_id)},
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


def _persist_clinical_input_snapshot(db, analysis_id):
    analysis = db.get(Analysis, analysis_id)
    snapshot = build_case_clinical_input_snapshot(db, analysis)
    db.add(WorkflowStep(
        id=uuid4(), analysis_id=analysis_id, step_id="build_evidence",
        step_order=5, status="SUCCEEDED", attempt=1,
        input_artifacts=[], output_artifacts=[], error_code=None,
        error_message=None,
        metadata_json={
            "clinical_input_snapshot": snapshot,
            "clinical_input_snapshot_sha256": clinical_input_snapshot_digest(snapshot),
        },
    ))
    db.flush()


def test_reproducibility_manifest_includes_case_level_phenotype_inputs(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'case-phenotype-manifest.db'}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, analysis_id = (uuid4() for _ in range(4))
    try:
        with Session(engine) as db:
            db.add(Organization(id=organization_id, name="Manifest Lab"))
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="Manifest Test", role="ADMIN", status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"MANIFEST-{case_id}", status="OPEN",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.flush()
            _seed_analysis(
                db, organization_id=organization_id, user_id=user_id,
                case_id=case_id, analysis_id=analysis_id, parent_id=None, version=1,
            )
            evidence_step = WorkflowStep(
                id=uuid4(), analysis_id=analysis_id, step_id="build_evidence",
                step_order=5, status="SUCCEEDED", attempt=1,
                input_artifacts=[], output_artifacts=[], error_code=None,
                error_message=None, metadata_json={},
            )
            analysis = db.get(Analysis, analysis_id)
            db.add(evidence_step)
            db.commit()

            captured = capture_or_reuse_case_clinical_input_snapshot(
                db, analysis, evidence_step
            )
            assert captured["phenotype_observations"] == []
            before = build_reproducibility_manifest(db, analysis_id)
            db.add(PhenotypeObservation(
                id=uuid4(), case_id=case_id, analysis_id=None,
                hpo_id="HP:0001250", label="Seizure", present=True,
                phenotype_status="PRESENT", onset="CHILDHOOD",
                severity="MODERATE", source="CLINICAL_INPUT",
                evidence={"recorded_by": "reviewed-fixture"},
            ))
            db.flush()
            reused = capture_or_reuse_case_clinical_input_snapshot(
                db, analysis, evidence_step
            )
            after = build_reproducibility_manifest(db, analysis_id)

            assert reused == captured
            assert before["scientific_output_sha256"] == after["scientific_output_sha256"]
            assert before["reproducibility_eligible"] is True
            assert after["reproducibility_eligible"] is True
    finally:
        engine.dispose()


def test_reused_evidence_stage_inherits_verified_parent_clinical_inputs():
    snapshot = {
        "schema_version": 1,
        "phenotype_observations": [{
            "scope": "CASE", "hpo_id": "HP:0001250", "label": "Seizure",
            "present": True, "phenotype_status": "PRESENT", "onset": None,
            "severity": None, "source": "CLINICAL_INPUT", "evidence": {},
        }],
        "gene_disease_evidence": [],
        "literature_evidence": [],
    }
    parent = WorkflowStep(
        id=uuid4(), analysis_id=uuid4(), step_id="build_evidence", step_order=5,
        status="SUCCEEDED", attempt=1, input_artifacts=[], output_artifacts=[],
        metadata_json={
            "clinical_input_snapshot": snapshot,
            "clinical_input_snapshot_sha256": clinical_input_snapshot_digest(snapshot),
        },
    )
    child = WorkflowStep(
        id=uuid4(), analysis_id=uuid4(), step_id="build_evidence", step_order=5,
        status="SUCCEEDED", attempt=1, input_artifacts=[], output_artifacts=[],
        metadata_json={"reanalysis_reuse": True},
    )

    inherited = inherit_reused_case_clinical_input_snapshot(parent, child)

    assert inherited == validate_case_clinical_input_snapshot(snapshot)
    assert child.metadata_json["clinical_input_snapshot"] == snapshot
    assert child.metadata_json["clinical_input_snapshot_sha256"] == clinical_input_snapshot_digest(snapshot)


def test_reused_evidence_stage_rejects_modified_parent_snapshot():
    snapshot = {
        "schema_version": 1, "phenotype_observations": [],
        "gene_disease_evidence": [], "literature_evidence": [],
    }
    parent = WorkflowStep(
        id=uuid4(), analysis_id=uuid4(), step_id="build_evidence", step_order=5,
        status="SUCCEEDED", attempt=1, input_artifacts=[], output_artifacts=[],
        metadata_json={"clinical_input_snapshot": snapshot, "clinical_input_snapshot_sha256": "0" * 64},
    )
    child = WorkflowStep(
        id=uuid4(), analysis_id=uuid4(), step_id="build_evidence", step_order=5,
        status="SUCCEEDED", attempt=1, input_artifacts=[], output_artifacts=[], metadata_json={},
    )

    with pytest.raises(ValueError, match="Parent clinical input snapshot checksum"):
        inherit_reused_case_clinical_input_snapshot(parent, child)


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
            member_id = uuid4()
            father_id = uuid4()
            db.add(PedigreeMember(
                id=member_id, case_id=case_id, member_identifier="proband",
                relationship_to_proband="PROBAND", sex="UNKNOWN",
                affected_status="AFFECTED", is_proband=True, sampled=True,
                specimen_id=None, metadata_json={},
            ))
            db.add(PedigreeMember(
                id=father_id, case_id=case_id, member_identifier="father",
                relationship_to_proband="FATHER", sex="MALE",
                affected_status="UNAFFECTED", is_proband=False, sampled=True,
                specimen_id=None, metadata_json={},
            ))
            db.add(PedigreeRelationship(
                id=uuid4(), case_id=case_id, parent_member_id=father_id,
                child_member_id=member_id, relationship_type="PARENT_CHILD",
                metadata_json={},
            ))
            db.flush()
            for analysis_id in (parent_id, child_id):
                artifact_id = uuid4()
                db.add(Artifact(
                    id=artifact_id, analysis_id=analysis_id, case_id=case_id,
                    artifact_type="NORMALIZED_VCF", filename="normalized.vcf",
                    media_type="text/vcf", size_bytes=12, sha256="e" * 64,
                    storage_uri=f"file:///fixture/{analysis_id}/normalized.vcf",
                    genome_build="GRCh38", specimen_id=None, paired_artifact_id=None,
                    validation_status="VALIDATED", metadata_json={"stage": "normalize"},
                ))
                db.add(WorkflowStep(
                    id=uuid4(), analysis_id=analysis_id, step_id="normalize",
                    step_order=1, status="SUCCEEDED", attempt=1,
                    input_artifacts=[],
                    output_artifacts=[{"artifact_id": str(artifact_id), "sha256": "e" * 64}],
                    error_code=None, error_message=None,
                    metadata_json={"tool": "bcftools", "tool_version": "1.19"},
                ))
                db.add(WorkflowDecisionRecord(
                    id=uuid4(), analysis_id=analysis_id, step_id="normalize", attempt=1,
                    outcome_kind="SUCCESS", action="CONTINUE", code="STAGE_COMPLETED",
                    message="Normalization completed.", retryable=False,
                    fallback_allowed=False, lab_action_required=False,
                    resource_id=None, fallback_resource_id=None,
                    metadata_json={"output_sha256": "e" * 64},
                ))
                db.add(PhenotypeObservation(
                    id=uuid4(), case_id=case_id, analysis_id=analysis_id,
                    hpo_id="HP:0001250", label="Seizure", present=True,
                    phenotype_status="PRESENT", onset="CHILDHOOD", severity="MODERATE",
                    source="CLINICAL_INPUT", evidence={"source": "fixture"},
                ))
                db.add(TechnicalQCObservation(
                    id=uuid4(), analysis_id=analysis_id, artifact_id=None,
                    metric_name="mean_depth", metric_value=42.0, metric_unit="x",
                    status="PASS", source="LAB_QC", source_version="qc-v1",
                    metadata_json={"fixture": "known-answer"},
                ))
                db.add(QCAssessment(
                    id=uuid4(), analysis_id=analysis_id, assay_id=None,
                    status="PASS", profile_name="germline", profile_version="1",
                    metrics_json={"mean_depth": 42.0},
                    evaluated_rules=[{"rule": "minimum_depth", "status": "PASS"}],
                    gate_status="PASS", reviewer_note=None,
                ))
                db.add(ToolRun(
                    id=uuid4(), analysis_id=analysis_id, tool_name="normalizer",
                    tool_version="1.19", container_digest="sha256:fixture",
                    command_fingerprint="c" * 64, parameters={"reference": "GRCh38"},
                    status="SUCCEEDED", exit_code=0,
                ))
                db.add(SegregationObservation(
                    id=uuid4(), analysis_id=analysis_id, variant_id=variant_id,
                    pedigree_member_id=member_id, genotype="0/1", zygosity="HET",
                    phase="UNKNOWN", allele_observed="G", phenotype_status="AFFECTED",
                    source="LAB_VCF", notes=None, metadata_json={
                        "pedigree_context_snapshot": {
                            "schema_version": 1,
                            "members": [
                                {"member_identifier": "father", "relationship_to_proband": "FATHER", "sex": "MALE", "affected_status": "UNAFFECTED", "is_proband": False, "sampled": True, "specimen_identifier": None, "specimen_type": None, "metadata": {}},
                                {"member_identifier": "proband", "relationship_to_proband": "PROBAND", "sex": "UNKNOWN", "affected_status": "AFFECTED", "is_proband": True, "sampled": True, "specimen_identifier": None, "specimen_type": None, "metadata": {}},
                            ],
                            "relationships": [
                                {"parent_member_identifier": "father", "child_member_identifier": "proband", "relationship_type": "PARENT_CHILD", "metadata": {}}
                            ],
                        },
                    },
                ))
                db.add(InheritanceAssessment(
                    id=uuid4(), analysis_id=analysis_id, variant_id=variant_id,
                    model="AUTOSOMAL_DOMINANT", status="COMPATIBLE", score=None,
                    rationale="Heterozygous candidate; family phase unknown.",
                    observation_fingerprint="d" * 64, reviewer_note=None,
                    created_by="fixture-reviewer",
                ))
                db.add(ConfirmationRecord(
                    id=uuid4(), analysis_id=analysis_id, variant_id=variant_id,
                    version=1, supersedes_record_id=None, required=False,
                    method=None, status="NOT_REQUIRED", result=None, laboratory=None,
                    accession=None, performed_at=None, reviewed_by=None,
                    reviewed_at=None, notes=None, metadata_json={},
                ))
                db.add(SecondaryFindingDecision(
                    id=uuid4(), analysis_id=analysis_id, variant_id=variant_id,
                    version=1, supersedes_decision_id=None,
                    policy_name="secondary-policy", policy_version="1",
                    eligibility="ELIGIBLE", consent_status="CONSENTED",
                    disposition="REVIEW", status="PENDING_REVIEW",
                    rationale="Requires human review.", gene_disease_context={"gene": "GENE1"},
                    reviewed_by=None, reviewed_at=None,
                ))
                db.add(ReviewAction(
                    id=uuid4(), case_id=case_id, analysis_id=analysis_id,
                    variant_id=variant_id, reviewer_id=user_id, action_type="NOTE_ADDED",
                    sequence_number=1, reason="Review fixture", before_state=None,
                    after_state={"note": "reviewed"}, expected_version=0,
                    resulting_version=1,
                ))
            for analysis_id in (parent_id, child_id):
                classification = Classification(
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
                )
                db.add(classification)
                db.add(ReportabilityDecision(
                    id=uuid4(), analysis_id=analysis_id, variant_id=variant_id,
                    classification_id=classification.id, version=1,
                    supersedes_decision_id=None, policy_name="fixture-policy",
                    policy_version="1", disposition="REPORTABLE_CANDIDATE",
                    priority_score=0, priority_band="ROUTINE", reasons=["review"],
                    status="PENDING_REVIEW", review_version=0, reviewed_by=None,
                    approved_at=None,
                ))
                db.add(AnalysisPartition(
                    id=uuid4(), analysis_id=analysis_id, step_id="normalize",
                    partition_key="0:1", ordinal=0, record_start=0, record_end=1,
                    variant_count=1, status="SUCCEEDED",
                    metadata_json={
                        "variant_ids": [str(variant_id)],
                        "sample_calls": [{
                            "variant_id": str(variant_id), "status": "AVAILABLE",
                            "sample_name": "SAMPLE-1", "genotype": "0/1",
                            "zygosity": "HETEROZYGOUS", "phase": "UNPHASED",
                            "phase_set": None, "format_values": {"DP": "30"},
                        }],
                    },
                ))
            for analysis_id in (parent_id, child_id):
                _persist_clinical_input_snapshot(db, analysis_id)
            db.commit()

            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["resource_snapshots_match"] is True
            assert result["scientific_outputs_match"] is True
            assert result["reproducible"] is True
            assert result["decision"] == "MATCH"
            assert result["parent"]["workflow_version"] != result["child"]["workflow_version"]

            child_analysis = db.get(Analysis, child_id)
            child_source = db.get(
                Artifact, UUID(child_analysis.configuration["input_artifact_id"])
            )
            child_source.sha256 = "f" * 64
            db.flush()
            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["decision"] == "MISMATCH"
            child_source.sha256 = "b" * 64

            child_source.sha256 = "z" * 64
            db.flush()
            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["decision"] == "INELIGIBLE_INCOMPLETE_PROVENANCE"
            assert result["child"]["provenance_issues"] == [
                "SOURCE_ARTIFACT_MISSING_OR_UNVERIFIED"
            ]
            child_source.sha256 = "b" * 64

            child_segregation_snapshot = db.query(SegregationObservation).filter_by(
                analysis_id=child_id
            ).one()
            saved_segregation_metadata = child_segregation_snapshot.metadata_json
            child_segregation_snapshot.metadata_json = {}
            db.flush()
            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["decision"] == "INELIGIBLE_INCOMPLETE_PROVENANCE"
            assert result["child"]["provenance_issues"] == [
                "SEGREGATION_PEDIGREE_CONTEXT_SNAPSHOT_MISSING"
            ]
            child_segregation_snapshot.metadata_json = saved_segregation_metadata

            child_review = db.query(ReviewAction).filter_by(analysis_id=child_id).one()
            child_review.action_type = "REJECTED"
            db.flush()
            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["decision"] == "MISMATCH"

            child_review.action_type = "NOTE_ADDED"
            child_secondary = db.query(SecondaryFindingDecision).filter_by(
                analysis_id=child_id
            ).one()
            child_secondary.consent_status = "NOT_DOCUMENTED"
            db.flush()
            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["decision"] == "MISMATCH"

            child_secondary.consent_status = "CONSENTED"
            child_step = db.query(WorkflowStep).filter_by(
                analysis_id=child_id, step_id="normalize"
            ).one()
            child_step.status = "BLOCKED"
            db.flush()
            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["decision"] == "MISMATCH"

            child_step.status = "SUCCEEDED"
            child_artifact = db.query(Artifact).filter_by(analysis_id=child_id).one()
            child_artifact.sha256 = "f" * 64
            db.flush()
            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["decision"] == "INELIGIBLE_INCOMPLETE_PROVENANCE"
            assert result["child"]["provenance_issues"] == [
                "WORKFLOW_ARTIFACT_CHECKSUM_MISMATCH:normalize:output"
            ]

            child_artifact.sha256 = "e" * 64
            child_step.output_artifacts = [
                {"artifact_id": str(child_artifact.id), "sha256": "invalid"}
            ]
            db.flush()
            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["decision"] == "INELIGIBLE_INCOMPLETE_PROVENANCE"
            assert result["child"]["provenance_issues"] == [
                "WORKFLOW_ARTIFACT_CHECKSUM_MISMATCH:normalize:output"
            ]
            child_step.output_artifacts = [
                {"artifact_id": str(child_artifact.id), "sha256": "e" * 64}
            ]

            child_inheritance = db.query(InheritanceAssessment).filter_by(
                analysis_id=child_id
            ).one()
            child_inheritance.status = "INCOMPATIBLE"
            db.flush()
            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["decision"] == "MISMATCH"

            child_inheritance.status = "COMPATIBLE"
            child_segregation = child_segregation_snapshot
            child_segregation.genotype = "1/1"
            db.flush()
            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["decision"] == "MISMATCH"

            child_segregation.genotype = "0/1"
            child_segregation.metadata_json = {
                **child_segregation.metadata_json,
                "pedigree_context_snapshot": {
                    **child_segregation.metadata_json["pedigree_context_snapshot"],
                    "relationships": [
                        {
                            "parent_member_identifier": "father",
                            "child_member_identifier": "proband",
                            "relationship_type": "ADOPTIVE_PARENT",
                            "metadata": {},
                        }
                    ],
                },
            }
            db.flush()
            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["decision"] == "MISMATCH"

            child_segregation.metadata_json = {
                **child_segregation.metadata_json,
                "pedigree_context_snapshot": {
                    **child_segregation.metadata_json["pedigree_context_snapshot"],
                    "relationships": [
                        {
                            "parent_member_identifier": "father",
                            "child_member_identifier": "proband",
                            "relationship_type": "PARENT_CHILD",
                            "metadata": {},
                        }
                    ],
                },
            }
            db.flush()
            child_reportability = db.query(ReportabilityDecision).filter_by(
                analysis_id=child_id
            ).one()
            child_reportability.status = "APPROVED"
            db.flush()
            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["decision"] == "MISMATCH"

            child_reportability.status = "PENDING_REVIEW"
            child_confirmation = db.query(ConfirmationRecord).filter_by(
                analysis_id=child_id
            ).one()
            child_confirmation.status = "COMPLETED"
            db.flush()
            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["decision"] == "MISMATCH"

            child_phenotype = db.query(PhenotypeObservation).filter_by(
                analysis_id=child_id
            ).one()
            child_phenotype.present = False
            child_phenotype.phenotype_status = "ABSENT"
            db.flush()
            child_snapshot_step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == child_id,
                WorkflowStep.step_id == "build_evidence",
            ))
            original_child_snapshot = child_snapshot_step.metadata_json[
                "clinical_input_snapshot"
            ]
            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            # Current case/row state is not substituted for what the completed
            # analyses actually consumed. Child consumed input has now drifted.
            assert result["decision"] == "MISMATCH"
            child_snapshot_step.metadata_json = {
                **child_snapshot_step.metadata_json,
                "clinical_input_snapshot": {
                    **original_child_snapshot,
                    "phenotype_observations": [
                        {**row, "present": False, "phenotype_status": "ABSENT"}
                        if row["hpo_id"] == child_phenotype.hpo_id else row
                        for row in original_child_snapshot["phenotype_observations"]
                    ],
                },
            }
            child_snapshot_step.metadata_json["clinical_input_snapshot_sha256"] = (
                clinical_input_snapshot_digest(
                    child_snapshot_step.metadata_json["clinical_input_snapshot"]
                )
            )
            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["decision"] == "MISMATCH"
            assert result["scientific_outputs_match"] is False

            child_phenotype.present = True
            child_phenotype.phenotype_status = "PRESENT"
            child_snapshot_step.metadata_json = {
                **child_snapshot_step.metadata_json,
                "clinical_input_snapshot": original_child_snapshot,
                "clinical_input_snapshot_sha256": clinical_input_snapshot_digest(
                    original_child_snapshot
                ),
            }
            child_qc = db.query(QCAssessment).filter_by(analysis_id=child_id).one()
            child_qc.gate_status = "REVIEW_REQUIRED"
            db.flush()
            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["decision"] == "MISMATCH"

            child_qc.gate_status = "PASS"
            child_tool = db.query(ToolRun).filter_by(analysis_id=child_id).one()
            child_tool.tool_version = "1.20"
            db.flush()
            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["decision"] == "MISMATCH"

            child_tool.tool_version = "1.19"
            child_analysis.configuration = {
                **child_analysis.configuration,
                "normalization_policy": "different",
            }
            db.flush()
            result = compare_reanalysis_outputs(
                db, parent_analysis_id=parent_id, child_analysis_id=child_id
            )
            assert result["decision"] == "MISMATCH"
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
            for analysis_id in (parent_id, child_id):
                db.add(AnalysisPartition(
                    id=uuid4(), analysis_id=analysis_id, step_id="normalize",
                    partition_key="0:1", ordinal=0, record_start=0, record_end=1,
                    variant_count=1, status="SUCCEEDED",
                    metadata_json={
                        "variant_ids": [str(variant_id)],
                        "sample_calls": [{
                            "variant_id": str(variant_id), "status": "AVAILABLE",
                            "sample_name": "SAMPLE-1", "genotype": "0/1",
                            "zygosity": "HETEROZYGOUS", "phase": "UNPHASED",
                            "phase_set": None, "format_values": {"DP": "30"},
                        }],
                    },
                ))
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
            for analysis_id in (parent_id, child_id):
                _persist_clinical_input_snapshot(db, analysis_id)
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
            assert result["parent"]["provenance_issues"] == [
                "CLINICAL_INPUT_SNAPSHOT_MISSING",
                "SOURCE_ARTIFACT_MISSING_OR_UNVERIFIED"
            ]
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
