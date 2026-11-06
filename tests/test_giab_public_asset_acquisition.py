from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path("scripts/validation/acquire_giab_public_assets.py")


def _module():
    spec = importlib.util.spec_from_file_location("acquire_giab_public_assets", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _response(payload: bytes):
    class Response:
        status = 200
        def __init__(self):
            self.remaining = payload
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def read(self, size=-1):
            chunk, self.remaining = self.remaining[:size], self.remaining[size:]
            return chunk
    return Response()


def test_download_verified_publishes_only_after_official_md5_match(tmp_path):
    module = _module()
    payload = b"pinned GIAB test bytes"
    expected = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    destination = tmp_path / "asset.bin"
    with patch.object(module.urllib.request, "urlopen", return_value=_response(payload)):
        result = module.download_verified("https://example.invalid/asset.bin", destination, expected)
    assert destination.read_bytes() == payload
    assert result["official_md5_verified"] is True
    assert result["sha256"] == hashlib.sha256(payload).hexdigest()


def test_download_verified_rejects_checksum_mismatch_without_publishing(tmp_path):
    module = _module()
    destination = tmp_path / "asset.bin"
    with patch.object(module.urllib.request, "urlopen", return_value=_response(b"changed upstream bytes")):
        try:
            module.download_verified("https://example.invalid/asset.bin", destination, "0" * 32)
        except module.AcquisitionError as exc:
            assert "MD5 mismatch" in str(exc)
        else:
            raise AssertionError("checksum mismatch must fail closed")
    assert not destination.exists()
    assert not list(tmp_path.glob(".asset.bin.*"))


def test_download_verified_never_overwrites_existing_asset(tmp_path):
    module = _module()
    destination = tmp_path / "asset.bin"
    destination.write_bytes(b"preserved")
    try:
        module.download_verified("https://example.invalid/asset.bin", destination, "0" * 32)
    except module.AcquisitionError as exc:
        assert "Refusing to overwrite" in str(exc)
    else:
        raise AssertionError("existing evidence must not be overwritten")
    assert destination.read_bytes() == b"preserved"


def test_fai_generation_records_uncompressed_offsets_and_contig_geometry(tmp_path):
    module = _module()
    fasta = tmp_path / "reference.fa"
    fasta.write_bytes(b">chr1 description\nACGT\nTGCA\n>chr2\nAAAA\n")
    fai = tmp_path / "reference.fa.fai"
    count = module._write_fai_from_plain_fasta(fasta, fai)
    assert count == 2
    assert fai.read_text(encoding="utf-8").splitlines() == [
        "chr1\t8\t18\t4\t5",
        "chr2\t4\t34\t4\t5",
    ]
