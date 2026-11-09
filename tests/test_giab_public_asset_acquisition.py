from __future__ import annotations

import hashlib
import importlib.util
import io
import json

import pytest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validation" / "acquire_giab_public_assets.py"


def _load_acquirer():
    spec = importlib.util.spec_from_file_location("acquire_giab_public_assets", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeResponse(io.BytesIO):
    status = 200

    def __init__(self, payload: bytes):
        super().__init__(payload)
        self.headers = {
            "Content-Length": str(len(payload)),
            "Content-Type": "application/gzip",
        }

    def geturl(self) -> str:
        return "https://example.test/reference.fa.gz"


def test_download_verified_records_checksum_mismatch_diagnostics(tmp_path, monkeypatch):
    module = _load_acquirer()
    payload = b"unexpected public asset bytes"
    destination = tmp_path / "reference.fa.gz"
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda _request, timeout: _FakeResponse(payload),
    )

    with pytest.raises(module.AcquisitionError) as exc:
        module.download_verified(
            "https://example.test/reference.fa.gz",
            destination,
            "0" * 32,
        )

    details = exc.value.details
    assert details["stage"] == "asset_checksum_verification"
    assert details["expected_md5"] == "0" * 32
    assert details["observed_md5"] == hashlib.md5(payload, usedforsecurity=False).hexdigest()
    assert details["observed_sha256"] == hashlib.sha256(payload).hexdigest()
    assert details["size_bytes"] == len(payload)
    assert details["response"]["http_status"] == 200
    assert details["response"]["content_length"] == str(len(payload))
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_write_failure_provenance_preserves_transfer_diagnostics(tmp_path):
    module = _load_acquirer()
    error = module.AcquisitionError(
        "Official MD5 mismatch",
        details={
            "stage": "asset_checksum_verification",
            "expected_md5": "0" * 32,
            "observed_md5": "1" * 32,
            "size_bytes": 123,
        },
    )
    output = tmp_path / "acquisition-failure.json"

    module.write_failure_provenance(
        output,
        build="GRCh37",
        dataset="NIST_GIAB_HG001_NISTv4.2.1",
        failed_stage="asset_download_and_checksum_verification",
        failed_asset="reference_source_fasta",
        error=error,
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert output.read_bytes().endswith(b"\n")
    assert report["status"] == "FAILED"
    assert report["reference_build"] == "GRCh37"
    assert report["failed_stage"] == "asset_download_and_checksum_verification"
    assert report["failed_asset"] == "reference_source_fasta"
    assert report["details"]["observed_md5"] == "1" * 32
    assert report["details"]["size_bytes"] == 123
