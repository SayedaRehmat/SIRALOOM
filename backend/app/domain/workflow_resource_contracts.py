"""Canonical scientific workflow-stage contracts.

These contracts are declarative knowledge: they describe the resource classes a
stage consumes and the outputs it is expected to make available. Orchestration
may continue to evolve independently; this module is intentionally side-effect
free so it can be used by setup/preflight, capacity planning, reanalysis and
future execution adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from backend.app.domain.resource_capabilities import (
    ACMG_RULE_SPECIFICATION,
    ANNOTATION_ENGINE,
    CLINICAL_DATABASE,
    COMPUTATIONAL_PREDICTOR,
    FUNCTIONAL_EVIDENCE,
    GENE_DISEASE,
    GENE_PANEL,
    INTERNAL_LAB_EVIDENCE,
    LITERATURE_PROVIDER,
    PHENOTYPE_ONTOLOGY,
    POPULATION,
    POPULATION_SECONDARY,
    REFERENCE_PACKAGE,
    SPLICING_PREDICTOR,
)


@dataclass(frozen=True)
class WorkflowStageContract:
    step_id: str
    order: int
    purpose: str
    required_resources: tuple[str, ...]
    optional_resources: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    continuation_if_optional_unavailable: bool
    human_review_expected: bool


WORKFLOW_STAGE_CONTRACTS: Final[tuple[WorkflowStageContract, ...]] = (
    WorkflowStageContract(
        "validate_input", 1,
        "Validate VCF structure, semantics, supported variant scope and case constraints.",
        (), (GENE_PANEL,),
        ("input_vcf",),
        ("validated_vcf_profile",),
        True, False,
    ),
    WorkflowStageContract(
        "normalize", 2,
        "Produce reference-aware, deterministic variant representation.",
        (REFERENCE_PACKAGE,), (),
        ("validated_vcf", "reference_package"),
        ("normalized_vcf", "variant_identity"),
        False, False,
    ),
    WorkflowStageContract(
        "annotate", 3,
        "Produce consequence, transcript and HGVS annotation.",
        (ANNOTATION_ENGINE,), (),
        ("normalized_variant", "reference_package"),
        ("gene", "transcript", "consequence", "hgvs"),
        False, False,
    ),
    WorkflowStageContract(
        "population", 4,
        "Acquire population allele-frequency/count evidence with population context.",
        (POPULATION,), (POPULATION_SECONDARY,),
        ("normalized_variant",),
        ("population_evidence",),
        False, False,
    ),
    WorkflowStageContract(
        "build_evidence", 5,
        "Assemble clinical, gene-disease, phenotype, computational, splicing, functional, literature and internal evidence.",
        (),
        (
            CLINICAL_DATABASE,
            GENE_DISEASE,
            PHENOTYPE_ONTOLOGY,
            COMPUTATIONAL_PREDICTOR,
            SPLICING_PREDICTOR,
            FUNCTIONAL_EVIDENCE,
            LITERATURE_PROVIDER,
            INTERNAL_LAB_EVIDENCE,
        ),
        ("normalized_variant", "annotation", "population", "case_context"),
        ("evidence_records", "evidence_gaps", "evidence_provenance"),
        True, True,
    ),
    WorkflowStageContract(
        "acmg_assessment", 6,
        "Evaluate evidence against the applicable ACMG/AMP and ClinGen specifications.",
        (ACMG_RULE_SPECIFICATION,), (),
        ("evidence_records", "gene", "disease"),
        ("criterion_assessments", "classification_proposal", "classification_gaps"),
        False, True,
    ),
    WorkflowStageContract(
        "review", 7,
        "Human review, evidence reconciliation and clinical sign-out preparation.",
        (), (),
        ("classification_proposal", "evidence_records"),
        ("review_decision", "review_provenance"),
        True, True,
    ),
    WorkflowStageContract(
        "reportability", 8,
        "Apply laboratory reporting policy to reviewed findings.",
        (), (GENE_PANEL,),
        ("review_decision", "test_scope"),
        ("reportability_decision",),
        True, True,
    ),
    WorkflowStageContract(
        "report", 9,
        "Generate an immutable clinical report version from approved decisions.",
        (), (),
        ("reportability_decision", "review_decision"),
        ("report_version",),
        False, True,
    ),
    WorkflowStageContract(
        "export_provenance", 10,
        "Persist the complete reproducibility and audit package.",
        (), (),
        ("report_version", "resource_snapshot", "execution_records"),
        ("provenance_package",),
        False, False,
    ),
)


def get_workflow_stage_contract(step_id: str) -> WorkflowStageContract:
    key = str(step_id or "").strip()
    for contract in WORKFLOW_STAGE_CONTRACTS:
        if contract.step_id == key:
            return contract
    raise KeyError(f"unknown workflow step: {step_id!r}")


def required_resource_types(step_id: str) -> tuple[str, ...]:
    return get_workflow_stage_contract(step_id).required_resources


def optional_resource_types(step_id: str) -> tuple[str, ...]:
    return get_workflow_stage_contract(step_id).optional_resources
