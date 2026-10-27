import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.mark.skipif(os.name != "nt", reason="Windows drive file URI behavior")
def test_windows_drive_file_uri_does_not_retain_url_leading_slash():
    from backend.app.domain.local_uri import local_path_from_uri

    local_path = local_path_from_uri("file:///C:/Lab%20Data/input.vcf")
    assert local_path is not None
    assert local_path.drive == "C:"
    assert local_path.name == "input.vcf"
    assert local_path.parent.name == "Lab Data"


def test_population_query_checks_analysis_tenant_before_reading_rows(monkeypatch):
    from backend.app.api.v1 import populations

    analysis_id = uuid4()
    principal = SimpleNamespace(organization_id=uuid4(), role="read_only")

    def deny_foreign_analysis(*_args, **_kwargs):
        raise HTTPException(status_code=404, detail="Analysis not found")

    class ForbiddenDB:
        def scalars(self, *_args, **_kwargs):
            pytest.fail("Population rows were read before tenant authorization")

    monkeypatch.setattr(populations, "get_accessible_analysis", deny_foreign_analysis)
    with pytest.raises(HTTPException) as exc:
        populations.query(
            SimpleNamespace(analysis_id=analysis_id, variant_ids=[], requested_populations=[]),
            ForbiddenDB(),
            principal,
        )
    assert exc.value.status_code == 404


def test_population_query_checks_variant_membership_before_reading_rows(monkeypatch):
    from backend.app.api.v1 import populations

    analysis_id, variant_id = uuid4(), uuid4()
    analysis = SimpleNamespace(id=analysis_id)
    principal = SimpleNamespace(organization_id=uuid4(), role="read_only")

    def reject_nonmember(*_args):
        raise HTTPException(status_code=404, detail="Variant is not part of this analysis")

    class ForbiddenDB:
        def scalars(self, *_args, **_kwargs):
            pytest.fail("Population observations were read before variant membership validation")

    monkeypatch.setattr(populations, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(populations, "get_analysis_variant", reject_nonmember)
    with pytest.raises(HTTPException) as exc:
        populations.query(
            SimpleNamespace(
                analysis_id=analysis_id,
                variant_ids=[variant_id],
                requested_populations=["GLOBAL"],
            ),
            ForbiddenDB(),
            principal,
        )
    assert exc.value.status_code == 404


def test_population_query_rejects_unbounded_variant_lists():
    from pydantic import ValidationError

    from backend.app.domain.schemas import PopulationQueryRequest

    with pytest.raises(ValidationError):
        PopulationQueryRequest(
            analysis_id=uuid4(),
            variant_ids=[uuid4() for _ in range(501)],
        )


def test_default_population_query_includes_joint_and_cohort_specific_gnomad_codes():
    from backend.app.domain.schemas import PopulationQueryRequest

    request = PopulationQueryRequest(analysis_id=uuid4(), variant_ids=[uuid4()])
    assert {"GLOBAL", "MID", "GLOBAL_EXOMES", "GLOBAL_GENOMES", "MID_EXOMES", "MID_GENOMES"} <= set(request.requested_populations)


def test_artifact_download_checks_tenant_before_resolving_storage(monkeypatch):
    from backend.app.api.v1 import artifacts

    def deny_foreign_artifact(*_args, **_kwargs):
        raise HTTPException(status_code=404, detail="Artifact not found")

    def storage_must_not_be_resolved(*_args, **_kwargs):
        pytest.fail("Storage was resolved before artifact tenant authorization")

    monkeypatch.setattr(artifacts, "get_accessible_artifact", deny_foreign_artifact)
    monkeypatch.setattr(artifacts, "artifact_store_for_uri", storage_must_not_be_resolved)
    with pytest.raises(HTTPException) as exc:
        artifacts.download_artifact(str(uuid4()), object(), SimpleNamespace(organization_id=uuid4()))
    assert exc.value.status_code == 404


def test_evidence_read_checks_analysis_tenant_before_returning_record(monkeypatch):
    from backend.app.api.v1 import evidence

    row = SimpleNamespace(analysis_id=uuid4())
    principal = SimpleNamespace(organization_id=uuid4())

    class DB:
        def get(self, *_args):
            return row

    def deny_foreign_analysis(*_args, **_kwargs):
        raise HTTPException(status_code=404, detail="Analysis not found")

    monkeypatch.setattr(evidence, "get_accessible_analysis", deny_foreign_analysis)
    with pytest.raises(HTTPException) as exc:
        evidence.get_evidence(uuid4(), DB(), principal)
    assert exc.value.status_code == 404


@pytest.mark.parametrize("role", ["read_only", "reviewer", "bioinformatician"])
def test_population_resource_catalog_is_scoped_to_tenant_for_non_platform_users(role):
    from backend.app.api.v1 import populations

    organization_id = uuid4()
    principal = SimpleNamespace(organization_id=organization_id, role=role)
    observed = {}

    class Result:
        def all(self):
            return []

    class DB:
        def scalars(self, statement):
            observed["sql"] = str(statement.compile(compile_kwargs={"literal_binds": True}))
            return Result()

    assert populations.resources(DB(), principal) == []
    assert "resources.organization_id IS NULL" in observed["sql"]
    assert organization_id.hex in observed["sql"]


def test_population_resource_catalog_denies_unknown_role():
    from backend.app.api.v1 import populations

    with pytest.raises(HTTPException) as exc:
        populations.resources(object(), SimpleNamespace(role="unknown", organization_id=uuid4()))
    assert exc.value.status_code == 403


def test_population_replay_lookup_requires_exact_succeeded_execution():
    from backend.app.infrastructure.db.base import Base
    from backend.app.infrastructure.db.models import ResourceExecutionRecord
    from backend.app.workflows.variant import _succeeded_population_execution

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    analysis_id, other_analysis_id = uuid4(), uuid4()
    resource_id, other_resource_id = uuid4(), uuid4()
    qualification_id = uuid4()

    def execution(*, analysis, resource, batch, status):
        return ResourceExecutionRecord(
            id=uuid4(),
            analysis_id=analysis,
            step_id="population",
            attempt=1,
            batch_key=batch,
            resource_id=resource,
            qualification_id=qualification_id,
            qualification_version="qualification-v1",
            resource_version="release-v1",
            provider_id="fixture",
            provider_version="fixture-v1",
            access_method="API",
            endpoint="https://fixture.invalid",
            location="https://fixture.invalid",
            dataset=None,
            contract_hash="a" * 64,
            contract_json={},
            status=status,
            metadata_json={},
        )

    with Session(engine) as db:
        db.add_all([
            execution(analysis=analysis_id, resource=resource_id, batch="1:100:A:G", status="SUCCEEDED"),
            execution(analysis=analysis_id, resource=resource_id, batch="1:101:A:G", status="FAILED"),
            execution(analysis=other_analysis_id, resource=resource_id, batch="1:102:A:G", status="SUCCEEDED"),
            execution(analysis=analysis_id, resource=other_resource_id, batch="1:103:A:G", status="SUCCEEDED"),
        ])
        db.commit()

        assert _succeeded_population_execution(
            db, analysis_id=analysis_id, resource_id=resource_id, batch_key="1:100:A:G"
        )
        assert _succeeded_population_execution(
            db, analysis_id=analysis_id, resource_id=resource_id, batch_key="1:101:A:G"
        ) is None
        assert _succeeded_population_execution(
            db, analysis_id=analysis_id, resource_id=resource_id, batch_key="1:102:A:G"
        ) is None
        assert _succeeded_population_execution(
            db, analysis_id=analysis_id, resource_id=resource_id, batch_key="1:103:A:G"
        ) is None
