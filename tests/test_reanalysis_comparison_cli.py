"""Regression tests for the controlled parent/child reanalysis comparison CLI.

These tests exercise CLI argument handling, database-session lifecycle, JSON output,
and the documented exit-code contract without pretending to validate real lab analyses.
"""
import importlib
import json
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AnalysisResourceSnapshot,
    Case,
    Classification,
    Organization,
    User,
    Variant,
)


@pytest.mark.parametrize(
    ("decision", "expected_exit"),
    [
        ("MATCH", 0),
        ("MISMATCH", 1),
        ("INELIGIBLE_UNPINNED_RESOURCES", 2),
    ],
)
def test_comparison_cli_reports_decision_and_exit_code(
    monkeypatch, capsys, decision, expected_exit
):
    cli = importlib.import_module("scripts.compare_reanalysis_outputs")
    parent_id, child_id = uuid4(), uuid4()
    expected = {
        "decision": decision,
        "parent_analysis_id": str(parent_id),
        "child_analysis_id": str(child_id),
        "details": {"fixture": True},
    }
    calls = {}

    class FakeSession:
        def __enter__(self):
            calls["session_entered"] = True
            return self

        def __exit__(self, exc_type, exc, traceback):
            calls["session_exited"] = True
            return False

    @contextmanager
    def fake_session_local():
        session = FakeSession()
        try:
            yield session
        finally:
            calls["session_exited"] = True

    def fake_compare(db, *, parent_analysis_id, child_analysis_id):
        calls["db"] = db
        calls["parent_analysis_id"] = parent_analysis_id
        calls["child_analysis_id"] = child_analysis_id
        return expected

    monkeypatch.setattr(cli, "SessionLocal", fake_session_local)
    monkeypatch.setattr(cli, "compare_reanalysis_outputs", fake_compare)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compare_reanalysis_outputs.py",
            "--parent-analysis-id",
            str(parent_id),
            "--child-analysis-id",
            str(child_id),
        ],
    )

    assert cli.main() == expected_exit
    captured = capsys.readouterr()
    assert json.loads(captured.out) == expected
    assert captured.err == ""
    assert calls["session_exited"] is True
    assert calls["parent_analysis_id"] == parent_id
    assert calls["child_analysis_id"] == child_id


def test_comparison_cli_requires_both_analysis_ids(monkeypatch):
    cli = importlib.import_module("scripts.compare_reanalysis_outputs")
    monkeypatch.setattr(sys, "argv", ["compare_reanalysis_outputs.py"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2


@pytest.mark.parametrize(
    ("decision", "parent_result", "child_result", "checksum", "expected_exit"),
    [
        ("MATCH", "LIKELY_PATHOGENIC", "LIKELY_PATHOGENIC", "a" * 64, 0),
        ("MISMATCH", "LIKELY_PATHOGENIC", "UNCERTAIN_SIGNIFICANCE", "a" * 64, 1),
        ("INELIGIBLE_UNPINNED_RESOURCES", "LIKELY_PATHOGENIC", "LIKELY_PATHOGENIC", None, 2),
    ],
)
def test_comparison_cli_uses_real_parent_child_database_rows(
    monkeypatch, capsys, tmp_path, decision, parent_result, child_result, checksum, expected_exit
):
    cli = importlib.import_module("scripts.compare_reanalysis_outputs")
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / (decision + '.db')}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, parent_id, child_id, variant_id = (
        uuid4() for _ in range(6)
    )
    now = datetime.now(UTC)
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name="CLI Reproducibility Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="CLI Reproducibility Test",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"CLI-REPRO-{case_id}",
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.flush()
            db.add(Variant(
                id=variant_id,
                genome_build="GRCh38",
                chromosome="1",
                position=12345,
                reference="A",
                alternate="G",
                normalization_status="NORMALIZED",
                canonical_key="GRCh38:1:12345:A:G",
                identifiers={},
            ))
            db.flush()
            for analysis_id, parent_analysis_id, version, result in (
                (parent_id, None, 1, parent_result),
                (child_id, parent_id, 2, child_result),
            ):
                db.add(Analysis(
                    id=analysis_id,
                    case_id=case_id,
                    parent_analysis_id=parent_analysis_id,
                    assay_id=None,
                    analysis_type="VARIANT_INTERPRETATION",
                    workflow_id="variant-v1",
                    workflow_version=f"workflow-{version}",
                    status="SUCCEEDED",
                    queue_task_id=None,
                    reference_build="GRCh38",
                    configuration={},
                    started_at=now,
                    completed_at=now,
                    created_by=user_id,
                    analysis_version=version,
                ))
                db.add(AnalysisResourceSnapshot(
                    id=uuid4(),
                    analysis_id=analysis_id,
                    resource_id=None,
                    resource_kind="ANNOTATION",
                    resource_name="fixture-annotation",
                    provider="fixture-provider",
                    version="release-v1",
                    checksum=checksum,
                    genome_build="GRCh38",
                    metadata_json={"fixture": "pinned"},
                ))
                db.add(Classification(
                    id=uuid4(),
                    variant_id=variant_id,
                    analysis_id=analysis_id,
                    framework_name="ACMG/AMP",
                    framework_version="2015",
                    specification_provider="ClinGen",
                    specification_id="fixture-spec",
                    specification_version="1.0",
                    result=result,
                    criterion_ids=["PM2"],
                    metadata_json={"evidence_model": "fixture-v1"},
                    state="PROPOSED",
                    review_status="PENDING",
                    version=1,
                    review_version=0,
                ))
            db.commit()

        monkeypatch.setattr(cli, "SessionLocal", lambda: Session(engine))
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "compare_reanalysis_outputs.py",
                "--parent-analysis-id",
                str(parent_id),
                "--child-analysis-id",
                str(child_id),
            ],
        )

        assert cli.main() == expected_exit
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["decision"] == decision
        assert payload["parent"]["analysis_id"] == str(parent_id)
        assert payload["child"]["analysis_id"] == str(child_id)
        assert captured.err == ""
    finally:
        engine.dispose()
