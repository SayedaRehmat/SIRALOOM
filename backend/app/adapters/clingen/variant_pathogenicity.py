"""ClinGen Variant Pathogenicity provider.

Consumes the official ClinGen Evidence Repository Variant Pathogenicity CSV/TSV
download as an explicitly governed local/file resource. The provider preserves
VCEP classification, condition, inheritance, ACMG/AMP codes, CAID and expert
panel provenance as evidence. It never converts a ClinGen assertion into a
SIRALOOM final classification.
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


class ClinGenVariantPathogenicityError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClinGenVariantAssertion:
    classification: str | None
    condition: str | None
    inheritance: str | None
    gene: str | None
    hgvs: tuple[str, ...]
    caid: str | None
    clinvar_id: str | None
    expert_panel: str | None
    met_codes: tuple[str, ...]
    unmet_codes: tuple[str, ...]
    version: str | None
    published_date: str | None
    source_record_id: str
    payload: dict[str, Any]
    record_sha256: str


class ClinGenVariantPathogenicityProvider:
    provider_id = "ClinGen Variant Pathogenicity"
    provider_version = "ERepo"
    supported_builds = frozenset({"GRCh37", "GRCh38"})

    def __init__(self, *, resource_path: str, delimiter: str | None = None) -> None:
        self.path = Path(resource_path)
        self.delimiter = delimiter

    @classmethod
    def from_execution_contract(cls, resolved: Any):
        contract = resolved.contract
        if contract.access_method not in {"LOCAL", "FILE", "LOCAL_ONLY"}:
            raise ClinGenVariantPathogenicityError(
                "ClinGen Variant Pathogenicity requires the governed official CSV/TSV download as a local/file resource"
            )
        if not contract.location:
            raise ClinGenVariantPathogenicityError("ClinGen Variant Pathogenicity resource location is required")
        toolchain = contract.toolchain or {}
        delimiter = toolchain.get("delimiter")
        if delimiter not in {None, ",", "\t"}:
            raise ClinGenVariantPathogenicityError("delimiter must be ',' or '\\t'")
        return cls(resource_path=contract.location, delimiter="\t" if delimiter == "\t" else delimiter)

    def query_variant(
        self,
        *,
        gene: str | None,
        hgvs: Iterable[str] = (),
        caid: str | None = None,
        clinvar_id: str | None = None,
    ) -> list[ClinGenVariantAssertion]:
        if not self.path.is_file():
            raise ClinGenVariantPathogenicityError(f"ClinGen Variant Pathogenicity file not found: {self.path}")

        wanted_gene = (gene or "").strip().upper()
        wanted_hgvs = {self._norm_hgvs(x) for x in hgvs if x}
        wanted_caid = self._norm_id(caid)
        wanted_clinvar = self._norm_id(clinvar_id)

        rows = list(self._read_rows())
        out: list[ClinGenVariantAssertion] = []
        for row in rows:
            normalized = self._normalize_row(row)
            row_gene = (normalized.get("gene") or "").upper()
            row_hgvs = {self._norm_hgvs(x) for x in normalized.get("hgvs", ())}
            row_caid = self._norm_id(normalized.get("caid"))
            row_clinvar = self._norm_id(normalized.get("clinvar_id"))

            exact_identifier = (
                wanted_caid and row_caid == wanted_caid
            ) or (
                wanted_clinvar and row_clinvar == wanted_clinvar
            )
            hgvs_match = bool(wanted_hgvs and row_hgvs.intersection(wanted_hgvs))
            gene_match = bool(wanted_gene and row_gene == wanted_gene)

            if exact_identifier or (gene_match and hgvs_match):
                out.append(self._to_assertion(normalized, row))

        return out

    def _read_rows(self):
        with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(8192)
            handle.seek(0)
            delimiter = self.delimiter or ("\t" if "\t" in sample and sample.count("\t") >= sample.count(",") else ",")
            reader = csv.DictReader(handle, delimiter=delimiter)
            if not reader.fieldnames:
                raise ClinGenVariantPathogenicityError("ClinGen Variant Pathogenicity file has no header")
            for row in reader:
                if row:
                    yield row

    @staticmethod
    def _key(row: dict[str, Any], *names: str) -> str | None:
        normalized = {
            str(k).strip().lower().replace(" ", "_").replace("-", "_"): v
            for k, v in row.items()
        }
        for name in names:
            value = normalized.get(name)
            if value not in (None, ""):
                return str(value).strip()
        return None

    @classmethod
    def _normalize_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        hgvs_raw = cls._key(row, "hgvs", "hgvs_expressions", "preferred_variant_title") or ""
        hgvs = tuple(x.strip() for x in hgvs_raw.split("|") if x.strip())
        met_raw = cls._key(row, "met_codes", "met_criteria") or ""
        unmet_raw = cls._key(row, "unmet_codes", "unmet_criteria") or ""
        return {
            "classification": cls._key(row, "classification"),
            "condition": cls._key(row, "condition", "disease"),
            "inheritance": cls._key(row, "moi", "inheritance", "mode_of_inheritance"),
            "gene": cls._key(row, "gene", "gene_symbol"),
            "hgvs": hgvs,
            "caid": cls._key(row, "caid", "ca_id"),
            "clinvar_id": cls._key(row, "clinvar_id", "cvid", "cv_id"),
            "expert_panel": cls._key(row, "expert_panel", "vcep"),
            "met_codes": tuple(x.strip() for x in met_raw.split(",") if x.strip()),
            "unmet_codes": tuple(x.strip() for x in unmet_raw.split(",") if x.strip()),
            "version": cls._key(row, "version"),
            "published_date": cls._key(row, "published_date", "approved_on", "classification_date"),
        }

    @classmethod
    def _to_assertion(cls, normalized: dict[str, Any], raw: dict[str, Any]) -> ClinGenVariantAssertion:
        canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        digest = hashlib.sha256(canonical).hexdigest()
        record_id = (
            normalized.get("caid")
            or normalized.get("clinvar_id")
            or "|".join(normalized.get("hgvs") or ())
        )
        if not record_id:
            raise ClinGenVariantPathogenicityError("Matched ClinGen record has no stable identifier")
        return ClinGenVariantAssertion(
            **normalized,
            source_record_id=f"ERepo:{record_id}",
            payload=dict(raw),
            record_sha256=digest,
        )

    @staticmethod
    def _norm_hgvs(value: str) -> str:
        return " ".join(str(value).strip().split()).upper()

    @staticmethod
    def _norm_id(value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip().upper()
        return text or None
