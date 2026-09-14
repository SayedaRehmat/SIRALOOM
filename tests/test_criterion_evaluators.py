from backend.app.acmg.evaluators import (
    EvaluatorConfigurationError,
    evaluate_ba1_bs1,
    evaluate_pm2,
    evaluate_pp3_bp4,
    evaluate_pvs1,
)


def obs(code="MID", af=0.0, an=10000, ac=0):
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
    assert result.strength == "MODERATE"
    assert result.direction == "PATHOGENIC"


def test_pm2_missing_data_is_not_zero():
    result = evaluate_pm2(
        [{"observation_id": "POBS-2", "population_code": "SAU", "population_level": "COUNTRY", "availability": "NOT_CONFIGURED"}],
        profile={"PM2": {"max_allele_frequency": 0.00005, "minimum_allele_number": 10000}},
    )
    assert result.applicable is False
    assert result.metadata["unavailable_population_data"] is True


def test_bs1_uses_explicit_threshold():
    result = evaluate_ba1_bs1(
        [obs(af=0.01)],
        criterion="BS1",
        profile={"BS1": {"minimum_allele_frequency": 0.005, "minimum_allele_number": 10000, "population_codes": ["MID"]}},
    )
    assert result.applicable is True
    assert result.strength == "STRONG"
    assert result.direction == "BENIGN"


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


def test_pvs1_requires_lof_mechanism():
    try:
        evaluate_pvs1(
            {"consequence": "frameshift_variant"},
            profile={"PVS1": {"allowed_consequences": ["frameshift_variant"]}},
        )
    except EvaluatorConfigurationError:
        return
    raise AssertionError("PVS1 must require explicit LoF mechanism")


def test_pvs1_conservative_gate():
    result = evaluate_pvs1(
        {"consequence": "frameshift_variant"},
        profile={"PVS1": {"lof_mechanism_established": True, "allowed_consequences": ["frameshift_variant"], "strength": "VERY_STRONG"}},
    )
    assert result.applicable is True
    assert result.strength == "VERY_STRONG"
