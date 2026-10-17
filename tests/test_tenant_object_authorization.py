from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.auth.authorization import (
    get_accessible_analysis,
    get_accessible_artifact,
    get_accessible_case,
    get_accessible_report,
)
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.models import Analysis, Artifact, Case, Report


class TenantObjectSession:
    def __init__(self, rows):
        self.rows = rows

    def get(self, model, object_id):
        value = self.rows.get(model)
        if isinstance(value, dict):
            return value.get(object_id)
        return value

    def scalars(self, _statement):
        reports = self.rows.get(Report, [])
        if not isinstance(reports, list):
            reports = [reports]
        return SimpleNamespace(all=lambda: reports)


@pytest.mark.parametrize("object_kind", ["case", "analysis", "artifact", "report"])
@pytest.mark.parametrize("same_tenant", [True, False])
def test_shared_object_accessors_enforce_case_tenant_boundary(object_kind, same_tenant):
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    case_id = uuid4()
    object_id = uuid4()
    case = SimpleNamespace(id=case_id, organization_id=tenant_id if same_tenant else other_tenant_id)
    analysis = SimpleNamespace(id=object_id, case_id=case_id)
    artifact = SimpleNamespace(
        id=object_id, case_id=case_id, analysis_id=object_id,
        artifact_type="REPORT_PDF", validation_status="VALID",
        metadata_json={"report_id": str(object_id), "report_version": 1, "report_state": "DRAFT"},
    )
    report = SimpleNamespace(
        id=object_id, case_id=case_id, analysis_id=object_id,
        artifact_id=object_id, signed_artifact_id=None, signed_sha256=None,
        report_version=1, status="DRAFT",
    )
    db = TenantObjectSession({
        Case: case,
        Analysis: analysis,
        Artifact: artifact,
        Report: report,
    })
    principal = Principal(
        user_id=uuid4(), organization_id=tenant_id,
        role="read_only", subject="verified-subject",
    )
    accessors = {
        "case": (get_accessible_case, case),
        "analysis": (get_accessible_analysis, analysis),
        "artifact": (get_accessible_artifact, artifact),
        "report": (get_accessible_report, report),
    }
    accessor, expected = accessors[object_kind]

    if same_tenant:
        assert accessor(object_id, db=db, principal=principal) is expected
    else:
        with pytest.raises(HTTPException) as error:
            accessor(object_id, db=db, principal=principal)
        assert error.value.status_code == 404


def test_report_access_rejects_analysis_from_another_case_in_same_tenant():
    tenant_id = uuid4()
    report_case_id, analysis_case_id = uuid4(), uuid4()
    report_id, analysis_id = uuid4(), uuid4()
    db = TenantObjectSession({
        Report: SimpleNamespace(id=report_id, case_id=report_case_id, analysis_id=analysis_id),
        Case: SimpleNamespace(id=report_case_id, organization_id=tenant_id),
        Analysis: SimpleNamespace(id=analysis_id, case_id=analysis_case_id),
    })
    principal = Principal(
        user_id=uuid4(), organization_id=tenant_id,
        role="read_only", subject="verified-subject",
    )

    with pytest.raises(HTTPException) as error:
        get_accessible_report(report_id, db=db, principal=principal)

    assert error.value.status_code == 404


@pytest.mark.parametrize("broken_link", ["case", "analysis", "type", "report_id", "version", "state"])
def test_report_access_rejects_misbound_draft_artifact(broken_link):
    tenant_id, case_id, analysis_id, report_id, artifact_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4(),
    )
    report = SimpleNamespace(
        id=report_id, case_id=case_id, analysis_id=analysis_id,
        artifact_id=artifact_id, status="DRAFT", report_version=2,
    )
    artifact = SimpleNamespace(
        id=artifact_id,
        case_id=uuid4() if broken_link == "case" else case_id,
        analysis_id=uuid4() if broken_link == "analysis" else analysis_id,
        artifact_type="OTHER" if broken_link == "type" else "REPORT_PDF",
        validation_status="VALID",
        metadata_json={
            "report_state": "FINAL" if broken_link == "state" else "DRAFT",
            "report_id": str(uuid4()) if broken_link == "report_id" else str(report_id),
            "report_version": 3 if broken_link == "version" else 2,
        },
    )
    db = TenantObjectSession({
        Report: report,
        Artifact: artifact,
        Case: SimpleNamespace(id=case_id, organization_id=tenant_id),
        Analysis: SimpleNamespace(id=analysis_id, case_id=case_id),
    })
    principal = Principal(
        user_id=uuid4(), organization_id=tenant_id,
        role="read_only", subject="verified-subject",
    )

    with pytest.raises(HTTPException) as error:
        get_accessible_report(report_id, db=db, principal=principal)

    assert error.value.status_code == 404


def test_report_access_rejects_missing_draft_artifact():
    tenant_id, case_id, analysis_id, report_id = uuid4(), uuid4(), uuid4(), uuid4()
    db = TenantObjectSession({
        Report: SimpleNamespace(
            id=report_id, case_id=case_id, analysis_id=analysis_id,
            artifact_id=None, status="DRAFT", report_version=1,
        ),
        Case: SimpleNamespace(id=case_id, organization_id=tenant_id),
        Analysis: SimpleNamespace(id=analysis_id, case_id=case_id),
    })
    principal = Principal(
        user_id=uuid4(), organization_id=tenant_id,
        role="read_only", subject="verified-subject",
    )

    with pytest.raises(HTTPException) as error:
        get_accessible_report(report_id, db=db, principal=principal)

    assert error.value.status_code == 404


def test_artifact_access_rejects_analysis_from_another_case_in_same_tenant():
    tenant_id = uuid4()
    artifact_case_id, analysis_case_id = uuid4(), uuid4()
    artifact_id, analysis_id = uuid4(), uuid4()
    db = TenantObjectSession({
        Artifact: SimpleNamespace(id=artifact_id, case_id=artifact_case_id, analysis_id=analysis_id),
        Case: SimpleNamespace(id=artifact_case_id, organization_id=tenant_id),
        Analysis: SimpleNamespace(id=analysis_id, case_id=analysis_case_id),
    })
    principal = Principal(
        user_id=uuid4(), organization_id=tenant_id,
        role="read_only", subject="verified-subject",
    )

    with pytest.raises(HTTPException) as error:
        get_accessible_artifact(artifact_id, db=db, principal=principal)

    assert error.value.status_code == 404


@pytest.mark.parametrize(
    "broken_link",
    ["draft_other_artifact", "signed_other_artifact", "signed_hash", "version", "report_missing"],
)
def test_report_pdf_artifact_access_requires_owning_report_lineage(broken_link):
    tenant_id, case_id, analysis_id, report_id, artifact_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4(),
    )
    is_signed = broken_link != "draft_other_artifact"
    report = SimpleNamespace(
        id=report_id,
        case_id=case_id,
        analysis_id=analysis_id,
        report_version=2,
        status="FINAL" if is_signed else "DRAFT",
        artifact_id=uuid4() if broken_link == "draft_other_artifact" else artifact_id,
        signed_artifact_id=uuid4() if broken_link == "signed_other_artifact" else artifact_id if is_signed else None,
        signed_sha256="b" * 64,
    )
    metadata = {
        "report_id": str(uuid4()) if broken_link == "report_missing" else str(report_id),
        "report_version": 3 if broken_link == "version" else 2,
        "report_state": "FINAL" if is_signed else "DRAFT",
    }
    if is_signed:
        metadata["signed"] = True
    artifact = SimpleNamespace(
        id=artifact_id,
        case_id=case_id,
        analysis_id=analysis_id,
        artifact_type="REPORT_PDF",
        metadata_json=metadata,
        sha256="c" * 64 if broken_link == "signed_hash" else "b" * 64,
    )
    db = TenantObjectSession({
        Artifact: artifact,
        Report: {report_id: report} if broken_link == "report_missing" else report,
        Case: SimpleNamespace(id=case_id, organization_id=tenant_id),
        Analysis: SimpleNamespace(id=analysis_id, case_id=case_id),
    })
    principal = Principal(
        user_id=uuid4(), organization_id=tenant_id,
        role="read_only", subject="verified-subject",
    )

    with pytest.raises(HTTPException) as error:
        get_accessible_artifact(artifact_id, db=db, principal=principal)

    assert error.value.status_code == 404


def test_report_pdf_without_metadata_requires_unique_persisted_report_link():
    tenant_id, case_id, analysis_id, report_id, artifact_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4(),
    )
    artifact = SimpleNamespace(
        id=artifact_id, case_id=case_id, analysis_id=analysis_id,
        artifact_type="REPORT_PDF", metadata_json={}, sha256="a" * 64,
    )
    report = SimpleNamespace(
        id=report_id, case_id=case_id, analysis_id=analysis_id,
        report_version=1, status="DRAFT", artifact_id=artifact_id,
        signed_artifact_id=None, signed_sha256=None,
    )
    db = TenantObjectSession({
        Artifact: artifact,
        Report: [report],
        Case: SimpleNamespace(id=case_id, organization_id=tenant_id),
        Analysis: SimpleNamespace(id=analysis_id, case_id=case_id),
    })
    principal = Principal(
        user_id=uuid4(), organization_id=tenant_id,
        role="read_only", subject="verified-subject",
    )

    assert get_accessible_artifact(artifact_id, db=db, principal=principal) is artifact

    db.rows[Report] = []
    with pytest.raises(HTTPException) as error:
        get_accessible_artifact(artifact_id, db=db, principal=principal)
    assert error.value.status_code == 404

    db.rows[Report] = [report, SimpleNamespace(**{**vars(report), "id": uuid4()})]
    with pytest.raises(HTTPException) as error:
        get_accessible_artifact(artifact_id, db=db, principal=principal)
    assert error.value.status_code == 404


@pytest.mark.parametrize("status", ["FINAL", "SUPERSEDED"])
def test_report_access_rejects_released_report_without_valid_signed_artifact(status):
    tenant_id, case_id, analysis_id, report_id = uuid4(), uuid4(), uuid4(), uuid4()
    db = TenantObjectSession({
        Report: SimpleNamespace(
            id=report_id, case_id=case_id, analysis_id=analysis_id,
            status=status, signed_artifact_id=None, signed_sha256=None,
        ),
        Case: SimpleNamespace(id=case_id, organization_id=tenant_id),
        Analysis: SimpleNamespace(id=analysis_id, case_id=case_id),
    })
    principal = Principal(
        user_id=uuid4(), organization_id=tenant_id,
        role="read_only", subject="verified-subject",
    )

    with pytest.raises(HTTPException) as error:
        get_accessible_report(report_id, db=db, principal=principal)

    assert error.value.status_code == 404


def test_report_access_accepts_final_report_with_matching_signed_artifact():
    tenant_id, case_id, analysis_id, report_id, artifact_id, draft_artifact_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4(),
    )
    report = SimpleNamespace(
        id=report_id, case_id=case_id, analysis_id=analysis_id, status="FINAL",
        artifact_id=draft_artifact_id, signed_artifact_id=artifact_id,
        signed_sha256="d" * 64, report_version=3,
    )
    artifact = SimpleNamespace(
        id=artifact_id, case_id=case_id, analysis_id=analysis_id,
        artifact_type="REPORT_PDF", validation_status="VALID", sha256="d" * 64,
        metadata_json={"report_id": str(report_id), "report_version": 3, "signed": True},
    )
    draft_artifact = SimpleNamespace(
        id=draft_artifact_id, case_id=case_id, analysis_id=analysis_id,
        artifact_type="REPORT_PDF", validation_status="VALID",
        metadata_json={"report_id": str(report_id), "report_version": 3, "report_state": "DRAFT"},
    )
    db = TenantObjectSession({
        Report: report,
        Artifact: {artifact_id: artifact, draft_artifact_id: draft_artifact},
        Case: SimpleNamespace(id=case_id, organization_id=tenant_id),
        Analysis: SimpleNamespace(id=analysis_id, case_id=case_id),
    })
    principal = Principal(
        user_id=uuid4(), organization_id=tenant_id,
        role="read_only", subject="verified-subject",
    )

    assert get_accessible_report(report_id, db=db, principal=principal) is report
