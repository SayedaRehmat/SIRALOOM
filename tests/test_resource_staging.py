from hashlib import sha256

import pytest

from backend.app.domain.resource_staging import ResourceStagingError, stage_and_verify


class FakeStager:
    def __init__(self, payload: bytes):
        self.payload = payload

    def stage(self, descriptor, destination):
        destination.write_bytes(self.payload)
        return type(
            "Staged",
            (),
            {
                "source": "fake-provider",
                "local_path": str(destination),
                "sha256": "provider-reported",
                "size_bytes": len(self.payload),
                "metadata": {"provider_version": descriptor["version"]},
            },
        )()


def test_stage_and_verify_requires_expected_integrity(tmp_path):
    payload = b"SIRALOOM resource"
    expected = sha256(payload).hexdigest()
    result = stage_and_verify(
        FakeStager(payload),
        {"version": "2026.09"},
        tmp_path / "staged-resource.bin",
        expected,
    )
    assert result.sha256 == expected
    assert result.size_bytes == len(payload)
    assert result.metadata["integrity"] == "SHA-256"


def test_stage_and_verify_rejects_tampered_resource(tmp_path):
    payload = b"original"
    path = tmp_path / "resource.bin"
    with pytest.raises(ResourceStagingError, match="checksum mismatch"):
        stage_and_verify(
            FakeStager(payload),
            {"version": "2026.09"},
            path,
            sha256(b"tampered").hexdigest(),
        )
