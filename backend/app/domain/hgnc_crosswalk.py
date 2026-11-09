"""Deterministic, release-pinned HGNC identifier resolution.

This module never performs fuzzy matching. The resolver is constructed from
both official HGNC tab-separated artifacts and must be bound to their exact
SHA-256 digests and release identity.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
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


def _read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file() or path.stat().st_size == 0:
        raise HGNCResourceError(f"HGNC artifact missing or empty: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames:
            raise HGNCResourceError(f"HGNC artifact has no header: {path}")
        rows = list(reader)
        if not rows:
            raise HGNCResourceError(f"HGNC artifact has no records: {path}")
        return list(reader.fieldnames), rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def acquire_hgnc_release(destination: Path, *, release: str = HGNC_ARCHIVE_RELEASE) -> dict:
    """Download the immutable official quarterly snapshot and preserve bytes.

    Existing files are never overwritten. The manifest records local SHA-256
    digests; HGNC does not publish per-file cryptographic checksums.
    """
    if release != HGNC_ARCHIVE_RELEASE:
        raise HGNCResourceError(
            f"unsupported pinned HGNC release {release!r}; expected {HGNC_ARCHIVE_RELEASE}"
        )
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    artifacts = (
        ("hgnc_complete_set.txt", HGNC_COMPLETE_URL),
        ("withdrawn.txt", HGNC_WITHDRAWN_URL),
    )
    manifest_files = []
    for filename, url in artifacts:
        path = destination / filename
        if path.exists():
            raise HGNCResourceError(f"refusing to overwrite existing source artifact: {path}")
        request = Request(url, headers={"User-Agent": "SIRALOOM-resource-acquisition/1.0"})
        with urlopen(request, timeout=120) as response, path.open("xb") as output:
            if response.status != 200:
                raise HGNCResourceError(f"HGNC download failed with HTTP {response.status}: {url}")
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        manifest_files.append({
            "filename": filename,
            "source_url": url,
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
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
    manifest_path = destination / "manifest.json"
    if manifest_path.exists():
        raise HGNCResourceError(f"refusing to overwrite acquisition manifest: {manifest_path}")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


class HGNCResolver:
    """Exact resolver over one validated pair of HGNC release artifacts."""

    def __init__(self, complete_set_path: Path, withdrawn_path: Path, *, release: str):
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
            )
        self._approved: dict[str, dict[str, str]] = {}
        self._approved_symbols: dict[str, set[str]] = {}
        self._alias_index: dict[str, set[str]] = {}
        self._previous: dict[str, set[str]] = {}
        self._ensembl: dict[str, set[str]] = {}
        self._withdrawn: dict[str, list[tuple[str, str, str]]] = {}
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
        for row in withdrawn:
            symbol = row["withdrawn_symbol"].strip().upper()
            if not symbol:
                continue
            status = row["status"].strip()
            targets = []
            for raw_target in (row.get("merged_into_report") or "").split(","):
                parts = [part.strip() for part in raw_target.split("|")]
                if len(parts) >= 2 and HGNC_ID_RE.fullmatch(parts[0].upper()):
                    targets.append((parts[0].upper(), parts[1].upper(), parts[2] if len(parts) > 2 else ""))
            self._withdrawn.setdefault(symbol, []).append((status, tuple(targets)))
        self.complete_sha256 = _sha256(complete_set_path)
        self.withdrawn_sha256 = _sha256(withdrawn_path)

    def resolve(self, identifier: str) -> HGNCResolution:
        original = identifier
        raw = identifier.strip()
        normalized = raw.upper()
        if not raw:
            return HGNCResolution(original, normalized, HGNCResolutionStatus.INVALID, None, None, None)
        if HGNC_ID_RE.fullmatch(normalized):
            if normalized in self._approved:
                return self._result(original, normalized, normalized, HGNCResolutionStatus.HGNC_ID, "hgnc_id")
            return HGNCResolution(original, normalized, HGNCResolutionStatus.NOT_FOUND, None, None, "hgnc_id")
        ensembl = ENSEMBL_GENE_RE.fullmatch(normalized)
        if ensembl:
            return self._resolve_candidates(original, normalized, self._ensembl.get(ensembl.group(1), set()), HGNCResolutionStatus.ENSEMBL_GENE_ID, "ensembl_gene_id")
        approved = self._approved_symbols.get(normalized, set())
        if len(approved) == 1:
            return self._resolve_candidates(original, normalized, approved, HGNCResolutionStatus.APPROVED_SYMBOL, "symbol")
        if len(approved) > 1:
            return self._ambiguous(original, normalized, approved, "symbol")
        # Alias and previous-symbol namespaces are resolved independently so
        # collisions are surfaced rather than silently selecting one record.
        alias_candidates = self._alias_candidates(normalized)
        if alias_candidates:
            return self._resolve_candidates(original, normalized, alias_candidates, HGNCResolutionStatus.ALIAS_SYMBOL, "alias_symbol")
        previous_candidates = self._previous.get(normalized, set())
        if previous_candidates:
            return self._resolve_candidates(original, normalized, previous_candidates, HGNCResolutionStatus.PREVIOUS_SYMBOL, "prev_symbol")
        withdrawn = self._withdrawn.get(normalized, [])
        if withdrawn:
            targets = {
                target[0]
                for _status, rows in withdrawn
                for target in rows
                if target[0] in self._approved
            }
            if len(targets) == 1 and all(status.casefold() == "merged/split" for status, _ in withdrawn):
                target_id = next(iter(targets))
                return self._result(original, normalized, target_id, HGNCResolutionStatus.WITHDRAWN_MERGED, "withdrawn_symbol")
            return HGNCResolution(
                original, normalized, HGNCResolutionStatus.WITHDRAWN_UNRESOLVED,
                None, None, "withdrawn_symbol", tuple(sorted(targets))
            )
        return HGNCResolution(original, normalized, HGNCResolutionStatus.NOT_FOUND, None, None, None)

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
