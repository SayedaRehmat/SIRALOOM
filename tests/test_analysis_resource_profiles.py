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


def test_analysis_create_exposes_resource_profile_as_first_class_configuration():
    from uuid import uuid4
    from backend.app.domain.schemas import AnalysisCreate

    payload = AnalysisCreate(
        input_artifact_id=uuid4(),
        resource_profile_id="WES_GRCh38_STANDARD",
    )
    assert payload.resource_profile_id == "WES_GRCh38_STANDARD"


def test_analysis_create_keeps_resource_profile_optional_for_legacy_callers():
    from uuid import uuid4
    from backend.app.domain.schemas import AnalysisCreate

    payload = AnalysisCreate(input_artifact_id=uuid4())
    assert payload.resource_profile_id is None


def test_workflow_stage_resource_projection_is_deterministic_and_actionable():
    from backend.app.domain.resource_profile_resolver import (
        AnalysisResourcePlan,
        ResourceResolutionIssue,
        build_workflow_stage_resource_plan,
    )

    plan = AnalysisResourcePlan(
        profile_id="WES_GRCh38_STANDARD",
        profile_version="1",
        genome_build="GRCh38",
        deployment_profile_type="LABORATORY",
        deployment_profile_version="1",
        status="READY_WITH_LIMITATIONS",
        selected=(),
        issues=(
            ResourceResolutionIssue(
                capability=CLINICAL_DATABASE,
                required=False,
                code="RESOURCE_UNAVAILABLE",
                message="ClinVar is unavailable",
                candidate_count=0,
            ),
        ),
        plan_hash="test",
    )

    stages = build_workflow_stage_resource_plan(plan)
    assert [stage["step_id"] for stage in stages] == [
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
    assert stages[0]["status"] == "READY"
    evidence = next(stage for stage in stages if stage["step_id"] == "build_evidence")
    assert evidence["status"] == "READY_WITH_LIMITATIONS"
    assert evidence["issues"][0]["capability"] == CLINICAL_DATABASE
    assert next(stage for stage in stages if stage["step_id"] == "normalize")["status"] == "READY"


def test_workflow_stage_resource_projection_blocks_only_stages_with_required_issues():
    from backend.app.domain.resource_profile_resolver import (
        AnalysisResourcePlan,
        ResourceResolutionIssue,
        build_workflow_stage_resource_plan,
    )

    plan = AnalysisResourcePlan(
        profile_id="WES_GRCh38_STANDARD",
        profile_version="1",
        genome_build="GRCh38",
        deployment_profile_type="LABORATORY",
        deployment_profile_version="1",
        status="BLOCKED",
        selected=(),
        issues=(
            ResourceResolutionIssue(
                capability=REFERENCE_PACKAGE,
                required=True,
                code="RESOURCE_UNAVAILABLE",
                message="Reference package is unavailable",
                candidate_count=0,
            ),
        ),
        plan_hash="test",
    )

    stages = build_workflow_stage_resource_plan(plan)
    normalize = next(stage for stage in stages if stage["step_id"] == "normalize")
    assert normalize["status"] == "BLOCKED"
    assert normalize["issues"][0]["required"] is True
    assert next(stage for stage in stages if stage["step_id"] == "validate_input")["status"] == "READY"


def test_preflight_persists_analysis_and_stage_resource_state_on_block():
    from types import SimpleNamespace
    from uuid import uuid4
    import backend.app.application.analysis as analysis_module
    from backend.app.domain.resource_profile_resolver import AnalysisResourcePlan, ResourceResolutionIssue
    from backend.app.infrastructure.db.models import Analysis

    plan = AnalysisResourcePlan(
        profile_id="WES_GRCh38_STANDARD",
        profile_version="1",
        genome_build="GRCh38",
        deployment_profile_type="LABORATORY",
        deployment_profile_version="1",
        status="BLOCKED",
        selected=(),
        issues=(ResourceResolutionIssue(
            capability=REFERENCE_PACKAGE,
            required=True,
            code="RESOURCE_UNAVAILABLE",
            message="Reference package unavailable",
        ),),
        plan_hash="blocked-plan",
    )
    db = SimpleNamespace(add=lambda _x: None, flush=lambda: None)
    analysis = Analysis(
        id=uuid4(), case_id=uuid4(), parent_analysis_id=None, assay_id=None,
        analysis_type="GERMLINE", workflow_id="variant", workflow_version="1",
        status="CREATED", queue_task_id=None, reference_build="GRCh38",
        configuration={"resource_profile_id": "WES_GRCh38_STANDARD"},
        started_at=None, completed_at=None, created_by=None,
    )
    original = analysis_module.resolve_analysis_resource_profile
    try:
        analysis_module.resolve_analysis_resource_profile = lambda *args, **kwargs: plan
        result = analysis_module.preflight_analysis_resources(
            db, analysis=analysis, organization_id=uuid4()
        )
    finally:
        analysis_module.resolve_analysis_resource_profile = original

    assert result is plan
    assert analysis.status == "BLOCKED"
    assert analysis.configuration["resource_plan"]["status"] == "BLOCKED"
    normalize = next(x for x in analysis.configuration["resource_stage_plan"] if x["step_id"] == "normalize")
    assert normalize["status"] == "BLOCKED"
    assert normalize["issues"][0]["code"] == "RESOURCE_UNAVAILABLE"


def test_preflight_persists_ready_with_limitations_without_blocking_analysis():
    from types import SimpleNamespace
    from uuid import uuid4
    import backend.app.application.analysis as analysis_module
    from backend.app.domain.resource_profile_resolver import AnalysisResourcePlan, ResourceResolutionIssue
    from backend.app.infrastructure.db.models import Analysis

    plan = AnalysisResourcePlan(
        profile_id="WES_GRCh38_STANDARD",
        profile_version="1",
        genome_build="GRCh38",
        deployment_profile_type="LABORATORY",
        deployment_profile_version="1",
        status="READY_WITH_LIMITATIONS",
        selected=(),
        issues=(ResourceResolutionIssue(
            capability=CLINICAL_DATABASE,
            required=False,
            code="RESOURCE_UNAVAILABLE",
            message="ClinVar unavailable",
        ),),
        plan_hash="limited-plan",
    )
    db = SimpleNamespace(add=lambda _x: None, flush=lambda: None)
    analysis = Analysis(
        id=uuid4(), case_id=uuid4(), parent_analysis_id=None, assay_id=None,
        analysis_type="GERMLINE", workflow_id="variant", workflow_version="1",
        status="CREATED", queue_task_id=None, reference_build="GRCh38",
        configuration={"resource_profile_id": "WES_GRCh38_STANDARD"},
        started_at=None, completed_at=None, created_by=None,
    )
    original = analysis_module.resolve_analysis_resource_profile
    try:
        analysis_module.resolve_analysis_resource_profile = lambda *args, **kwargs: plan
        result = analysis_module.preflight_analysis_resources(
            db, analysis=analysis, organization_id=uuid4()
        )
    finally:
        analysis_module.resolve_analysis_resource_profile = original

    assert result is plan
    assert analysis.status == "CREATED"
    evidence = next(x for x in analysis.configuration["resource_stage_plan"] if x["step_id"] == "build_evidence")
    assert evidence["status"] == "READY_WITH_LIMITATIONS"
    assert evidence["issues"][0]["required"] is False
