"""Deterministic, release-pinned HGNC identifier resolution.

This module never performs fuzzy matching. The resolver is constructed from
both official HGNC tab-separated artifacts and must be bound to their exact
SHA-256 digests and release identity.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import tempfile
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

HGNC_ARCHIVE_RELEASE = "2026-10-06"
HGNC_COMPLETE_URL = (
    "https://storage.googleapis.com/public-download-files/hgnc/archive/archive/"
    "quarterly/tsv/hgnc_complete_set_2026-10-06.txt"
)
HGNC_WITHDRAWN_URL = (
    "https://storage.googleapis.com/public-download-files/hgnc/archive/archive/"
    "quarterly/tsv/withdrawn_2026-10-06.txt"
)
HGNC_PUBLISHER = "HUGO Gene Nomenclature Committee"
HGNC_LICENSE = "CC0-1.0"
HGNC_ID_RE = re.compile(r"^HGNC:[0-9]+$", re.IGNORECASE)
ENSEMBL_GENE_RE = re.compile(r"^(ENSG[0-9]{11})(?:\.[0-9]+)?$", re.IGNORECASE)


class HGNCResourceError(ValueError):
    """Invalid or incomplete HGNC release or identifier."""


class HGNCResolutionStatus:
    APPROVED_SYMBOL = "APPROVED_SYMBOL"
    ALIAS_SYMBOL = "ALIAS_SYMBOL"
    PREVIOUS_SYMBOL = "PREVIOUS_SYMBOL"
    HGNC_ID = "HGNC_ID"
    ENSEMBL_GENE_ID = "ENSEMBL_GENE_ID"
    WITHDRAWN_MERGED = "WITHDRAWN_MERGED"
    AMBIGUOUS = "AMBIGUOUS"
    WITHDRAWN_UNRESOLVED = "WITHDRAWN_UNRESOLVED"
    NOT_FOUND = "NOT_FOUND"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class HGNCResolution:
    input_identifier: str
    normalized_identifier: str
    status: str
    hgnc_id: str | None
    approved_symbol: str | None
    matched_field: str | None
    candidate_hgnc_ids: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.hgnc_id is not None and self.status not in {
            HGNCResolutionStatus.AMBIGUOUS,
            HGNCResolutionStatus.WITHDRAWN_UNRESOLVED,
            HGNCResolutionStatus.NOT_FOUND,
            HGNCResolutionStatus.INVALID,
        }


def _split(value: str | None) -> tuple[str, ...]:
    return tuple(sorted({part.strip() for part in (value or "").split("|") if part.strip()}))


def _normalize_header(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if normalized.startswith("merged_into_report"):
        return "merged_into_report"
    return normalized


def _read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file() or path.stat().st_size == 0:
        raise HGNCResourceError(f"HGNC artifact missing or empty: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames:
            raise HGNCResourceError(f"HGNC artifact has no header: {path}")
        raw_fields = list(reader.fieldnames)
        normalized_fields = [_normalize_header(field) for field in raw_fields]
        if len(normalized_fields) != len(set(normalized_fields)):
            raise HGNCResourceError(f"HGNC artifact has duplicate normalized headers: {path}")
        rows = [
            {
                normalized: str(row.get(raw) or "")
                for raw, normalized in zip(raw_fields, normalized_fields)
            }
            for row in reader
        ]
        if not rows:
            raise HGNCResourceError(f"HGNC artifact has no records: {path}")
        return normalized_fields, rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def acquire_hgnc_release(destination: Path, *, release: str = HGNC_ARCHIVE_RELEASE) -> dict:
    """Acquire and atomically publish the exact official HGNC archive package.

    Both source artifacts and the manifest are completed and fsynced inside a
    private sibling staging directory. A single same-filesystem directory
    rename publishes the complete package; an interrupted acquisition never
    exposes a partially populated destination directory.

    Local SHA-256 values provide reproducible byte identity. HGNC does not
    publish per-file cryptographic checksums, so these are not represented as
    upstream authenticity checksums.
    """
    if release != HGNC_ARCHIVE_RELEASE:
        raise HGNCResourceError(
            f"unsupported pinned HGNC release {release!r}; expected {HGNC_ARCHIVE_RELEASE}"
        )
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise HGNCResourceError("HGNC release destination already exists")

    artifacts = (
        ("hgnc_complete_set.txt", HGNC_COMPLETE_URL),
        ("withdrawn.txt", HGNC_WITHDRAWN_URL),
    )
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent)
    )
    published = False
    try:
        manifest_files = []
        for filename, url in artifacts:
            request = Request(url, headers={"User-Agent": "SIRALOOM-resource-acquisition/1.0"})
            with urlopen(request, timeout=120) as response:
                if response.status != 200:
                    raise HGNCResourceError(f"HGNC download failed with HTTP {response.status}: {url}")
                temporary = staging_dir / f".{filename}.part"
                with temporary.open("xb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
            if temporary.stat().st_size == 0:
                raise HGNCResourceError(f"HGNC download returned an empty artifact: {url}")
            final_artifact = staging_dir / filename
            os.replace(temporary, final_artifact)
            manifest_files.append({
                "filename": filename,
                "source_url": url,
                "sha256": _sha256(final_artifact),
                "size_bytes": final_artifact.stat().st_size,
            })

        manifest = {
            "schema": "siraloom.hgnc-acquisition.v1",
            "publisher": HGNC_PUBLISHER,
            "release": release,
            "release_kind": "HGNC_QUARTERLY_ARCHIVE",
            "license": HGNC_LICENSE,
            "license_url": "https://www.genenames.org/about/license/",
            "authority_url": "https://www.genenames.org/download/archive/",
            "checksum_semantics": "LOCAL_SHA256; HGNC_DOES_NOT_PUBLISH_FILE_CHECKSUMS",
            "files": manifest_files,
        }
        manifest_temporary = staging_dir / ".manifest.json.part"
        with manifest_temporary.open("x", encoding="utf-8") as output:
            output.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(manifest_temporary, staging_dir / "manifest.json")

        # Persist the complete directory contents before making the directory
        # visible at its final path.
        staging_fd = os.open(staging_dir, os.O_RDONLY)
        try:
            os.fsync(staging_fd)
        finally:
            os.close(staging_fd)

        # The staging directory is a sibling of destination, so this rename is
        # a same-filesystem atomic publication of all three package files.
        os.rename(staging_dir, destination)
        published = True

        parent_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        return manifest
    except Exception:
        if not published:
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise

class HGNCResolver:
    """Exact resolver over one validated pair of HGNC release artifacts."""

    def __init__(
        self,
        complete_set_path: Path,
        withdrawn_path: Path,
        *,
        release: str,
        expected_complete_sha256: str | None = None,
        expected_withdrawn_sha256: str | None = None,
    ):
        if release != HGNC_ARCHIVE_RELEASE:
            raise HGNCResourceError(f"unsupported HGNC release: {release}")
        self.release = release
        complete_fields, genes = _read_tsv(complete_set_path)
        withdrawn_fields, withdrawn = _read_tsv(withdrawn_path)
        required_gene_fields = {
            "hgnc_id", "symbol", "alias_symbol", "prev_symbol", "ensembl_gene_id"
        }
        required_withdrawn_fields = {
            "hgnc_id", "status", "withdrawn_symbol", "merged_into_report"
        }
        if not required_gene_fields.issubset(set(complete_fields)):
            raise HGNCResourceError(
                "complete-set schema missing columns: "
                + ", ".join(sorted(required_gene_fields - set(complete_fields)))
            )
        if not required_withdrawn_fields.issubset(set(withdrawn_fields)):
            raise HGNCResourceError(
                "withdrawn schema missing columns: "
                + ", ".join(sorted(required_withdrawn_fields - set(withdrawn_fields)))
                + f"; observed columns: {sorted(withdrawn_fields)}"
            )
        self._approved: dict[str, dict[str, str]] = {}
        self._approved_symbols: dict[str, set[str]] = {}
        self._alias_index: dict[str, set[str]] = {}
        self._previous: dict[str, set[str]] = {}
        self._ensembl: dict[str, set[str]] = {}
        self._withdrawn: dict[str, list[tuple[str, tuple[tuple[str, str, str], ...]]]] = {}
        for row in genes:
            hgnc_id = row["hgnc_id"].strip().upper()
            symbol = row["symbol"].strip().upper()
            if not HGNC_ID_RE.fullmatch(hgnc_id) or not symbol:
                raise HGNCResourceError("complete set contains invalid HGNC ID or approved symbol")
            if hgnc_id in self._approved:
                raise HGNCResourceError(f"duplicate approved HGNC ID: {hgnc_id}")
            self._approved[hgnc_id] = {"symbol": row["symbol"].strip()}
            self._approved_symbols.setdefault(symbol, set()).add(hgnc_id)
            for alias in _split(row.get("alias_symbol")):
                self._alias_index.setdefault(alias.upper(), set()).add(hgnc_id)
            for previous in _split(row.get("prev_symbol")):
                self._previous.setdefault(previous.upper(), set()).add(hgnc_id)
            for ensembl_id in _split(row.get("ensembl_gene_id")):
                match = ENSEMBL_GENE_RE.fullmatch(ensembl_id.upper())
                if match:
                    self._ensembl.setdefault(match.group(1), set()).add(hgnc_id)
        self._withdrawn_ids: dict[str, list[tuple[str, tuple[tuple[str, str, str], ...]]]] = {}
        for row in withdrawn:
            withdrawn_id = row["hgnc_id"].strip().upper()
            symbol = row["withdrawn_symbol"].strip().upper()
            status = row["status"].strip()
            if not status:
                raise HGNCResourceError("withdrawn set contains a record without a status")
            if status.casefold() not in {"merged/split", "entry withdrawn"}:
                raise HGNCResourceError(f"withdrawn set contains an unsupported status: {status!r}")
            targets = []
            for raw_target in (row.get("merged_into_report") or "").split(","):
                parts = [part.strip() for part in raw_target.split("|")]
                if len(parts) >= 2 and HGNC_ID_RE.fullmatch(parts[0].upper()):
                    targets.append((parts[0].upper(), parts[1].upper(), parts[2] if len(parts) > 2 else ""))
            target_tuple = tuple(targets)
            if withdrawn_id:
                if not HGNC_ID_RE.fullmatch(withdrawn_id):
                    raise HGNCResourceError(f"withdrawn set contains invalid HGNC ID: {withdrawn_id!r}")
                self._withdrawn_ids.setdefault(withdrawn_id, []).append((status, target_tuple))
            if symbol:
                self._withdrawn.setdefault(symbol, []).append((status, target_tuple))
        self.complete_sha256 = _sha256(complete_set_path)
        self.withdrawn_sha256 = _sha256(withdrawn_path)
        for label, expected, actual in (
            ("complete-set", expected_complete_sha256, self.complete_sha256),
            ("withdrawn", expected_withdrawn_sha256, self.withdrawn_sha256),
        ):
            if expected is None:
                continue
            normalized_expected = str(expected).strip().lower().removeprefix("sha256:")
            if not re.fullmatch(r"[0-9a-f]{64}", normalized_expected):
                raise HGNCResourceError(f"{label} expected SHA-256 is invalid")
            if actual != normalized_expected:
                raise HGNCResourceError(f"{label} SHA-256 does not match the qualified manifest")

    def resolve(self, identifier: str) -> HGNCResolution:
        if not isinstance(identifier, str):
            original = str(identifier)
            return HGNCResolution(
                original, "", HGNCResolutionStatus.INVALID, None, None, None
            )
        original = identifier
        raw = identifier.strip()
        normalized = raw.upper()
        if not raw:
            return HGNCResolution(original, normalized, HGNCResolutionStatus.INVALID, None, None, None)
        if HGNC_ID_RE.fullmatch(normalized):
            if normalized in self._approved:
                return self._result(original, normalized, normalized, HGNCResolutionStatus.HGNC_ID, "hgnc_id")
            withdrawn_id = self._withdrawn_ids.get(normalized, [])
            if withdrawn_id:
                return self._resolve_withdrawn(
                    original, normalized, withdrawn_id, "withdrawn_hgnc_id"
                )
            return HGNCResolution(original, normalized, HGNCResolutionStatus.NOT_FOUND, None, None, "hgnc_id")
        ensembl = ENSEMBL_GENE_RE.fullmatch(normalized)
        if ensembl:
            candidates = self._ensembl.get(ensembl.group(1), set())
            if not candidates:
                return HGNCResolution(original, normalized, HGNCResolutionStatus.NOT_FOUND, None, None, "ensembl_gene_id")
            return self._resolve_candidates(original, normalized, candidates, HGNCResolutionStatus.ENSEMBL_GENE_ID, "ensembl_gene_id")
        approved = self._approved_symbols.get(normalized, set())
        withdrawn = self._withdrawn.get(normalized, [])
        if withdrawn:
            # A historical withdrawn symbol can collide with a currently
            # approved symbol. Never let the current symbol silently shadow
            # the historical identity: both records must resolve to one and
            # the same approved HGNC accession, otherwise the input is
            # ambiguous or remains unresolved.
            historical = self._resolve_withdrawn(
                original, normalized, withdrawn, "withdrawn_symbol"
            )
            if not approved:
                return historical
            if historical.hgnc_id is None:
                return HGNCResolution(
                    original,
                    normalized,
                    HGNCResolutionStatus.WITHDRAWN_UNRESOLVED,
                    None,
                    None,
                    "withdrawn_symbol",
                    tuple(sorted(approved | set(historical.candidate_hgnc_ids))),
                )
            combined = approved | {historical.hgnc_id}
            if len(combined) > 1:
                return self._ambiguous(original, normalized, combined, "approved_and_withdrawn_symbol")
            return self._resolve_candidates(
                original, normalized, combined,
                HGNCResolutionStatus.APPROVED_SYMBOL, "symbol",
            )
        alias_candidates = self._alias_candidates(normalized)
        previous_candidates = self._previous.get(normalized, set())
        historical_candidates = alias_candidates | previous_candidates
        if approved and historical_candidates:
            combined = approved | historical_candidates
            if len(combined) > 1:
                return self._ambiguous(
                    original, normalized, combined, "approved_and_historical_symbol"
                )
            return self._resolve_candidates(
                original, normalized, combined,
                HGNCResolutionStatus.APPROVED_SYMBOL, "symbol",
            )
        if len(approved) == 1:
            return self._resolve_candidates(original, normalized, approved, HGNCResolutionStatus.APPROVED_SYMBOL, "symbol")
        if len(approved) > 1:
            return self._ambiguous(original, normalized, approved, "symbol")
        # Alias and previous-symbol namespaces are resolved independently so
        # collisions are surfaced rather than silently selecting one record.
        if historical_candidates:
            if len(historical_candidates) > 1:
                return self._ambiguous(original, normalized, historical_candidates, "historical_symbol")
            if alias_candidates:
                return self._resolve_candidates(original, normalized, alias_candidates, HGNCResolutionStatus.ALIAS_SYMBOL, "alias_symbol")
            return self._resolve_candidates(original, normalized, previous_candidates, HGNCResolutionStatus.PREVIOUS_SYMBOL, "prev_symbol")
        return HGNCResolution(original, normalized, HGNCResolutionStatus.NOT_FOUND, None, None, None)

    def _resolve_withdrawn(self, original, normalized, records, field):
        targets = {
            target[0]
            for _status, rows in records
            for target in rows
            if target[0] in self._approved
        }
        if len(targets) == 1 and all(status.casefold() == "merged/split" for status, _ in records):
            target_id = next(iter(targets))
            return self._result(
                original, normalized, target_id, HGNCResolutionStatus.WITHDRAWN_MERGED, field
            )
        return HGNCResolution(
            original, normalized, HGNCResolutionStatus.WITHDRAWN_UNRESOLVED,
            None, None, field, tuple(sorted(targets))
        )

    def _alias_candidates(self, normalized: str) -> set[str]:
        return self._alias_index.get(normalized, set())

    def _resolve_candidates(self, original, normalized, candidates, status, field):
        candidates = set(candidates)
        if len(candidates) != 1:
            return self._ambiguous(original, normalized, candidates, field)
        hgnc_id = next(iter(candidates))
        return self._result(original, normalized, hgnc_id, status, field)

    def _ambiguous(self, original, normalized, candidates, field):
        return HGNCResolution(
            original, normalized, HGNCResolutionStatus.AMBIGUOUS,
            None, None, field, tuple(sorted(candidates))
        )

    def _result(self, original, normalized, hgnc_id, status, field):
        return HGNCResolution(
            original, normalized, status, hgnc_id,
            self._approved[hgnc_id]["symbol"], field, (hgnc_id,)
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire the pinned official HGNC crosswalk release.")
    parser.add_argument("command", choices=("acquire",))
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--release", default=HGNC_ARCHIVE_RELEASE)
    args = parser.parse_args()
    manifest = acquire_hgnc_release(args.destination, release=args.release)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
