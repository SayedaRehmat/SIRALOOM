import pytest

from backend.app.domain.variant_eligibility import evaluate_small_variant_eligibility


def _validation(**overrides):
    value = {
        "source_record_count": 12,
        "parsed_variant_record_count": 12,
        "symbolic_source_record_count": 0,
        "breakend_source_record_count": 0,
        "gvcf_marker_count": 0,
        "telomere_record_count": 0,
        "unresolved_spanning_deletion_record_count": 0,
    }
    value.update(overrides)
    return value


def test_plain_snv_small_indel_vcf_is_eligible():
    result = evaluate_small_variant_eligibility(_validation())
    assert result["scope"] == "SNV_SMALL_INDEL"
    assert result["status"] == "ELIGIBLE"
    assert result["reason_codes"] == []


@pytest.mark.parametrize(
    ("counter", "count", "reason_code"),
    [
        ("symbolic_source_record_count", 1, "UNSUPPORTED_SYMBOLIC_SOURCE_RECORD_COUNT"),
        ("breakend_source_record_count", 1, "UNSUPPORTED_BREAKEND_SOURCE_RECORD_COUNT"),
        ("gvcf_marker_count", 1, "UNSUPPORTED_GVCF_MARKER_COUNT"),
        ("telomere_record_count", 1, "UNSUPPORTED_TELOMERE_RECORD_COUNT"),
        (
            "unresolved_spanning_deletion_record_count",
            1,
            "UNSUPPORTED_UNRESOLVED_SPANNING_DELETION_RECORD_COUNT",
        ),
    ],
)
def test_unsupported_variant_classes_are_not_eligible(counter, count, reason_code):
    result = evaluate_small_variant_eligibility(_validation(**{counter: count}))
    assert result["status"] == "INELIGIBLE"
    assert reason_code in result["reason_codes"]
    assert result["reasons"]


def test_missing_or_invalid_validation_counters_fail_closed():
    assert evaluate_small_variant_eligibility(None)["status"] == "NOT_ASSESSED"
    assert evaluate_small_variant_eligibility({"source_record_count": 2})["status"] == "NOT_ASSESSED"
    assert evaluate_small_variant_eligibility(
        _validation(symbolic_source_record_count=True)
    )["status"] == "NOT_ASSESSED"


def test_no_parsed_variant_records_are_not_eligible():
    result = evaluate_small_variant_eligibility(_validation(parsed_variant_record_count=0))
    assert result["status"] == "INELIGIBLE"
    assert "NO_VARIANT_RECORDS_FOR_SMALL_VARIANT_ANALYSIS" in result["reason_codes"]
