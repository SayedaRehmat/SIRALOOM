from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException


def _assert_tenant_denial_precedes_mutation(
    monkeypatch, *, module_name, endpoint_name, accessor_name, mutation_names, args
):
    module = import_module(module_name)

    def deny_foreign_object(*_args, **_kwargs):
        raise HTTPException(status_code=404, detail="Object not found")

    def mutation_must_not_run(*_args, **_kwargs):
        pytest.fail("A tenant-scoped mutation ran after the access guard denied the object")

    monkeypatch.setattr(module, accessor_name, deny_foreign_object)
    for mutation_name in mutation_names:
        monkeypatch.setattr(module, mutation_name, mutation_must_not_run)

    with pytest.raises(HTTPException) as exc:
        getattr(module, endpoint_name)(*args)
    assert exc.value.status_code == 404


@pytest.mark.parametrize(
    ("endpoint_name", "mutation_names", "payload"),
    [
        (
            "propose_manual",
            ("propose_manual_classification",),
            SimpleNamespace(result="PATHOGENIC", reason="test", evidence_ids=[]),
        ),
        ("start", ("start_review",), None),
        (
            "review",
            ("review_criterion",),
            SimpleNamespace(
                decision="ACCEPT", strength=None, reason="test",
                evidence_ids=[], expected_version=1,
            ),
        ),
        (
            "approve",
            ("approve_classification",),
            SimpleNamespace(expected_version=1, reason="test"),
        ),
        (
            "more_evidence",
            ("request_more_evidence",),
            SimpleNamespace(expected_version=1, reason="test"),
        ),
    ],
)
def test_review_mutations_stop_before_service_for_foreign_analysis(
    monkeypatch, endpoint_name, mutation_names, payload
):
    module_name = "backend.app.api.v1.review"
    analysis_id, variant_id = uuid4(), uuid4()
    principal = SimpleNamespace(user_id=uuid4(), organization_id=uuid4(), role="reviewer")
    db = object()
    if endpoint_name == "start":
        args = (analysis_id, variant_id, db, principal)
    elif endpoint_name == "review":
        args = (analysis_id, variant_id, "PM2", payload, db, principal)
    else:
        args = (analysis_id, variant_id, payload, db, principal)
    _assert_tenant_denial_precedes_mutation(
        monkeypatch,
        module_name=module_name,
        endpoint_name=endpoint_name,
        accessor_name="get_accessible_analysis",
        mutation_names=mutation_names,
        args=args,
    )


@pytest.mark.parametrize(
    ("endpoint_name", "accessor_name", "mutation_names", "payload"),
    [
        (
            "create_report", "get_accessible_analysis", ("build_report_content",),
            SimpleNamespace(language="en", report_type="CLINICAL", include_full_evidence=False),
        ),
        (
            "finalize", "get_accessible_report", ("finalize_report",),
            SimpleNamespace(reason="test"),
        ),
        (
            "evaluate_reportability", "get_accessible_analysis", ("evaluate_analysis",), None,
        ),
    ],
)
def test_report_mutations_stop_before_service_for_foreign_object(
    monkeypatch, endpoint_name, accessor_name, mutation_names, payload
):
    module_name = "backend.app.api.v1.reports"
    object_id = uuid4()
    principal = SimpleNamespace(user_id=uuid4(), organization_id=uuid4(), role="organization_admin")
    db = object()
    if endpoint_name == "create_report":
        args = (object_id, payload, db, principal)
    elif endpoint_name == "finalize":
        args = (object_id, payload, db, principal)
    else:
        args = (object_id, db, principal)
    _assert_tenant_denial_precedes_mutation(
        monkeypatch,
        module_name=module_name,
        endpoint_name=endpoint_name,
        accessor_name=accessor_name,
        mutation_names=mutation_names,
        args=args,
    )


def test_reanalysis_request_stops_before_child_creation_for_foreign_parent(monkeypatch):
    module_name = "backend.app.api.v1.reanalysis"
    _assert_tenant_denial_precedes_mutation(
        monkeypatch,
        module_name=module_name,
        endpoint_name="request_reanalysis",
        accessor_name="get_accessible_analysis",
        mutation_names=("create_reanalysis", "preflight_analysis_resources"),
        args=(
            uuid4(),
            SimpleNamespace(reason="test"),
            object(),
            SimpleNamespace(user_id=uuid4(), organization_id=uuid4(), role="organization_admin"),
        ),
    )
