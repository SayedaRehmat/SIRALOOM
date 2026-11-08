"""Governed local Gene2Phenotype (G2P) disease-model provider.

G2P is used for disease-specific allelic requirement, molecular mechanism,
variant-consequence context and curated publication evidence. The provider
consumes only an organization-approved local export pinned by release and
SHA-256. It does not infer penetrance; G2P does not provide a universal
penetrance assertion in the exported model record.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class G2PError(ValueError):
    """The local G2P export is unavailable, unpinned, or malformed."""


@dataclass(frozen=True)
class G2PDiseaseModel:
    g2p_id: str
    gene_symbol: str
    disease_name: str
    disease_mondo: str | None
    allelic_requirement: str
    molecular_mechanism: str
    confidence: str
    publications: tuple[str, ...]
    phenotypes: tuple[str, ...]
    cross_cutting_modifiers: tuple[str, ...]
    variant_types: tuple[str, ...]
    variant_consequences: tuple[str, ...]
    mechanism_evidence: tuple[str, ...]
    source_record_id: str
    record_sha256: str
    raw: dict[str, str]


_ALIASES = {
    "g2p_id": ("g2p id", "g2p_id", "id"),
    "gene_symbol": ("gene symbol", "gene", "gene_symbol"),
    "disease_name": ("disease name", "disease", "disease_name"),
    "disease_mondo": ("disease mondo", "disease mondo id", "mondo id", "disease_mondo"),
    "allelic_requirement": ("allelic requirement", "required genotype", "allelic_requirement"),
    "molecular_mechanism": ("molecular mechanism", "mechanism", "molecular_mechanism"),
    "confidence": ("confidence", "association confidence"),
    "publications": ("publication", "publications", "publication pmids"),
    "phenotypes": ("publication phenotypes", "phenotypes", "hpo phenotypes"),
    "cross_cutting_modifiers": ("cross cutting modifier", "cross-cutting modifiers", "cross_cutting_modifier"),
    "variant_types": ("publication variant types", "variant types", "variant_types"),
    "variant_consequences": ("evidence based variant consequence", "inferred variant consequence", "variant consequences"),
    "mechanism_evidence": ("publication molecular mechanism evidence", "molecular mechanism categorisation", "mechanism evidence"),
}


def _header_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().casefold()).strip()


def _split_values(value: str | None) -> tuple[str, ...]:
    return tuple(sorted({part.strip() for part in re.split(r"[;|]", value or "") if part.strip()}))


def _normalize_mondo(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.fullmatch(r"(?:MONDO:|MONDO_)(\d{7})", text, flags=re.IGNORECASE)
    if not match:
        raise G2PError(f"Unsupported G2P disease MONDO identifier: {text!r}")
    return f"MONDO:{match.group(1)}"


class G2PProvider:
    provider_id = "Gene2Phenotype"
    provider_version = "G2P_CSV"
    supported_builds = frozenset({"GRCh37", "GRCh38"})

    def __init__(self, *, resource_path: str, expected_sha256: str, release: str) -> None:
        self.path = Path(resource_path)
        self.release = str(release or "").strip()
        if not re.fullmatch(r"v?\d+\.\d+\.\d+", self.release):
            raise G2PError("G2P resource release must be a pinned semantic version, e.g. v21.0.0")
        expected = str(expected_sha256 or "").strip().lower().removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise G2PError("A valid SHA-256 pin is required for the G2P export")
        if not self.path.is_file():
            raise G2PError("Pinned G2P export is unavailable")
        self.sha256 = self._sha256(self.path)
        if self.sha256 != expected:
            raise G2PError("G2P export checksum does not match the approved resource")
        self._records = self._parse()

    @classmethod
    def from_execution_contract(cls, resolved: Any) -> "G2PProvider":
        contract = resolved.contract
        if contract.access_method not in {"LOCAL", "FILE", "LOCAL_ONLY"}:
            raise G2PError("G2P execution requires a governed local export")
        toolchain = dict(contract.toolchain or {})
        release = toolchain.get("release") or contract.dataset
        return cls(
            resource_path=contract.location or "",
            expected_sha256=str(toolchain.get("sha256") or toolchain.get("checksum") or ""),
            release=str(release or ""),
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _parse(self) -> tuple[G2PDiseaseModel, ...]:
        try:
            with self.path.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                if not reader.fieldnames:
                    raise G2PError("G2P export is missing its CSV header")
                normalized_headers = {_header_key(name): name for name in reader.fieldnames}
                columns: dict[str, str] = {}
                for field, aliases in _ALIASES.items():
                    found = next((normalized_headers[_header_key(alias)] for alias in aliases if _header_key(alias) in normalized_headers), None)
                    if found is None and field in {"g2p_id", "gene_symbol", "disease_name", "allelic_requirement", "molecular_mechanism", "confidence"}:
                        raise G2PError(f"G2P export is missing required column for {field}")
                    if found is not None:
                        columns[field] = found
                models: list[G2PDiseaseModel] = []
                for line_number, row in enumerate(reader, start=2):
                    raw = {str(k): str(v or "").strip() for k, v in row.items() if k is not None}
                    gene = raw.get(columns.get("gene_symbol", ""), "").upper()
                    if not gene:
                        raise G2PError(f"G2P row {line_number} is missing gene symbol")
                    g2p_id = raw.get(columns.get("g2p_id", ""), "")
                    if not g2p_id:
                        raise G2PError(f"G2P row {line_number} is missing stable G2P ID")
                    disease_name = raw.get(columns.get("disease_name", ""), "")
                    if not disease_name:
                        raise G2PError(f"G2P row {line_number} is missing disease name")
                    allelic = raw.get(columns.get("allelic_requirement", ""), "").strip()
                    mechanism = raw.get(columns.get("molecular_mechanism", ""), "").strip()
                    confidence = raw.get(columns.get("confidence", ""), "").strip()
                    if not allelic or not mechanism or not confidence:
                        raise G2PError(f"G2P row {line_number} lacks allelic requirement, molecular mechanism or confidence")
                    mondo = _normalize_mondo(raw.get(columns.get("disease_mondo", ""), ""))
                    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
                    digest = hashlib.sha256(canonical).hexdigest()
                    models.append(G2PDiseaseModel(
                        g2p_id=g2p_id,
                        gene_symbol=gene,
                        disease_name=disease_name,
                        disease_mondo=mondo,
                        allelic_requirement=allelic,
                        molecular_mechanism=mechanism,
                        confidence=confidence,
                        publications=_split_values(raw.get(columns.get("publications", ""))),
                        phenotypes=_split_values(raw.get(columns.get("phenotypes", ""))),
                        cross_cutting_modifiers=_split_values(raw.get(columns.get("cross_cutting_modifiers", ""))),
                        variant_types=_split_values(raw.get(columns.get("variant_types", ""))),
                        variant_consequences=_split_values(raw.get(columns.get("variant_consequences", ""))),
                        mechanism_evidence=_split_values(raw.get(columns.get("mechanism_evidence", ""))),
                        source_record_id=f"G2P:{g2p_id}",
                        record_sha256=digest,
                        raw=raw,
                    ))
        except OSError as exc:
            raise G2PError(f"Unable to read pinned G2P export: {exc}") from exc
        if not models:
            raise G2PError("G2P export contains no disease models")
        return tuple(models)

    def query_gene(self, *, gene: str) -> tuple[G2PDiseaseModel, ...]:
        wanted = str(gene or "").strip().upper()
        if not wanted:
            return ()
        return tuple(model for model in self._records if model.gene_symbol == wanted)
