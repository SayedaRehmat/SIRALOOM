"""Reader for a locally qualified Human Phenotype Ontology annotation file.

This adapter preserves the source's disease, assertion, evidence, frequency,
negation, onset and curation fields. It does not score or validate disease
associations and never fetches HPOA data over the network.
"""

from __future__ import annotations

import gzip
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from backend.app.domain.resource_source_contract import ResourceExecutionContract


class HPOAError(ValueError):
    """The local HPOA artifact is malformed or does not match its resource pin."""


_REQUIRED_COLUMNS = (
    "database_id",
    "disease_name",
    "qualifier",
    "hpo_id",
    "reference",
    "evidence",
    "onset",
    "frequency",
    "sex",
    "modifier",
    "aspect",
    "biocuration",
)
_HPO_ID = re.compile(r"^HP:\d{7}$")
_RELEASE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ASPECTS = frozenset({"P", "C", "I", "H", "M"})


@dataclass(frozen=True)
class HPOADiseaseAnnotation:
    disease_id: str
    disease_name: str
    qualifier: str
    hpo_id: str
    reference: str
    evidence: str
    onset: str | None
    frequency: str | None
    sex: str | None
    modifiers: tuple[str, ...]
    aspect: str
    biocuration: tuple[str, ...]


class HPOAProvider:
    provider_id = "HPOA"
    provider_version = "HPOA_TSV"

    def __init__(
        self,
        path: str | Path,
        *,
        expected_sha256: str,
        expected_release: str,
        expected_hpo_release: str,
    ) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise HPOAError("Pinned HPOA annotation file is unavailable")
        expected = str(expected_sha256 or "").strip().lower()
        if expected.startswith("sha256:"):
            expected = expected.partition(":")[2]
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise HPOAError("A valid SHA-256 pin is required for the HPOA file")
        self.sha256 = self._sha256(self.path)
        if self.sha256 != expected:
            raise HPOAError("HPOA checksum does not match the approved resource")
        self.release, self.hpo_release, self.annotations = self._parse(self.path)
        if self.release != _release(expected_release):
            raise HPOAError(
                f"HPOA release mismatch: resource pins {expected_release}, file declares {self.release}"
            )
        if self.hpo_release != _release(expected_hpo_release):
            raise HPOAError(
                f"HPOA ontology release mismatch: expected {expected_hpo_release}, "
                f"file references {self.hpo_release}"
            )

    @classmethod
    def from_execution_contract(cls, contract: ResourceExecutionContract) -> HPOAProvider:
        if contract.access_method not in {"LOCAL", "FILE", "LOCAL_ONLY"}:
            raise HPOAError("HPOA execution requires a qualified local file resource")
        toolchain = dict(contract.toolchain or {})
        return cls(
            contract.location or "",
            expected_sha256=str(toolchain.get("sha256") or toolchain.get("checksum") or ""),
            expected_release=str(toolchain.get("release") or contract.dataset or ""),
            expected_hpo_release=str(toolchain.get("hpo_release") or ""),
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _open(path: Path) -> TextIO:
        if path.suffix.lower() == ".gz":
            return gzip.open(path, "rt", encoding="utf-8", newline="")
        return path.open("rt", encoding="utf-8", newline="")

    @classmethod
    def _parse(cls, path: Path) -> tuple[str, str, dict[str, tuple[HPOADiseaseAnnotation, ...]]]:
        release: str | None = None
        hpo_release: str | None = None
        header: tuple[str, ...] | None = None
        grouped: dict[str, list[HPOADiseaseAnnotation]] = {}
        with cls._open(path) as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                line = raw_line.rstrip("\r\n")
                if not line:
                    continue
                if line.startswith("#"):
                    key, separator, value = line[1:].partition(":")
                    if separator and key.strip() == "version":
                        if release is not None:
                            raise HPOAError("HPOA header repeats the version field")
                        release = _release(value.strip())
                    elif separator and key.strip() == "hpo-version":
                        if hpo_release is not None:
                            raise HPOAError("HPOA header repeats the hpo-version field")
                        match = re.search(r"(\d{4}-\d{2}-\d{2})", value)
                        if match is None:
                            raise HPOAError("HPOA header has an invalid HPO ontology release")
                        hpo_release = match.group(1)
                    elif header is None:
                        columns = tuple(item.strip() for item in line[1:].split("\t"))
                        if columns and columns[0] == _REQUIRED_COLUMNS[0]:
                            header = columns
                    continue
                if (
                    header is None
                    and tuple(item.strip() for item in line.split("\t")) == _REQUIRED_COLUMNS
                ):
                    header = _REQUIRED_COLUMNS
                    continue
                if header != _REQUIRED_COLUMNS:
                    raise HPOAError("HPOA data appeared before its supported 12-column header")
                fields = line.split("\t")
                if len(fields) != len(_REQUIRED_COLUMNS):
                    raise HPOAError(f"HPOA line {line_number} must contain 12 tab-separated fields")
                row = dict(zip(_REQUIRED_COLUMNS, fields, strict=True))
                disease_id = row["database_id"].strip()
                disease_name = row["disease_name"].strip()
                hpo_id = row["hpo_id"].strip()
                qualifier = row["qualifier"].strip().upper()
                aspect = row["aspect"].strip().upper()
                if not disease_id or not disease_name:
                    raise HPOAError(f"HPOA line {line_number} is missing disease identity")
                if not _HPO_ID.fullmatch(hpo_id):
                    raise HPOAError(
                        f"HPOA line {line_number} has invalid HPO identifier {hpo_id!r}"
                    )
                if qualifier not in {"", "NOT"}:
                    raise HPOAError(
                        f"HPOA line {line_number} has unsupported qualifier {qualifier!r}"
                    )
                if aspect not in _ASPECTS:
                    raise HPOAError(f"HPOA line {line_number} has unsupported aspect {aspect!r}")
                for field in ("reference", "evidence", "biocuration"):
                    if not row[field].strip():
                        raise HPOAError(f"HPOA line {line_number} is missing required {field}")
                annotation = HPOADiseaseAnnotation(
                    disease_id=disease_id,
                    disease_name=disease_name,
                    qualifier=qualifier,
                    hpo_id=hpo_id,
                    reference=row["reference"].strip(),
                    evidence=row["evidence"].strip(),
                    onset=row["onset"].strip() or None,
                    frequency=row["frequency"].strip() or None,
                    sex=row["sex"].strip().upper() or None,
                    modifiers=tuple(x.strip() for x in row["modifier"].split(";") if x.strip()),
                    aspect=aspect,
                    biocuration=tuple(
                        x.strip() for x in row["biocuration"].split(";") if x.strip()
                    ),
                )
                grouped.setdefault(disease_id.casefold(), []).append(annotation)
        if header != _REQUIRED_COLUMNS:
            raise HPOAError("HPOA file is missing the supported 12-column header")
        if release is None or hpo_release is None:
            raise HPOAError("HPOA file is missing its version or HPO ontology release")
        if not grouped:
            raise HPOAError("HPOA file contains no disease phenotype annotations")
        return (
            release,
            hpo_release,
            {disease_id: tuple(rows) for disease_id, rows in grouped.items()},
        )

    def query_disease(self, disease_id: str) -> tuple[HPOADiseaseAnnotation, ...]:
        """Return exact identifier matches; no disease crosswalk is inferred."""
        return self.annotations.get(str(disease_id or "").strip().casefold(), ())


def _release(value: str) -> str:
    release = str(value or "").strip()
    if not _RELEASE.fullmatch(release):
        raise HPOAError(f"Invalid HPOA release identity {release!r}")
    return release
