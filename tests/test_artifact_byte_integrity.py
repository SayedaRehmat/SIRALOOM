from __future__ import annotations

import hashlib

import pytest

from backend.app.domain.artifact_integrity import ArtifactIntegrityError, verify_artifact_file


def test_integrity_verification_rejects_final_symlink(tmp_path):
    target = tmp_path / "actual.vcf"
    target.write_bytes(b"clinical evidence")
    link = tmp_path / "artifact.vcf"
    link.symlink_to(target)
    with pytest.raises(ArtifactIntegrityError, match="symbolic link"):
        verify_artifact_file(link, sha256=hashlib.sha256(b"clinical evidence").hexdigest(), size_bytes=17)


def test_integrity_verification_rejects_symlinked_parent(tmp_path):
    real_directory = tmp_path / "real"
    real_directory.mkdir()
    (real_directory / "artifact.vcf").write_bytes(b"clinical evidence")
    linked_directory = tmp_path / "linked"
    linked_directory.symlink_to(real_directory, target_is_directory=True)
    with pytest.raises(ArtifactIntegrityError, match="symbolic link"):
        verify_artifact_file(linked_directory / "artifact.vcf", sha256=hashlib.sha256(b"clinical evidence").hexdigest(), size_bytes=17)


def test_integrity_verification_rejects_non_regular_file(tmp_path):
    directory = tmp_path / "artifact.vcf"
    directory.mkdir()
    with pytest.raises(ArtifactIntegrityError, match="regular file"):
        verify_artifact_file(directory, sha256="0" * 64, size_bytes=0)
