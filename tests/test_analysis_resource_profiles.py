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

def test_annotation_provider_policy_is_deployment_specific():
    from backend.app.domain.resource_profile_resolver import _effective_preferred_providers

    profile = get_analysis_resource_profile("WES_GRCh38_STANDARD")
    annotation = next(
        requirement
        for requirement in profile.requirements
        if requirement.capability == ANNOTATION_ENGINE
    )

    assert _effective_preferred_providers(
        annotation, deployment_profile_type="TRIAL_PUBLIC"
    ) == ("GENEBE",)
    assert _effective_preferred_providers(
        annotation, deployment_profile_type="LABORATORY"
    ) == ("VEP",)


def test_non_annotation_resources_keep_profile_provider_preferences():
    from backend.app.domain.resource_profile_resolver import _effective_preferred_providers

    profile = get_analysis_resource_profile("WES_GRCh38_STANDARD")
    population = next(
        requirement
        for requirement in profile.requirements
        if requirement.capability == POPULATION
    )

    assert _effective_preferred_providers(
        population, deployment_profile_type="LABORATORY"
    ) == ("GNOMAD",)


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


def test_unregistered_optional_resources_are_not_reported_as_limitations():
    """Optional capabilities are opt-in; absence means not applicable."""
    from types import SimpleNamespace
    from uuid import uuid4
    from backend.app.domain.resource_profile_resolver import resolve_analysis_resource_profile

    class _Scalar:
        def all(self):
            return []

    class _DB:
        def scalars(self, _query):
            return _Scalar()

    class _Policy:
        profile_type = "LABORATORY"
        profile_version = "1"
        allow_siraloom_managed_global_resources = False
        require_organization_binding_for_lab_resources = True

    import backend.app.domain.resource_profile_resolver as resolver_module
    original_policy = resolver_module.resolve_resource_deployment_policy
    try:
        resolver_module.resolve_resource_deployment_policy = lambda *args, **kwargs: _Policy()
        plan = resolve_analysis_resource_profile(
            _DB(),
            organization_id=uuid4(),
            profile_id="WES_GRCh38_STANDARD",
        )
    finally:
        resolver_module.resolve_resource_deployment_policy = original_policy

    assert plan.status == "BLOCKED"
    assert all(issue.required for issue in plan.issues)
    assert all(issue.capability not in {
        "CLINICAL_DATABASE",
        "GENE_DISEASE",
        "PHENOTYPE_ONTOLOGY",
        "COMPUTATIONAL_PREDICTOR",
        "SPLICING_PREDICTOR",
        "LITERATURE_PROVIDER",
        "INTERNAL_LAB_EVIDENCE",
        "POPULATION_SECONDARY",
    } for issue in plan.issues)


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
    added = []
    class _ScalarResult:
        def all(self):
            return []
    class _DB:
        def scalars(self, _query):
            return _ScalarResult()
        def add(self, value):
            added.append(value)
        def flush(self):
            return None
    db = _DB()
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
    normalize_step = next(step for step in added if step.step_id == "normalize")
    assert normalize_step.status == "BLOCKED"
    assert normalize_step.metadata_json["next_step"] == "resource_setup"
    assert normalize_step.metadata_json["workflow_action"] == "WAIT_FOR_RESOURCE"
    assert normalize_step.metadata_json["resource_readiness"]["status"] == "BLOCKED"


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
    db = SimpleNamespace(
        scalars=lambda _query: SimpleNamespace(all=lambda: []),
        add=lambda _x: None,
        flush=lambda: None,
    )
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


def test_preflight_resumes_previously_resource_blocked_analysis_when_resources_recover():
    from uuid import uuid4
    import backend.app.application.analysis as analysis_module
    from backend.app.domain.resource_profile_resolver import AnalysisResourcePlan
    from backend.app.infrastructure.db.models import Analysis, WorkflowStep

    analysis = Analysis(
        id=uuid4(), case_id=uuid4(), parent_analysis_id=None, assay_id=None,
        analysis_type="GERMLINE", workflow_id="variant", workflow_version="1",
        status="BLOCKED", queue_task_id=None, reference_build="GRCh38",
        configuration={
            "resource_profile_id": "WES_GRCh38_STANDARD",
            "resource_plan": {"status": "BLOCKED"},
        },
        started_at=None, completed_at=None, created_by=None,
    )
    blocked_step = WorkflowStep(
        id=uuid4(),
        analysis_id=analysis.id,
        step_id="normalize",
        step_order=2,
        status="BLOCKED",
        attempt=0,
        input_artifacts=[],
        output_artifacts=[],
        metadata_json={
            "next_step": "resource_setup",
            "workflow_action": "WAIT_FOR_RESOURCE",
            "resource_blocked": True,
        },
    )

    ready_plan = AnalysisResourcePlan(
        profile_id="WES_GRCh38_STANDARD",
        profile_version="1",
        genome_build="GRCh38",
        deployment_profile_type="LABORATORY",
        deployment_profile_version="1",
        status="READY",
        selected=(),
        issues=(),
        plan_hash="ready-plan",
    )
    db = type("_DB", (), {
        "scalars": lambda self, _query: type("_Rows", (), {"all": lambda self: [blocked_step]})(),
        "add": lambda self, _value: None,
        "flush": lambda self: None,
    })()

    original = analysis_module.resolve_analysis_resource_profile
    try:
        analysis_module.resolve_analysis_resource_profile = lambda *args, **kwargs: ready_plan
        result = analysis_module.preflight_analysis_resources(
            db, analysis=analysis, organization_id=uuid4()
        )
    finally:
        analysis_module.resolve_analysis_resource_profile = original

    assert result is ready_plan
    assert analysis.status == "CREATED"
    assert blocked_step.status == "PENDING"
    assert blocked_step.metadata_json["resource_readiness"]["status"] == "READY"
    assert "resource_blocked" not in blocked_step.metadata_json
    assert "next_step" not in blocked_step.metadata_json
    assert "workflow_action" not in blocked_step.metadata_json


def test_preflight_created_workflow_steps_are_idempotent_with_runtime_initialization():
    """Resource preflight may create durable steps before the worker starts.

    The runtime initializer must observe those rows rather than attempting
    duplicate inserts against the analysis_id/step_id uniqueness boundary.
    """
    from uuid import uuid4
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from backend.app.infrastructure.db.models import Analysis, Base, WorkflowStep
    from backend.app.workflows.variant import WORKFLOW_STEPS, ensure_steps

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    analysis_id = uuid4()
    with Session(engine) as db:
        db.add(Analysis(
            id=analysis_id,
            case_id=uuid4(),
            parent_analysis_id=None,
            assay_id=None,
            analysis_type="GERMLINE",
            workflow_id="variant",
            workflow_version="1",
            status="CREATED",
            queue_task_id=None,
            reference_build="GRCh38",
            configuration={},
            started_at=None,
            completed_at=None,
            created_by=None,
        ))
        db.flush()

        # This mirrors the durable rows created by resource preflight.
        for step_id, order in WORKFLOW_STEPS:
            db.add(WorkflowStep(
                id=uuid4(),
                analysis_id=analysis_id,
                step_id=step_id,
                step_order=order,
                status="BLOCKED" if step_id == "normalize" else "PENDING",
                attempt=0,
                input_artifacts=[],
                output_artifacts=[],
                metadata_json={},
            ))
        db.commit()

        ensure_steps(db, analysis_id)

        rows = db.scalars(
            select(WorkflowStep)
            .where(WorkflowStep.analysis_id == analysis_id)
            .order_by(WorkflowStep.step_order)
        ).all()
        assert len(rows) == len(WORKFLOW_STEPS)
        assert rows[1].status == "BLOCKED"

    engine.dispose()

def test_secondary_population_selection_keeps_all_qualified_providers():
    from types import SimpleNamespace
    from backend.app.domain.resource_profile_resolver import _select_all_candidates
    from backend.app.domain.resource_capabilities import POPULATION_SECONDARY

    requirement = SimpleNamespace(
        capability=POPULATION_SECONDARY,
        preferred_providers=("1000GENOMES", "TOPMED", "MIDDLE_EAST", "INTERNAL_LAB_POPULATION"),
        license_required=False,
    )

    def resource(provider, name):
        return SimpleNamespace(
            provider=provider,
            name=name,
            resource_type=POPULATION_SECONDARY,
            genome_build="GRCh38",
            version="1",
            checksum=name,
            id=name,
            license_text=None,
        )

    candidates = [
        (resource("TOPMED", "topmed"), SimpleNamespace()),
        (resource("1000GENOMES", "1000g"), SimpleNamespace()),
        (resource("MIDDLE_EAST", "me"), SimpleNamespace()),
    ]

    selected = _select_all_candidates(
        candidates,
        requirement,
        preferred_providers=requirement.preferred_providers,
    )

    assert [item[0].provider for item in selected] == [
        "1000GENOMES",
        "TOPMED",
        "MIDDLE_EAST",
    ]
    assert len(selected) == 3


def test_laboratory_preflight_rejects_missing_resource_profile(monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4

    import pytest
    import backend.app.application.analysis as analysis_module

    monkeypatch.setattr(
        analysis_module,
        "resolve_resource_deployment_policy",
        lambda *_args, **_kwargs: SimpleNamespace(is_laboratory=True),
    )
    analysis = SimpleNamespace(configuration={}, reference_build="GRCh38")

    with pytest.raises(ValueError, match="RESOURCE_PROFILE_REQUIRED"):
        analysis_module.preflight_analysis_resources(
            object(),
            analysis=analysis,
            organization_id=uuid4(),
        )


def test_trial_preflight_keeps_legacy_no_profile_path(monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4

    import backend.app.application.analysis as analysis_module

    monkeypatch.setattr(
        analysis_module,
        "resolve_resource_deployment_policy",
        lambda *_args, **_kwargs: SimpleNamespace(is_laboratory=False),
    )
    analysis = SimpleNamespace(configuration={}, reference_build="GRCh38")

    assert analysis_module.preflight_analysis_resources(
        object(),
        analysis=analysis,
        organization_id=uuid4(),
    ) is None


def test_preflight_rejects_resource_plan_drift_without_overwriting_persisted_plan(monkeypatch):
    from types import SimpleNamespace
    import pytest
    import backend.app.application.analysis as analysis_module

    persisted = {
        "status": "READY",
        "plan_hash": "previous-qualified-plan",
        "selected": [{"capability": "REFERENCE_PACKAGE", "resource_id": "old-resource"}],
    }
    plan = SimpleNamespace(
        status="READY",
        plan_hash="newly-resolved-plan",
        is_ready=True,
    )
    monkeypatch.setattr(
        analysis_module,
        "resolve_analysis_resource_profile",
        lambda *_args, **_kwargs: plan,
    )
    analysis = SimpleNamespace(
        configuration={
            "resource_profile_id": "WES_GRCh38_STANDARD",
            "resource_plan": persisted,
        },
        reference_build="GRCh38",
        status="CREATED",
    )

    with pytest.raises(ValueError, match="RESOURCE_PLAN_STALE"):
        analysis_module.preflight_analysis_resources(
            object(),
            analysis=analysis,
            organization_id=__import__("uuid").uuid4(),
        )

    assert analysis.configuration["resource_plan"] is persisted
    assert analysis.configuration["resource_plan"]["plan_hash"] == "previous-qualified-plan"
