import pytest

from backend.app.acmg.assessment_service import _variant_context
from backend.app.acmg.evaluators import (
    EvaluatorConfigurationError,
    evaluate_ba1_bs1,
    evaluate_pm2,
    evaluate_pp3_bp4,
    evaluate_pvs1,
)


def obs(code="MID", af=0.0, an=10000, ac=None):
    return {
        "observation_id": "POBS-1",
        "population_code": code,
        "population_level": "ANCESTRY",
        "population_label": "Middle Eastern",
        "allele_frequency": af,
        "allele_number": an,
        "allele_count": ac,
        "availability": "AVAILABLE",
    }


def test_variant_context_does_not_choose_first_unselected_transcript_consequence():
    context = _variant_context({
        "effect": None,
        "hgvs_consequences": [
            {"consequence": "stop_gained"},
            {"consequence": "synonymous_variant"},
        ],
    })

    assert context == {"consequence": None}


def test_pm2_requires_explicit_configuration():
    try:
        evaluate_pm2([obs()], profile={})
    except EvaluatorConfigurationError:
        return
    raise AssertionError("PM2 must not run without an explicit specification")


def test_pm2_meets_configured_threshold():
    result = evaluate_pm2(
        [obs(af=0.00001, an=20000)],
        profile={"PM2": {"max_allele_frequency": 0.00005, "minimum_allele_number": 10000, "population_level": "ANCESTRY", "population_codes": ["MID"]}},
    )
    assert result.applicable is True
    assert result.strength == "SUPPORTING"
    assert result.direction == "PATHOGENIC"


def test_pm2_honors_explicit_disease_specification_strength():
    result = evaluate_pm2(
        [obs(af=0.00001, an=20000)],
        profile={"PM2": {
            "max_allele_frequency": 0.00005,
            "minimum_allele_number": 10000,
            "population_level": "ANCESTRY",
            "population_codes": ["MID"],
            "strength": "MODERATE",
        }},
    )

    assert result.applicable is True
    assert result.strength == "MODERATE"


def test_pm2_missing_data_is_not_zero():
    result = evaluate_pm2(
        [{"observation_id": "POBS-2", "population_code": "SAU", "population_level": "COUNTRY", "availability": "NOT_CONFIGURED"}],
        profile={"PM2": {"max_allele_frequency": 0.00005, "minimum_allele_number": 10000}},
    )
    assert result.applicable is False
    assert result.metadata["unavailable_population_data"] is True


def test_pm2_does_not_implicitly_mix_gnomad_cohort_with_joint_observations():
    result = evaluate_pm2(
        [obs(code="MID_EXOMES", af=0.000001, an=20000)],
        profile={"PM2": {"max_allele_frequency": 0.00005, "minimum_allele_number": 10000}},
    )
    assert result.applicable is False
    assert result.status == "REQUIRES_REVIEW"


def test_pm2_can_use_cohort_observation_when_explicitly_configured():
    result = evaluate_pm2(
        [obs(code="MID_EXOMES", af=0.000001, an=20000)],
        profile={"PM2": {
            "max_allele_frequency": 0.00005,
            "minimum_allele_number": 10000,
            "population_codes": ["MID_EXOMES"],
        }},
    )
    assert result.applicable is True
    assert result.status == "PROPOSED"


def test_bs1_uses_explicit_threshold():
    result = evaluate_ba1_bs1(
        [obs(af=0.01)],
        criterion="BS1",
        profile={"BS1": {"minimum_allele_frequency": 0.005, "minimum_allele_number": 10000, "population_codes": ["MID"]}},
    )
    assert result.applicable is True
    assert result.strength == "STRONG"
    assert result.direction == "BENIGN"


@pytest.mark.parametrize(
    "bad_observation",
    [
        {"allele_frequency": -0.01, "allele_number": 10000, "allele_count": 0},
        {"allele_frequency": 1.01, "allele_number": 10000, "allele_count": 0},
        {"allele_frequency": float("nan"), "allele_number": 10000, "allele_count": 0},
        {"allele_frequency": float("inf"), "allele_number": 10000, "allele_count": 0},
        {"allele_frequency": True, "allele_number": 10000, "allele_count": 0},
        {"allele_frequency": 0.0, "allele_number": 100, "allele_count": 101},
        {"allele_frequency": 0.0, "allele_number": 100, "allele_count": -1},
        {"allele_frequency": 0.0, "allele_number": 100.5, "allele_count": 0},
        {"allele_frequency": 0.0, "allele_number": True, "allele_count": 0},
        {"allele_frequency": 0.0, "allele_number": "100", "allele_count": 0},
        {"allele_frequency": 0.0, "allele_number": 100, "allele_count": "0"},
        {"allele_frequency": 0.0, "allele_number": 0, "allele_count": 0},
        {"allele_frequency": 0.0, "allele_number": None, "allele_count": 0},
        {"allele_frequency": 0.01, "allele_number": 100, "allele_count": 0},
        {"allele_frequency": 0.02, "allele_number": 100, "allele_count": 1},
    ],
    ids=[
        "negative-af", "af-over-one", "nan-af", "infinite-af", "boolean-af", "ac-over-an",
        "negative-ac", "fractional-an", "boolean-an", "string-an", "string-ac", "zero-denominator",
        "missing-denominator", "nonzero-af-with-zero-ac", "af-inconsistent-with-ac-an",
    ],
)
@pytest.mark.parametrize("criterion", ["PM2", "BS1"])
def test_population_criteria_require_review_for_malformed_available_metrics(
    bad_observation, criterion
):
    result = obs()
    result.update(bad_observation)
    profile = {
        "PM2": {"max_allele_frequency": 0.00005, "minimum_allele_number": 100},
        "BS1": {"minimum_allele_frequency": 0.005, "minimum_allele_number": 100},
    }

    if criterion == "PM2":
        assessment = evaluate_pm2([result], profile=profile)
    else:
        assessment = evaluate_ba1_bs1([result], criterion="BS1", profile=profile)

    assert assessment.status == "REQUIRES_REVIEW"
    assert assessment.applicable is False
    assert assessment.strength is None
    assert assessment.metadata["invalid_population_observations"]


def test_population_criteria_ignore_malformed_unselected_cohort():
    valid = obs(code="MID", af=0.00001, an=20000)
    unselected = obs(code="MID_EXOMES", af=-1, an=1000, ac=0)
    profile = {
        "PM2": {
            "max_allele_frequency": 0.00005,
            "minimum_allele_number": 10000,
            "population_codes": ["MID"],
        }
    }

    result = evaluate_pm2([valid, unselected], profile=profile)

    assert result.status == "PROPOSED"
    assert result.evidence_ids == ("POBS-1",)


def test_pm2_does_not_report_not_met_when_selected_population_data_is_missing():
    sufficiently_rare = obs(af=0.00001, an=20000)
    unavailable = {
        **obs(code="SAU", af=None, an=None),
        "availability": "NOT_AVAILABLE",
    }
    result = evaluate_pm2(
        [sufficiently_rare, unavailable],
        profile={"PM2": {
            "max_allele_frequency": 0.00005,
            "minimum_allele_number": 10000,
        }},
    )

    assert result.status == "REQUIRES_REVIEW"
    assert result.applicable is False
    assert result.metadata["incomplete_population_observations"]


def test_bs1_does_not_report_not_met_when_selected_population_data_is_missing():
    below_threshold = obs(code="MID", af=0.001, an=20000)
    unavailable = {
        **obs(code="SAU", af=None, an=None),
        "availability": "NOT_AVAILABLE",
    }
    result = evaluate_ba1_bs1(
        [below_threshold, unavailable],
        criterion="BS1",
        profile={"BS1": {
            "minimum_allele_frequency": 0.005,
            "minimum_allele_number": 10000,
        }},
    )

    assert result.status == "REQUIRES_REVIEW"
    assert result.applicable is False
    assert result.metadata["incomplete_population_observations"]


def test_bs1_reports_not_met_only_when_sufficient_selected_data_is_below_threshold():
    result = evaluate_ba1_bs1(
        [obs(code="MID", af=0.001, an=20000)],
        criterion="BS1",
        profile={"BS1": {
            "minimum_allele_frequency": 0.005,
            "minimum_allele_number": 10000,
        }},
    )

    assert result.status == "NOT_MET"
    assert result.applicable is False


@pytest.mark.parametrize("criterion,field,value", [
    ("PM2", "max_allele_frequency", -0.1),
    ("PM2", "max_allele_frequency", 1.1),
    ("BS1", "minimum_allele_frequency", -0.1),
    ("BS1", "minimum_allele_frequency", 1.1),
])
def test_population_criteria_reject_frequency_threshold_outside_unit_interval(
    criterion, field, value
):
    with pytest.raises(EvaluatorConfigurationError, match=r"\[0, 1\]"):
        if criterion == "PM2":
            evaluate_pm2([obs()], profile={"PM2": {
                "max_allele_frequency": value,
                "minimum_allele_number": 100,
            }})
        else:
            evaluate_ba1_bs1([obs()], criterion="BS1", profile={"BS1": {
                "minimum_allele_frequency": value,
                "minimum_allele_number": 100,
            }})


def test_pp3_requires_calibrated_profile():
    try:
        evaluate_pp3_bp4({"REVEL": 0.9}, criterion="PP3", profile={})
    except EvaluatorConfigurationError:
        return
    raise AssertionError("PP3 must require explicit calibration")


def test_pp3_uses_calibrated_interval():
    result = evaluate_pp3_bp4(
        {"REVEL": 0.91},
        criterion="PP3",
        profile={"PP3": {"predictor": "REVEL", "minimum_score": 0.9, "strength": "SUPPORTING"}},
    )
    assert result.applicable is True
    assert result.strength == "SUPPORTING"
    assert result.direction == "PATHOGENIC"


@pytest.mark.parametrize(
    "predictor_observations",
    [
        {},
        {"REVEL": None},
        {"REVEL": "not-a-score"},
        {"REVEL": float("nan")},
        {"REVEL": float("inf")},
        {"REVEL": True},
    ],
)
def test_pp3_missing_or_invalid_predictor_score_requires_review(predictor_observations):
    result = evaluate_pp3_bp4(
        predictor_observations,
        criterion="PP3",
        profile={"PP3": {
            "predictor": "REVEL",
            "minimum_score": 0.9,
            "strength": "SUPPORTING",
        }},
    )

    assert result.status == "REQUIRES_REVIEW"
    assert result.applicable is False
    assert result.strength is None


def test_pp3_valid_score_outside_calibrated_interval_is_not_met():
    result = evaluate_pp3_bp4(
        {"REVEL": 0.7},
        criterion="PP3",
        profile={"PP3": {
            "predictor": "REVEL",
            "minimum_score": 0.9,
            "strength": "SUPPORTING",
        }},
    )

    assert result.status == "NOT_MET"
    assert result.applicable is False


@pytest.mark.parametrize(
    "configuration",
    [
        {"predictor": "REVEL", "minimum_score": "invalid"},
        {"predictor": "REVEL", "minimum_score": 0.9, "maximum_score": "invalid"},
        {"predictor": "REVEL", "minimum_score": 0.9, "maximum_score": 0.2},
        {"predictor": "REVEL", "minimum_score": 0.9, "strength": "UNVALIDATED"},
    ],
)
def test_pp3_rejects_invalid_calibration_configuration(configuration):
    with pytest.raises(EvaluatorConfigurationError):
        evaluate_pp3_bp4(
            {"REVEL": 0.95},
            criterion="PP3",
            profile={"PP3": configuration},
        )


def test_pvs1_requires_lof_mechanism():
    try:
        evaluate_pvs1(
            {"consequence": "frameshift_variant"},
            profile={"PVS1": {"allowed_consequences": ["frameshift_variant"]}},
        )
    except EvaluatorConfigurationError:
        return
    raise AssertionError("PVS1 must require explicit LoF mechanism")


@pytest.mark.parametrize(
    "consequence",
    ["frameshift_variant", "missense_variant", None],
    ids=["configured-lof", "unconfigured-consequence", "missing-consequence"],
)
def test_pvs1_requires_review_until_decision_tree_is_implemented(consequence):
    result = evaluate_pvs1(
        {"consequence": consequence},
        profile={"PVS1": {"lof_mechanism_established": True, "allowed_consequences": ["frameshift_variant"], "strength": "VERY_STRONG"}},
    )
    assert result.applicable is False
    assert result.status == "REQUIRES_REVIEW"
    assert result.strength is None
    assert result.metadata["automated_strength"] == "NOT_PRODUCED"
    assert result.metadata["review_reason"] == "PVS1_DECISION_TREE_NOT_IMPLEMENTED"
