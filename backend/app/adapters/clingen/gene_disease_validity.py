"""ClinGen Gene-Disease Validity provider.

Consumes ClinGen's official Gene-Disease Validity CSV download. Each matched
gene-disease assertion is preserved as contextual gene-disease evidence with
its ClinGen curation identifier, SOP, classification, inheritance and expert
panel. It is not converted into variant pathogenicity.
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ClinGenGeneDiseaseValidityError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeneDiseaseAssertion:
    gene: str
    hgnc_id: str | None
    disease: str
    mondo_id: str | None
    moi: str | None
    sop: str | None
    classification: str | None
    online_report: str | None
    classification_date: str | None
    expert_panel: str | None
    source_record_id: str
    payload: dict[str, Any]
    record_sha256: str


class ClinGenGeneDiseaseValidityProvider:
    provider_id = "ClinGen Gene-Disease Validity"
    provider_version = "GeneValidity"
    supported_builds = frozenset({"GRCh37", "GRCh38"})

    def __init__(self, *, resource_path: str, delimiter: str | None = None) -> None:
        self.path = Path(resource_path)
        self.delimiter = delimiter

    @classmethod
    def from_execution_contract(cls, resolved: Any):
        contract = resolved.contract
        if contract.access_method not in {"LOCAL", "FILE", "LOCAL_ONLY"}:
            raise ClinGenGeneDiseaseValidityError(
                "ClinGen Gene-Disease Validity requires the governed official CSV download as a local/file resource"
            )
        if not contract.location:
            raise ClinGenGeneDiseaseValidityError("ClinGen Gene-Disease Validity resource location is required")
        delimiter = (contract.toolchain or {}).get("delimiter")
        if delimiter not in {None, ",", "\t"}:
            raise ClinGenGeneDiseaseValidityError("delimiter must be ',' or '\\t'")
        return cls(resource_path=contract.location, delimiter="\t" if delimiter == "\t" else delimiter)

    def query_gene(self, *, gene: str) -> list[GeneDiseaseAssertion]:
        wanted = str(gene or "").strip().upper()
        if not wanted:
            return []
        if not self.path.is_file():
            raise ClinGenGeneDiseaseValidityError(f"ClinGen Gene-Disease Validity file not found: {self.path}")

        out: list[GeneDiseaseAssertion] = []
        with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(8192)
            handle.seek(0)
            delimiter = self.delimiter or ("\t" if "\t" in sample and sample.count("\t") >= sample.count(",") else ",")
            reader = csv.reader(handle, delimiter=delimiter)
            rows = list(reader)

        header_index = next((i for i, row in enumerate(rows) if row and "GENE SYMBOL" in row[0].upper()), None)
        if header_index is None:
            raise ClinGenGeneDiseaseValidityError("ClinGen Gene-Disease Validity header not found")

        headers = [x.strip() for x in rows[header_index]]
        for row in rows[header_index + 1:]:
            if not row or row[0].startswith("+"):
                continue
            if len(row) < len(headers):
                row = row + [""] * (len(headers) - len(row))
            data = {headers[i]: row[i].strip() for i in range(len(headers))}
            if data.get("GENE SYMBOL", "").upper() != wanted:
                continue
            canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
            digest = hashlib.sha256(canonical).hexdigest()
            report = data.get("ONLINE REPORT") or None
            record_id = report.rsplit("/", 1)[-1] if report else f"{wanted}:{data.get('DISEASE ID','')}"
            out.append(
                GeneDiseaseAssertion(
                    gene=wanted,
                    hgnc_id=data.get("GENE ID (HGNC)") or None,
                    disease=data.get("DISEASE LABEL", ""),
                    mondo_id=data.get("DISEASE ID (MONDO)") or None,
                    moi=data.get("MOI") or None,
                    sop=data.get("SOP") or None,
                    classification=data.get("CLASSIFICATION") or None,
                    online_report=report,
                    classification_date=data.get("CLASSIFICATION DATE") or None,
                    expert_panel=data.get("GCEP") or None,
                    source_record_id=f"ClinGen-GDV:{record_id}",
                    payload=data,
                    record_sha256=digest,
                )
            )
        return out
