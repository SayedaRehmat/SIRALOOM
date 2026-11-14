"""Publisher checksum evidence verification for staged reference artifacts."""
from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlparse
from typing import Any


class PublisherChecksumError(ValueError):
    def __init__(self, message: str, *, code: str = "PUBLISHER_CHECKSUM_EVIDENCE_INVALID"):
        super().__init__(message)
        self.code = code


def _digest_file(path: Path, algorithm: str) -> str:
    if algorithm not in {"md5", "sha256"}:
        raise PublisherChecksumError(
            f"unsupported publisher checksum algorithm {algorithm!r}",
            code="PUBLISHER_CHECKSUM_ALGORITHM_UNSUPPORTED",
        )
    digest = hashlib.new(algorithm, usedforsecurity=False) if algorithm == "md5" else hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_publisher_checksum_evidence(
    source_contract: dict[str, Any],
    *,
    artifact_path: str | Path,
) -> dict[str, Any]:
    """Verify publisher-published checksum text against evidence bytes and artifact bytes.

    The checksum text file itself is pinned by SHA-256. The expected artifact
    digest must occur in that file for the exact artifact basename, and the
    actual staged artifact bytes must produce that same digest.
    """
    evidence = source_contract.get("publisher_checksum_evidence")
    if not isinstance(evidence, dict):
        raise PublisherChecksumError(
            "reference package has no publisher checksum evidence object",
            code="PUBLISHER_CHECKSUM_EVIDENCE_MISSING",
        )
    algorithm = str(evidence.get("algorithm") or "").lower()
    expected = str(evidence.get("expected_digest") or "").lower()
    evidence_path = Path(str(evidence.get("evidence_file_path") or ""))
    artifact = Path(artifact_path)
    artifact_filename = str(evidence.get("artifact_filename") or "")
    artifact_url = str(source_contract.get("artifact_url") or "")
    url_filename = Path(urlparse(artifact_url).path).name
    evidence_url = str(evidence.get("evidence_file_url") or "")
    expected_evidence_sha = str(evidence.get("evidence_file_sha256") or "").lower()

    if not artifact_filename or artifact_filename != url_filename:
        raise PublisherChecksumError(
            "publisher checksum filename does not match the authoritative artifact URL",
            code="PUBLISHER_ARTIFACT_URL_MISMATCH",
        )
    if not evidence_url.startswith("https://"):
        raise PublisherChecksumError(
            "publisher checksum evidence URL must be HTTPS",
            code="PUBLISHER_EVIDENCE_URL_INVALID",
        )
    if not evidence_path.is_file() or not artifact.is_file():
        raise PublisherChecksumError(
            "publisher checksum evidence file or downloaded artifact is missing",
            code="PUBLISHER_EVIDENCE_FILE_MISSING",
        )
    actual_evidence_sha = _digest_file(evidence_path, "sha256")
    if not expected_evidence_sha or actual_evidence_sha != expected_evidence_sha:
        raise PublisherChecksumError(
            "publisher checksum evidence file SHA-256 does not match its pinned digest",
            code="PUBLISHER_EVIDENCE_FILE_CHECKSUM_MISMATCH",
        )
    if algorithm not in {"md5", "sha256"} or not expected:
        raise PublisherChecksumError(
            "publisher checksum algorithm or expected digest is missing/unsupported",
            code="PUBLISHER_CHECKSUM_DECLARATION_INVALID",
        )
    manifest_match = False
    for line in evidence_path.read_text(encoding="utf-8").splitlines():
        fields = line.strip().lstrip("*").split()
        if len(fields) >= 2 and Path(fields[-1]).name == artifact_filename:
            if fields[0].lower() != expected:
                raise PublisherChecksumError(
                    "declared publisher digest differs from the digest in the publisher manifest",
                    code="PUBLISHER_CHECKSUM_MANIFEST_MISMATCH",
                )
            manifest_match = True
            break
    if not manifest_match:
        raise PublisherChecksumError(
            f"publisher checksum manifest has no entry for {artifact_filename!r}",
            code="PUBLISHER_CHECKSUM_ENTRY_MISSING",
        )
    actual_artifact_digest = _digest_file(artifact, algorithm)
    if actual_artifact_digest != expected:
        raise PublisherChecksumError(
            "downloaded reference artifact does not match publisher checksum",
            code="PUBLISHER_ARTIFACT_CHECKSUM_MISMATCH",
        )
    return {
        "status": "VERIFIED",
        "algorithm": algorithm,
        "expected_digest": expected,
        "observed_artifact_digest": actual_artifact_digest,
        "evidence_file_sha256": actual_evidence_sha,
        "evidence_file_url": evidence_url,
        "artifact_url": artifact_url,
        "artifact_filename": artifact_filename,
    }
