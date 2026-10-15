"""Regression tests for the controlled parent/child reanalysis comparison CLI.

These tests exercise CLI argument handling, database-session lifecycle, JSON output,
and the documented exit-code contract without pretending to validate real lab analyses.
"""
import importlib
import json
import sys
from contextlib import contextmanager
from uuid import uuid4

import pytest


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
