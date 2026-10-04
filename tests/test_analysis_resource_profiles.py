from backend.app.domain.analysis_resource_profiles import (
    get_analysis_resource_profile,
    supported_analysis_resource_profiles,
)
from backend.app.domain.resource_capabilities import (
    ACMG_RULE_SPECIFICATION,
    ANNOTATION_ENGINE,
    CLINICAL_DATABASE,
    POPULATION,
    REFERENCE_PACKAGE,
)
from backend.app.domain.resource_profile_resolver import _provider_rank


def test_standard_wes_profile_has_nonnegotiable_core_capabilities():
    profile = get_analysis_resource_profile("WES_GRCh38_STANDARD")
    assert profile.genome_build == "GRCh38"
    assert profile.assay_scope == "WES"
    assert profile.required_capabilities == (
        REFERENCE_PACKAGE,
        ANNOTATION_ENGINE,
        POPULATION,
        ACMG_RULE_SPECIFICATION,
    )


def test_standard_profile_treats_external_evidence_as_optional():
    profile = get_analysis_resource_profile("WES_GRCh38_STANDARD")
    optional = profile.optional_capabilities
    assert CLINICAL_DATABASE in optional
    assert REFERENCE_PACKAGE not in optional


def test_profiles_are_explicitly_versioned():
    assert "WES_GRCh38_STANDARD" in supported_analysis_resource_profiles()
    assert get_analysis_resource_profile("WES_GRCh38_STANDARD").version == "1"


def test_provider_preference_is_deterministic():
    assert _provider_rank("GENEBE", ("GENEBE", "VEP")) == 0
    assert _provider_rank("VEP", ("GENEBE", "VEP")) == 1
    assert _provider_rank("CUSTOM", ("GENEBE", "VEP")) == 2


def test_unknown_profile_is_rejected():
    try:
        get_analysis_resource_profile("does_not_exist")
    except KeyError:
        pass
    else:
        raise AssertionError("unknown profile must be rejected")


def test_optional_resource_limitations_do_not_make_plan_unrunnable():
    from backend.app.domain.resource_profile_resolver import AnalysisResourcePlan

    plan = AnalysisResourcePlan(
        profile_id="WES_GRCh38_STANDARD",
        profile_version="1",
        genome_build="GRCh38",
        deployment_profile_type="LABORATORY",
        deployment_profile_version="1",
        status="READY_WITH_LIMITATIONS",
        selected=(),
        issues=(),
        plan_hash="test",
    )
    assert plan.is_ready is True
