from uuid import uuid4

from backend.app.acmg.source_assessment import assess_source_assertion
from backend.app.infrastructure.db.models import ACMGSourceAssertion, ClinGenSpecification


def make_assertion(*, criterion="PS3", status="MET", strength="Strong"):
    return ACMGSourceAssertion(
        id=uuid4(),
        analysis_id=uuid4(),
        variant_id=uuid4(),
        evidence_id=uuid4(),
        criterion=criterion,
        status=status,
        strength=strength,
        source_name="ClinGen ERepo",
        source_version="2.5.6",
        source_record_id="ERepo:abc-123",
        source_classification="Likely Pathogenic",
        condition="Example disease",
        gene="RAG1",
        mondo_id="MONDO:0000572",
        expert_panel="Example VCEP",
        rationale="Source rationale",
        pmids=["12345678"],
        source_payload={},
        assertion_fingerprint="fingerprint",
    )


def make_spec(criteria):
    return ClinGenSpecification(
        id=uuid4(),
        specification_id="GN123",
        version="2.2",
        provider="ClinGen",
        framework="ACMG/AMP",
        source_iri="https://cspec.clinicalgenome.org/cspec/SequenceVariantInterpretation/id/GN123/version/2.2",
        criteria=criteria,
        gene_scope=["RAG1"],
        disease_scope=["Example disease"],
        validated_for_automation=True,
        validation_status="APPROVED_FOR_AUTOMATION",
    )


def test_source_assertion_requires_structured_specification_rule():
    result = assess_source_assertion(
        make_assertion(),
        make_spec({}),
    )
    assert result.status == "REQUIRES_REVIEW"
    assert result.applicable is False
    assert result.source_assertion_ids


def test_source_assertion_respects_explicit_not_applicable():
    result = assess_source_assertion(
        make_assertion(criterion="PS3"),
        make_spec({"PS3": {"applicable": False, "strength": "Strong"}}),
    )
    assert result.status == "NOT_APPLICABLE"
    assert result.applicable is False
    assert result.strength is None


def test_source_assertion_accepts_strength_allowed_by_cspec():
    result = assess_source_assertion(
        make_assertion(criterion="PS3", strength="Supporting"),
        make_spec({"PS3": {"strength": "Supporting"}}),
    )
    assert result.status == "PROPOSED"
    assert result.applicable is True
    assert result.strength == "SUPPORTING"
    assert result.effective_criterion == "PS3"


def test_source_assertion_applies_single_strength_modification():
    result = assess_source_assertion(
        make_assertion(criterion="PS3", strength="Strong"),
        make_spec({"PS3": {"strength": "Supporting", "modification_type": "Strength"}}),
    )
    assert result.status == "PROPOSED"
    assert result.strength == "SUPPORTING"
    assert result.effective_criterion == "PS3_Supporting"
    assert result.metadata["strength_basis"] == "SPECIFICATION_OVERRIDE"


def test_source_assertion_does_not_guess_between_multiple_strengths():
    result = assess_source_assertion(
        make_assertion(criterion="PS3", strength="Strong"),
        make_spec({"PS3": {"strengths": ["Moderate", "Supporting"]}}),
    )
    assert result.status == "REQUIRES_REVIEW"
    assert result.strength is None


def test_not_met_source_assertion_never_becomes_positive_evidence():
    result = assess_source_assertion(
        make_assertion(criterion="BS1", status="NOT_MET", strength=None),
        make_spec({"BS1": {"strength": "Strong"}}),
    )
    assert result.status == "NOT_MET"
    assert result.strength is None
    assert result.direction == "BENIGN"


def test_source_assessment_does_not_create_final_classification():
    result = assess_source_assertion(
        make_assertion(),
        make_spec({"PS3": {"strength": "Strong"}}),
    )
    assert not hasattr(result, "classification")
    assert result.status == "PROPOSED"
