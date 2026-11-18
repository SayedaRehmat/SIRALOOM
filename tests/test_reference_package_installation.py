import hashlib
import json
from pathlib import Path

import pytest

from scripts.reference.install_reference_package import (
    InstallError,
    install_reference_package,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> Path:
    source = tmp_path / "build"
    (source / "sequences").mkdir(parents=True)
    (source / "source").mkdir()
    fasta = source / "sequences" / "GRCh38.fa"
    fai = source / "sequences" / "GRCh38.fa.fai"
    dictionary = source / "sequences" / "GRCh38.dict"
    checksum_file = source / "source" / "md5checksums.txt"
    compressed = source / "source" / "reference.fa.gz"
    fasta.write_bytes(b">1\\nACGT\\n")
    fai.write_text("1\\t4\\t3\\t4\\t5\\n", encoding="ascii")
    dictionary.write_text("@HD\\tVN:1.6\\n@SQ\\tSN:1\\tLN:4\\n", encoding="ascii")
    checksum_file.write_text("0123456789abcdef0123456789abcdef  reference.fa.gz\\n", encoding="ascii")
    compressed.write_bytes(b"publisher compressed bytes")
    manifest = {
        "package_version": "ncbi-test-1",
        "package_checksum": "a" * 64,
        "assembly_name": "GRCh38",
        "fasta_path": str(fasta),
        "fai_path": str(fai),
        "dictionary_path": str(dictionary),
        "fasta_sha256": _sha(fasta),
        "fai_sha256": _sha(fai),
        "dictionary_sha256": _sha(dictionary),
        "source_contract": {
            "publisher_checksum_evidence": {
                "evidence_file_path": str(checksum_file),
                "verified_artifact_path": str(compressed),
                "expected_digest": "0123456789abcdef0123456789abcdef",
            }
        },
        "execution": {"location": str(fasta)},
    }
    manifest_path = source / "reference-package.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_installs_all_reference_and_publisher_evidence_assets_atomically(tmp_path: Path):
    manifest_path = _fixture(tmp_path)
    root = tmp_path / "persistent-mount" / "references"

    installed = install_reference_package(manifest_path, root)

    package_dir = root / "ncbi-test-1"
    assert installed["durable_install"]["status"] == "INSTALLED_VERIFIED"
    assert installed["durable_install"]["persistence_guarantee"] == "DEPLOYMENT_MOUNT_DEPENDENT"
    assert len(installed["durable_install"]["assets"]) == 5
    assert Path(installed["fasta_path"]) == package_dir / "sequences" / "GRCh38.fa"
    assert Path(installed["fai_path"]).is_file()
    assert Path(installed["dictionary_path"]).is_file()
    assert Path(installed["source_contract"]["publisher_checksum_evidence"]["evidence_file_path"]).is_file()
    assert Path(installed["source_contract"]["publisher_checksum_evidence"]["verified_artifact_path"]).is_file()
    assert not list(root.glob("*.staging-*"))
    assert (package_dir / "reference-package.json").is_file()


def test_install_is_idempotent_but_revalidates_every_persisted_asset(tmp_path: Path):
    manifest_path = _fixture(tmp_path)
    root = tmp_path / "persistent-mount" / "references"

    first = install_reference_package(manifest_path, root)
    second = install_reference_package(manifest_path, root)
    assert second["durable_install"]["package_checksum"] == first["durable_install"]["package_checksum"]

    fasta = Path(second["fasta_path"])
    fasta.write_bytes(b"tampered")
    with pytest.raises(InstallError, match="integrity check failed"):
        install_reference_package(manifest_path, root)


def test_install_refuses_to_overwrite_a_different_package_version(tmp_path: Path):
    manifest_path = _fixture(tmp_path)
    root = tmp_path / "persistent-mount" / "references"
    install_reference_package(manifest_path, root)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["package_checksum"] = "b" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(InstallError, match="different reference package"):
        install_reference_package(manifest_path, root)


def test_install_rejects_missing_publisher_source_evidence_without_partial_publish(tmp_path: Path):
    manifest_path = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    Path(manifest["source_contract"]["publisher_checksum_evidence"]["verified_artifact_path"]).unlink()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    root = tmp_path / "persistent-mount" / "references"

    with pytest.raises(FileNotFoundError):
        install_reference_package(manifest_path, root)

    assert not (root / "ncbi-test-1").exists()
    assert not list(root.glob(".ncbi-test-1.staging-*"))
