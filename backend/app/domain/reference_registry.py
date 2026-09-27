from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


class ReferencePackageError(ValueError):
    """A reference package failed qualification checks."""


@dataclass(frozen=True)
class ReferencePackage:
    build: str
    fasta: Path
    fai: Path
    manifest: Path
    fasta_sha256: str
    fai_sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_reference_package(
    *,
    build: str,
    fasta_path: str | Path,
    fai_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
) -> ReferencePackage:
    if build not in {"GRCh37", "GRCh38"}:
        raise ReferencePackageError(f"Unsupported reference build: {build}")

    fasta = Path(fasta_path).expanduser().resolve()
    fai = Path(fai_path).expanduser().resolve() if fai_path else Path(f"{fasta}.fai")
    manifest = (
        Path(manifest_path).expanduser().resolve()
        if manifest_path
        else fasta.parent / "manifest.json"
    )

    for path, label in ((fasta, "FASTA"), (fai, "FAI"), (manifest, "manifest")):
        if not path.is_file():
            raise ReferencePackageError(f"Reference {label} not found: {path}")

    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReferencePackageError(f"Invalid reference manifest: {manifest}") from exc

    if data.get("assembly") != build:
        raise ReferencePackageError(
            f"Reference manifest assembly {data.get('assembly')!r} does not match {build}"
        )

    expected_fasta = str(data.get("fasta_sha256", "")).lower()
    expected_fai = str(data.get("fai_sha256", "")).lower()
    if len(expected_fasta) != 64 or len(expected_fai) != 64:
        raise ReferencePackageError(
            "Reference manifest must contain 64-character fasta_sha256 and fai_sha256 values."
        )

    actual_fasta = sha256_file(fasta)
    actual_fai = sha256_file(fai)

    if actual_fasta != expected_fasta:
        raise ReferencePackageError(
            f"Reference FASTA SHA-256 mismatch for {build}: expected {expected_fasta}, got {actual_fasta}"
        )
    if actual_fai != expected_fai:
        raise ReferencePackageError(
            f"Reference FAI SHA-256 mismatch for {build}: expected {expected_fai}, got {actual_fai}"
        )

    return ReferencePackage(
        build=build,
        fasta=fasta,
        fai=fai,
        manifest=manifest,
        fasta_sha256=actual_fasta,
        fai_sha256=actual_fai,
    )
