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
import re
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


def _normalize_mondo_id(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    match = re.fullmatch(r"MONDO[:_](\d{7})", raw, flags=re.IGNORECASE)
    if not match:
        raise ClinGenGeneDiseaseValidityError(
            f"ClinGen export contains an invalid MONDO identifier: {raw!r}"
        )
    return f"MONDO:{match.group(1)}"


class ClinGenGeneDiseaseValidityProvider:
    provider_id = "ClinGen Gene-Disease Validity"
    provider_version = "GeneValidity"
    source_url = "https://search.clinicalgenome.org/kb/downloads"
    download_url = "https://search.clinicalgenome.org/kb/gene-validity/download"
    methodology_url = "https://www.clinicalgenome.org/docs/gene-disease-validity-standard-operating-procedure/"
    supported_builds = frozenset({"GRCh37", "GRCh38"})

    def __init__(
        self,
        *,
        resource_path: str,
        delimiter: str | None = None,
        expected_sha256: str | None = None,
        expected_release: str | None = None,
    ) -> None:
        self.path = Path(resource_path)
        self.delimiter = delimiter
        self.expected_release = str(expected_release or "").strip() or None
        if self.expected_release is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.expected_release):
            raise ClinGenGeneDiseaseValidityError("ClinGen resource version must be the exact FILE CREATED date (YYYY-MM-DD)")
        self.release_date: str | None = None
        self._records_by_gene: dict[str, tuple[GeneDiseaseAssertion, ...]] | None = None
        self.sha256: str | None = None
        expected = str(expected_sha256 or "").strip().lower().removeprefix("sha256:")
        if expected_sha256 is not None and (len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected)):
            raise ClinGenGeneDiseaseValidityError("ClinGen Gene-Disease Validity requires a valid SHA-256 pin")
        if expected_sha256 is not None:
            if not self.path.is_file():
                raise ClinGenGeneDiseaseValidityError(f"ClinGen Gene-Disease Validity file not found: {self.path}")
            self.sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()
            if self.sha256 != expected:
                raise ClinGenGeneDiseaseValidityError("ClinGen Gene-Disease Validity checksum does not match the approved resource")

    @classmethod
    def from_execution_contract(cls, resolved: Any, *, expected_sha256: str | None = None):
        contract = resolved.contract
        if contract.provider_id != cls.provider_id:
            raise ClinGenGeneDiseaseValidityError("ClinGen Gene-Disease Validity provider identity does not match")
        if contract.provider_version != cls.provider_version:
            raise ClinGenGeneDiseaseValidityError("ClinGen Gene-Disease Validity provider version does not match")
        if contract.access_method not in {"LOCAL", "FILE", "LOCAL_ONLY"}:
            raise ClinGenGeneDiseaseValidityError(
                "ClinGen Gene-Disease Validity requires the governed official CSV download as a local/file resource"
            )
        if not contract.location:
            raise ClinGenGeneDiseaseValidityError("ClinGen Gene-Disease Validity resource location is required")
        delimiter = (contract.toolchain or {}).get("delimiter")
        if delimiter not in {None, ",", "\t"}:
            raise ClinGenGeneDiseaseValidityError("delimiter must be ',' or '\\t'")
        release = str(resolved.resource_version or "").strip()
        declared_release = str((contract.toolchain or {}).get("release") or "").strip()
        if declared_release and declared_release != release:
            raise ClinGenGeneDiseaseValidityError(
                "ClinGen execution contract release does not match the registered resource version"
            )
        return cls(
            resource_path=contract.location,
            delimiter="\t" if delimiter == "\t" else delimiter,
            expected_sha256=expected_sha256,
            expected_release=release,
        )

    def _load_index(self) -> dict[str, tuple[GeneDiseaseAssertion, ...]]:
        if self._records_by_gene is not None:
            return self._records_by_gene
        if not self.path.is_file():
            raise ClinGenGeneDiseaseValidityError(f"ClinGen Gene-Disease Validity file not found: {self.path}")
        if self.sha256 is None:
            self.sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()
        raw_text = self.path.read_text(encoding="utf-8-sig")
        # Some governed transfers preserve newline characters as the literal two-character
        # sequence \n. Normalize this transport representation before parsing release metadata
        # and CSV rows. The acquired source bytes remain unchanged.
        raw_text = raw_text.replace("\\n", "\n")
        release_match = re.search(r"FILE CREATED:\s*(\d{4}-\d{2}-\d{2})", raw_text, flags=re.IGNORECASE)
        self.release_date = release_match.group(1) if release_match else None
        if self.expected_release is not None and self.release_date != self.expected_release:
            raise ClinGenGeneDiseaseValidityError(
                f"ClinGen release mismatch: resource pins {self.expected_release}, file declares {self.release_date or 'no FILE CREATED date'}"
            )
        from io import StringIO
        sample = raw_text[:8192]
        delimiter = self.delimiter or ("\t" if "\t" in sample and sample.count("\t") >= sample.count(",") else ",")
        reader = csv.reader(StringIO(raw_text), delimiter=delimiter)
        rows = list(reader)

        # Some exported fixtures/pipeline transfers encode line breaks literally
        # as the two characters \\n. Normalize those before header detection so
        # the parser remains tolerant without changing the official field names.
        expanded: list[list[str]] = []
        for row in rows:
            if len(row) == 1 and "\\n" in row[0]:
                expanded.extend(list(csv.reader(row[0].split("\\n"), delimiter=delimiter)))
            else:
                expanded.append(row)
        rows = expanded

        header_index = next(
            (i for i, row in enumerate(rows) if row and any(
                "GENE SYMBOL" == cell.strip().upper() for cell in row
            )),
            None,
        )
        if header_index is None:
            raise ClinGenGeneDiseaseValidityError("ClinGen Gene-Disease Validity header not found")

        headers = [x.strip() for x in rows[header_index]]
        if len({header.casefold() for header in headers}) != len(headers):
            raise ClinGenGeneDiseaseValidityError("ClinGen Gene-Disease Validity export contains duplicate headers")
        indexed: dict[str, list[GeneDiseaseAssertion]] = {}
        for row in rows[header_index + 1:]:
            if not row or row[0].startswith("+"):
                continue
            if len(row) > len(headers) and any(str(value).strip() for value in row[len(headers):]):
                raise ClinGenGeneDiseaseValidityError("ClinGen Gene-Disease Validity row contains unexpected extra columns")
            if len(row) < len(headers):
                row = row + [""] * (len(headers) - len(row))
            data = {headers[i]: row[i].strip() for i in range(len(headers))}
            gene_symbol = data.get("GENE SYMBOL", "").upper()
            if not gene_symbol:
                continue
            canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
            digest = hashlib.sha256(canonical).hexdigest()
            report = data.get("ONLINE REPORT") or None
            record_id = report.rsplit("/", 1)[-1] if report else ""
            hgnc_id = data.get("GENE ID (HGNC)") or None
            if hgnc_id and not re.fullmatch(r"HGNC:\d+", hgnc_id, flags=re.IGNORECASE):
                raise ClinGenGeneDiseaseValidityError(
                    f"ClinGen export contains an invalid HGNC identifier: {hgnc_id!r}"
                )
            mondo_id = _normalize_mondo_id(data.get("DISEASE ID (MONDO)"))
            if not record_id:
                record_id = f"{gene_symbol}:{mondo_id or data.get('DISEASE LABEL','')}:{digest[:16]}"
            assertion = GeneDiseaseAssertion(
                gene=gene_symbol,
                hgnc_id=hgnc_id,
                disease=data.get("DISEASE LABEL", ""),
                mondo_id=mondo_id,
                moi=data.get("MOI") or None,
                sop=data.get("SOP") or None,
                classification=data.get("CLASSIFICATION") or None,
                online_report=report,
                classification_date=data.get("CLASSIFICATION DATE") or None,
                expert_panel=data.get("GCEP") or None,
                source_record_id=f"ClinGen-GDV:{record_id}:{digest[:16]}",
                payload=data,
                record_sha256=digest,
            )
            indexed.setdefault(gene_symbol, []).append(assertion)
        self._records_by_gene = {gene: tuple(records) for gene, records in indexed.items()}
        return self._records_by_gene

    def query_gene(self, *, gene: str) -> list[GeneDiseaseAssertion]:
        wanted = str(gene or "").strip().upper()
        if not wanted:
            return []
        return list(self._load_index().get(wanted, ()))
