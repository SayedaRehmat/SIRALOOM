"""ClinGen Variant Pathogenicity provider.

Consumes the official ClinGen Evidence Repository Variant Pathogenicity CSV/TSV
download as an explicitly governed local/file resource. The provider preserves
VCEP classification, condition, inheritance, variant identity, criterion-level
met/not-met codes, version and expert-panel provenance as source evidence. It
never converts a ClinGen assertion into a SIRALOOM final classification.

The ERepo summary export is intentionally treated as a summary-level contract:
it exposes ACMG/AMP criterion codes but not the per-code narrative comments
shown on individual ERepo classification pages. SIRALOOM therefore stores the
codes as structured criterion observations and does not invent criterion
rationales that are absent from the governed export.
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
class ClinGenCriterionAssertion:
    code: str
    status: str
    source: str = "ClinGen ERepo Variant Pathogenicity summary export"
    rationale: str | None = None


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
    criterion_assertions: tuple[ClinGenCriterionAssertion, ...]
    version: str | None
    published_date: str | None
    source_record_id: str
    payload: dict[str, Any]
    record_sha256: str


class ClinGenVariantPathogenicityProvider:
    provider_id = "ClinGen Variant Pathogenicity"
    provider_version = "ERepo"

    # The summary export itself is not coordinate/build specific. A matched
    # assertion can contain HGVS expressions for multiple assemblies. Build
    # compatibility is therefore determined by the caller's variant identity,
    # not by this provider descriptor.
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
            raise ClinGenVariantPathogenicityError(
                "ClinGen Variant Pathogenicity resource location is required"
            )
        toolchain = contract.toolchain or {}
        delimiter = toolchain.get("delimiter")
        if delimiter not in {None, ",", "\t"}:
            raise ClinGenVariantPathogenicityError("delimiter must be ',' or '\\t'")
        return cls(
            resource_path=contract.location,
            delimiter="\t" if delimiter == "\t" else delimiter,
        )

    def query_variant(
        self,
        *,
        gene: str | None,
        hgvs: Iterable[str] = (),
        caid: str | None = None,
        clinvar_id: str | None = None,
    ) -> list[ClinGenVariantAssertion]:
        if not self.path.is_file():
            raise ClinGenVariantPathogenicityError(
                f"ClinGen Variant Pathogenicity file not found: {self.path}"
            )

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

            exact_identifier = bool(
                (wanted_caid and row_caid == wanted_caid)
                or (wanted_clinvar and row_clinvar == wanted_clinvar)
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
            delimiter = self.delimiter or (
                "\t" if "\t" in sample and sample.count("\t") >= sample.count(",") else ","
            )
            reader = csv.DictReader(handle, delimiter=delimiter)
            if not reader.fieldnames:
                raise ClinGenVariantPathogenicityError(
                    "ClinGen Variant Pathogenicity file has no header"
                )
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
            key = name.strip().lower().replace(" ", "_").replace("-", "_")
            value = normalized.get(key)
            if value not in (None, ""):
                return str(value).strip()
        return None

    @classmethod
    def _normalize_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        # Current ERepo summary exports expose both "Preferred Variant Title"
        # and "HGVS". Preserve all expressions rather than assuming one
        # transcript/build representation is authoritative.
        hgvs_values = []
        for field in (
            cls._key(row, "hgvs"),
            cls._key(row, "hgvs_expressions"),
            cls._key(row, "preferred_variant_title"),
        ):
            hgvs_values.extend(cls._split_list(field))
        hgvs = tuple(dict.fromkeys(x for x in hgvs_values if x))

        met_codes = cls._split_codes(
            cls._key(row, "met_codes", "met_criteria", "met_criteria_codes")
        )
        unmet_codes = cls._split_codes(
            cls._key(row, "unmet_codes", "unmet_criteria", "unmet_criteria_codes")
        )

        criterion_assertions = tuple(
            [
                *(
                    ClinGenCriterionAssertion(code=code, status="MET")
                    for code in met_codes
                ),
                *(
                    ClinGenCriterionAssertion(code=code, status="NOT_MET")
                    for code in unmet_codes
                ),
            ]
        )

        return {
            "classification": cls._key(row, "classification"),
            "condition": cls._key(row, "condition", "disease"),
            "inheritance": cls._key(
                row, "moi", "inheritance", "mode_of_inheritance"
            ),
            "gene": cls._key(row, "gene", "gene_symbol"),
            "mondo_id": cls._key(row, "mondo", "mondo_id", "disease_id"),
            "preferred_variant_title": cls._key(
                row, "preferred_variant_title", "preferred_variant"
            ),
            "hgvs": hgvs,
            "caid": cls._key(row, "caid", "ca_id"),
            "clinvar_id": cls._key(row, "clinvar_id", "cvid", "cv_id"),
            "expert_panel": cls._key(row, "expert_panel", "vcep"),
            "met_codes": met_codes,
            "unmet_codes": unmet_codes,
            "criterion_assertions": criterion_assertions,
            "version": cls._key(row, "version"),
            "published_date": cls._key(
                row, "published_date", "approved_on", "classification_date"
            ),
        }

    @classmethod
    def _to_assertion(
        cls, normalized: dict[str, Any], raw: dict[str, Any]
    ) -> ClinGenVariantAssertion:
        canonical = json.dumps(
            raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
        digest = hashlib.sha256(canonical).hexdigest()

        # ERepo summary exports do not expose the classification UUID. Use a
        # deterministic composite identity and retain the complete record hash.
        identity_parts = [
            normalized.get("caid"),
            normalized.get("clinvar_id"),
            normalized.get("gene"),
            normalized.get("condition"),
            normalized.get("version"),
            normalized.get("expert_panel"),
            normalized.get("preferred_variant_title"),
            "|".join(normalized.get("hgvs") or ()),
        ]
        record_id = "|".join(str(x) for x in identity_parts if x)
        if not record_id:
            raise ClinGenVariantPathogenicityError(
                "Matched ClinGen record has no stable identifying fields"
            )

        payload = dict(raw)
        payload.update(
            {
                "mondo_id": normalized.get("mondo_id"),
                "preferred_variant_title": normalized.get("preferred_variant_title"),
                "criterion_assertions": [
                    {
                        "code": item.code,
                        "status": item.status,
                        "source": item.source,
                        "rationale": item.rationale,
                    }
                    for item in normalized.get("criterion_assertions", ())
                ],
                "criterion_detail_available": False,
                "criterion_detail_note": (
                    "The governed ERepo summary export supplies met/not-met codes. "
                    "Per-code narrative evidence is available on individual ERepo "
                    "classification records but is not fabricated here."
                ),
            }
        )

        return ClinGenVariantAssertion(
            classification=normalized.get("classification"),
            condition=normalized.get("condition"),
            inheritance=normalized.get("inheritance"),
            gene=normalized.get("gene"),
            hgvs=normalized.get("hgvs", ()),
            caid=normalized.get("caid"),
            clinvar_id=normalized.get("clinvar_id"),
            expert_panel=normalized.get("expert_panel"),
            met_codes=normalized.get("met_codes", ()),
            unmet_codes=normalized.get("unmet_codes", ()),
            criterion_assertions=normalized.get("criterion_assertions", ()),
            version=normalized.get("version"),
            published_date=normalized.get("published_date"),
            source_record_id=f"ERepo:{record_id}",
            payload=payload,
            record_sha256=digest,
        )

    @staticmethod
    def _split_list(value: str | None) -> list[str]:
        if not value:
            return []
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except json.JSONDecodeError:
                pass
        return [
            item.strip().strip('"').strip("'")
            for item in text.replace("\\n", "|").split("|")
            if item.strip()
        ]

    @classmethod
    def _split_codes(cls, value: str | None) -> tuple[str, ...]:
        if not value:
            return ()
        if value.startswith("[") and value.endswith("]"):
            values = cls._split_list(value)
        else:
            values = [
                item.strip()
                for item in value.replace(";", ",").split(",")
                if item.strip()
            ]
        return tuple(dict.fromkeys(values))

    @staticmethod
    def _norm_hgvs(value: str) -> str:
        return " ".join(str(value).strip().split()).upper()

    @staticmethod
    def _norm_id(value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip().upper()
        return text or None
