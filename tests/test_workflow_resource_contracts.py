from backend.app.domain.resource_capabilities import (
    ACMG_RULE_SPECIFICATION,
    ANNOTATION_ENGINE,
    CLINICAL_DATABASE,
    GENE_DISEASE,
    LITERATURE_PROVIDER,
    POPULATION,
    REFERENCE_PACKAGE,
    SPLICING_PREDICTOR,
)
from backend.app.domain.workflow_resource_contracts import (
    WORKFLOW_STAGE_CONTRACTS,
    get_workflow_stage_contract,
)


def test_canonical_workflow_contains_all_current_variant_steps_in_order():
    assert [x.step_id for x in WORKFLOW_STAGE_CONTRACTS] == [
        "validate_input",
        "normalize",
        "annotate",
        "population",
        "build_evidence",
        "acmg_assessment",
        "review",
        "reportability",
        "report",
        "export_provenance",
    ]
    assert [x.order for x in WORKFLOW_STAGE_CONTRACTS] == list(range(1, 11))


def test_normalization_and_annotation_have_explicit_resource_dependencies():
    assert get_workflow_stage_contract("normalize").required_resources == (REFERENCE_PACKAGE,)
    assert get_workflow_stage_contract("annotate").required_resources == (ANNOTATION_ENGINE,)


def test_evidence_stage_knows_the_distinct_evidence_resource_classes():
    optional = set(get_workflow_stage_contract("build_evidence").optional_resources)
    assert {
        CLINICAL_DATABASE,
        GENE_DISEASE,
        LITERATURE_PROVIDER,
        SPLICING_PREDICTOR,
    } <= optional


def test_acmg_stage_requires_rule_specification_not_a_generic_annotation_resource():
    contract = get_workflow_stage_contract("acmg_assessment")
    assert contract.required_resources == (ACMG_RULE_SPECIFICATION,)
    assert "evidence_records" in contract.inputs
    assert "criterion_assessments" in contract.outputs
