from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.reporting import finalization


def _fixture(tmp_path, payload=b"source evidence"):
    artifact_id = uuid4()
    case_id = uuid4()
    source = tmp_path / "source.vcf"
    source.write_bytes(payload)
    artifact = SimpleNamespace(
        id=artifact_id,
        case_id=case_id,
        storage_uri=source.as_uri(),
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        artifact_type="VCF",
        filename="source.vcf",
    )
    report = SimpleNamespace(
        case_id=case_id,
        artifact_id=None,
        content_json={
            "artifact_manifest": [{
                "artifact_id": str(artifact_id),
                "type": "VCF",
                "filename": "source.vcf",
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
            }]
        },
    )

    class DB:
        def get(self, model, identity):
            if identity == case_id:
                return SimpleNamespace(organization_id=uuid4())
            if identity == artifact_id:
                return artifact
            return None

    class Store:
        def local_path(self, uri):
            assert uri == artifact.storage_uri
            return source

    return report, DB(), Store(), source


def test_report_signout_source_manifest_reverifies_artifact_bytes(monkeypatch, tmp_path):
    report, db, store, _source = _fixture(tmp_path)
    monkeypatch.setattr(finalization, "artifact_store_for_uri", lambda *args, **kwargs: store)

    finalization._verify_report_artifact_bytes(db, report)


def test_report_signout_rejects_tampered_source_artifact(monkeypatch, tmp_path):
    report, db, store, source = _fixture(tmp_path)
    monkeypatch.setattr(finalization, "artifact_store_for_uri", lambda *args, **kwargs: store)
    source.write_bytes(b"tampered evidence")

    with pytest.raises(finalization.ReportFinalizationError, match="failed byte-integrity"):
        finalization._verify_report_artifact_bytes(db, report)


def test_report_signout_rejects_manifest_digest_substitution(monkeypatch, tmp_path):
    report, db, store, _source = _fixture(tmp_path)
    monkeypatch.setattr(finalization, "artifact_store_for_uri", lambda *args, **kwargs: store)
    report.content_json["artifact_manifest"][0]["sha256"] = "0" * 64

    with pytest.raises(finalization.ReportFinalizationError, match="does not match its manifest"):
        finalization._verify_report_artifact_bytes(db, report)
