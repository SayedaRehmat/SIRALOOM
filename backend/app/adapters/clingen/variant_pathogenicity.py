"""ClinGen Variant Pathogenicity provider.

Consumes the official ClinGen Evidence Repository Variant Pathogenicity CSV/TSV
download as an explicitly governed local/file resource. The provider preserves
VCEP classification, condition, inheritance, variant identity, criterion-level
met/not-met codes, version and expert-panel provenance as source evidence. It
never converts a ClinGen assertion into a SIRALOOM final classification.

The ERepo summary export is a summary-level contract: it exposes ACMG/AMP
criterion codes but not the per-code narrative comments shown on individual
classification records. The governed ERepo classification API is a separate
detail contract and, when selected by the resource execution contract,
SIRALOOM preserves the published SEPIO criterion assessment, outcome,
strength, curator comments and PMIDs when those fields are present.
"""
from __future__ import annotations

import csv
import hashlib
import json
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
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
    pmids: tuple[str, ...] = ()
    strength: str | None = None


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

    def __init__(
        self,
        *,
        resource_path: str | None = None,
        delimiter: str | None = None,
        api_base_url: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.path = Path(resource_path) if resource_path else None
        self.delimiter = "\t" if delimiter == "\\t" else delimiter
        self.api_base_url = (api_base_url or "").rstrip("/")
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_execution_contract(cls, resolved: Any):
        contract = resolved.contract
        if contract.access_method not in {"LOCAL", "FILE", "LOCAL_ONLY", "HTTP_API", "API", "REMOTE_API"}:
            raise ClinGenVariantPathogenicityError(
                "ClinGen Variant Pathogenicity supports governed official CSV/TSV files or the official ERepo REST API"
            )
        if not contract.location:
            raise ClinGenVariantPathogenicityError(
                "ClinGen Variant Pathogenicity resource location is required"
            )
        toolchain = contract.toolchain or {}
        delimiter = toolchain.get("delimiter")
        if delimiter not in {None, ",", "\t"}:
            raise ClinGenVariantPathogenicityError("delimiter must be ',' or '\\t'")
        if contract.access_method in {"HTTP_API", "API", "REMOTE_API"}:
            return cls(api_base_url=str(contract.location).rstrip("/"), timeout_seconds=float(toolchain.get("timeout_seconds", 30.0)))
        return cls(resource_path=contract.location, delimiter="\t" if delimiter == "\t" else delimiter)

    def query_variant(
        self,
        *,
        gene: str | None,
        hgvs: Iterable[str] = (),
        caid: str | None = None,
        clinvar_id: str | None = None,
    ) -> list[ClinGenVariantAssertion]:
        if self.api_base_url:
            return self._query_api(gene=gene, hgvs=hgvs, caid=caid, clinvar_id=clinvar_id)
        if self.path is None or not self.path.is_file():
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

    def _query_api(self, *, gene: str | None, hgvs: Iterable[str], caid: str | None, clinvar_id: str | None) -> list[ClinGenVariantAssertion]:
        """Use the documented ERepo summary-search API followed by full classification retrieval."""
        if caid:
            columns, values = "caId", caid
        elif clinvar_id:
            columns, values = "cvId", clinvar_id
        elif gene:
            columns, values = "gene", gene
        else:
            raise ClinGenVariantPathogenicityError("ERepo API query requires CAID, ClinVar Variation ID, or gene")
        params = [
            ("columns", columns),
            ("values", values),
            ("matchTypes", "exact"),
            ("matchMode", "and"),
            ("pgSize", "100"),
            ("pg", "1"),
        ]
        summary = self._api_get_json("/evrepo/api/summary/classifications", params)
        candidates = self._collect_records(summary)
        wanted_hgvs = {self._norm_hgvs(x) for x in hgvs if x}
        wanted_caid = self._norm_id(caid)
        wanted_cv = self._norm_id(clinvar_id)
        wanted_gene = (gene or "").strip().upper()
        out: list[ClinGenVariantAssertion] = []
        seen: set[str] = set()
        for candidate in candidates:
            uuid = self._find_string(candidate, "uuid", "classification_uuid", "classification_id", "id", "@id")
            if not uuid or uuid in seen:
                continue
            seen.add(uuid)
            document = self._api_get_json(f"/evrepo/api/classification/{quote(uuid, safe='')}", [])
            normalized = self._normalize_api_document(document)
            row_caid = self._norm_id(normalized.get("caid"))
            row_cv = self._norm_id(normalized.get("clinvar_id"))
            row_gene = (normalized.get("gene") or "").upper()
            row_hgvs = {self._norm_hgvs(x) for x in normalized.get("hgvs", ())}
            identifier_match = bool((wanted_caid and row_caid == wanted_caid) or (wanted_cv and row_cv == wanted_cv))
            gene_match = bool(wanted_gene and row_gene == wanted_gene)
            hgvs_match = bool(wanted_hgvs.intersection(row_hgvs))
            if identifier_match or (gene_match and (not wanted_hgvs or hgvs_match)):
                out.append(self._to_assertion(normalized, normalized["raw"]))
        return out

    def _api_get_json(self, path: str, params: list[tuple[str, str]]) -> Any:
        url = f"{self.api_base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "SIRALOOM/1.0"}, method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read()
        except Exception as exc:
            raise ClinGenVariantPathogenicityError(f"ClinGen ERepo API request failed: {url}: {exc}") from exc
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ClinGenVariantPathogenicityError(f"ClinGen ERepo API returned non-JSON content: {url}") from exc

    @classmethod
    def _collect_records(cls, value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            records = [value] if any(str(k).lower() in {"uuid", "classification_uuid", "classification_id", "id", "@id"} for k in value) else []
            for child in value.values():
                records.extend(cls._collect_records(child))
            return records
        if isinstance(value, list):
            records: list[dict[str, Any]] = []
            for child in value:
                records.extend(cls._collect_records(child))
            return records
        return []

    @classmethod
    def _find_string(cls, value: dict[str, Any], *keys: str) -> str | None:
        wanted = {key.lower() for key in keys}
        stack: list[Any] = [value]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                for key, child in current.items():
                    if str(key).lower() in wanted and isinstance(child, str) and child:
                        return child.rsplit("/", 1)[-1]
                    if isinstance(child, (dict, list)):
                        stack.append(child)
            elif isinstance(current, list):
                stack.extend(current)
        return None

    @classmethod
    def _normalize_api_document(cls, document: Any) -> dict[str, Any]:
        """Normalize ERepo JSON while preserving nested criterion evidence."""
        flat: dict[str, Any] = {}

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    lk = str(key).lower()
                    if isinstance(child, (str, int, float, bool)):
                        flat.setdefault(lk, str(child))
                    elif isinstance(child, list):
                        if all(isinstance(item, (str, int, float, bool)) for item in child):
                            flat.setdefault(lk, [str(item) for item in child])
                        else:
                            for item in child:
                                walk(item)
                    else:
                        walk(child)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(document)

        def first(*keys: str) -> str | None:
            wanted = {key.lower().replace("_", "") for key in keys}
            for key, value in flat.items():
                if key.lower().replace("_", "") in wanted and value not in (None, "") and not isinstance(value, list):
                    return str(value).strip()
            return None

        hgvs_values: list[str] = []
        for key in ("hgvs", "hgvs_expression", "hgvs_expressions"):
            value = flat.get(key)
            if isinstance(value, list):
                hgvs_values.extend(str(item).strip() for item in value if str(item).strip())
            elif value:
                hgvs_values.extend(cls._split_list(str(value)))

        met_value = flat.get("met_codes") or flat.get("metcodes") or flat.get("met_criteria") or flat.get("metcriteria")
        unmet_value = flat.get("unmet_codes") or flat.get("unmetcodes") or flat.get("unmet_criteria") or flat.get("unmetcriteria")
        met = cls._split_codes(
            "|".join(str(x) for x in met_value) if isinstance(met_value, list) else met_value
        )
        unmet = cls._split_codes(
            "|".join(str(x) for x in unmet_value) if isinstance(unmet_value, list) else unmet_value
        )
        criteria = list(cls._extract_criterion_assertions(document))
        known = {(item.code, item.status) for item in criteria}
        for code in met:
            if (code, "MET") not in known:
                criteria.append(ClinGenCriterionAssertion(code=code, status="MET"))
        for code in unmet:
            if (code, "NOT_MET") not in known:
                criteria.append(ClinGenCriterionAssertion(code=code, status="NOT_MET"))

        return {
            "classification": first("classification", "assertion"),
            "condition": first("condition", "disease"),
            "inheritance": first("moi", "inheritance", "inheritance_mode"),
            "gene": first("gene", "gene_symbol"),
            "hgvs": tuple(dict.fromkeys(hgvs_values)),
            "caid": first("caid", "ca_id"),
            "clinvar_id": first("cvid", "clinvar_id", "clinvar_variation_id"),
            "expert_panel": first("expert_panel", "vcep"),
            "met_codes": met,
            "unmet_codes": unmet,
            "criterion_assertions": tuple(criteria),
            "version": first("version", "guideline_version"),
            "published_date": first("published_on", "published_date", "approved_on"),
            "preferred_variant_title": first("preferred_variant_title"),
            "mondo_id": first("mondo", "mondo_id"),
            "source_record_id": cls._find_string(
                document, "@id", "uuid", "classification_uuid", "classification_id", "id"
            ),
            "raw": document,
        }

    @classmethod
    def _extract_criterion_assertions(cls, document: Any) -> tuple[ClinGenCriterionAssertion, ...]:
        """Extract criterion assessments from the published ERepo SEPIO structure."""
        found: list[ClinGenCriterionAssertion] = []
        seen: set[tuple[str, str, str | None, tuple[str, ...], str | None]] = set()

        def text_at(value: Any, keys: set[str]) -> str | None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if str(key).lower() in keys and isinstance(child, (str, int, float)):
                        text = str(child).strip()
                        if text:
                            return text
                for child in value.values():
                    result = text_at(child, keys)
                    if result:
                        return result
            elif isinstance(value, list):
                for child in value:
                    result = text_at(child, keys)
                    if result:
                        return result
            return None

        def all_texts(value: Any, keys: set[str]) -> tuple[str, ...]:
            out: list[str] = []
            if isinstance(value, dict):
                for key, child in value.items():
                    if str(key).lower() in keys:
                        if isinstance(child, (str, int, float)):
                            text = str(child).strip()
                            if text:
                                out.append(text)
                        else:
                            out.extend(all_texts(child, keys))
                    else:
                        out.extend(all_texts(child, keys))
            elif isinstance(value, list):
                for child in value:
                    out.extend(all_texts(child, keys))
            return tuple(dict.fromkeys(out))

        def normalize_status(value: str) -> str:
            status = value.strip().upper().replace(" ", "_")
            if status in {"MET", "APPLIED", "TRUE", "PASS", "SUPPORTED"}:
                return "MET"
            if status in {"NOT_MET", "UNMET", "FALSE", "FAIL", "REFUTED"}:
                return "NOT_MET"
            return status

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                criterion = value.get("criterion")
                outcome = value.get("statementOutcome")
                if isinstance(criterion, dict) and isinstance(outcome, dict):
                    code = (
                        criterion.get("label")
                        or criterion.get("code")
                        or criterion.get("id")
                    )
                    status = outcome.get("label") or outcome.get("status")
                    if code and status:
                        strength = None
                        default_strength = criterion.get("defaultStrength")
                        if isinstance(default_strength, dict):
                            strength = default_strength.get("label") or default_strength.get("id")
                        rationale = text_at(
                            value,
                            {"comments", "explanation", "rationale", "summary", "narrative", "notes", "text"},
                        )
                        pmids = cls._normalize_pmids(
                            all_texts(value, {"pmid", "pmids", "pubmed_id", "pubmed_ids"})
                        )
                        item = ClinGenCriterionAssertion(
                            code=str(code).strip(),
                            status=normalize_status(str(status)),
                            source="ClinGen ERepo classification API",
                            rationale=rationale,
                            pmids=pmids,
                            strength=str(strength).strip() if strength else None,
                        )
                        identity = (item.code, item.status, item.rationale, item.pmids, item.strength)
                        if identity not in seen:
                            seen.add(identity)
                            found.append(item)
                # Also support compact API/test representations such as
                # {"code": "PS3", "status": "Met", "explanation": "..."}.
                code = value.get("code") or value.get("criterion_code") or value.get("acmg_code")
                status = value.get("status") or value.get("outcome")
                if code and status and not isinstance(code, (dict, list)) and not isinstance(status, (dict, list)):
                    rationale = text_at(value, {"explanation", "rationale", "summary", "narrative", "comments", "notes", "text"})
                    pmids = cls._normalize_pmids(
                        all_texts(value, {"pmid", "pmids", "pubmed_id", "pubmed_ids"})
                    )
                    strength = text_at(value, {"strength", "modified_strength", "criterion_strength", "evidence_strength"})
                    item = ClinGenCriterionAssertion(
                        code=str(code).strip(),
                        status=normalize_status(str(status)),
                        source="ClinGen ERepo classification API",
                        rationale=rationale,
                        pmids=pmids,
                        strength=strength,
                    )
                    identity = (item.code, item.status, item.rationale, item.pmids, item.strength)
                    if identity not in seen:
                        seen.add(identity)
                        found.append(item)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(document)
        return tuple(found)

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
                        "pmids": list(item.pmids),
                        "strength": item.strength,
                    }
                    for item in normalized.get("criterion_assertions", ())
                ],
                "criterion_detail_available": any(item.rationale or item.pmids or item.strength for item in normalized.get("criterion_assertions", ())),
                "criterion_detail_note": "Criterion codes come from the ERepo summary; governed classification API detail is preserved when returned.",
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
            source_record_id=(
                f"ERepo:{normalized.get('source_record_id')}"
                if normalized.get("source_record_id")
                else f"ERepo:{record_id}"
            ),
            payload=payload,
            record_sha256=digest,
        )

    @staticmethod
    def _normalize_pmids(values: Iterable[str]) -> tuple[str, ...]:
        """Normalize PMID literals and PubMed URLs to stable numeric identifiers."""
        out: list[str] = []
        for value in values:
            text = str(value).strip()
            if not text:
                continue
            candidate = text.rstrip("/").rsplit("/", 1)[-1] if "://" in text else text
            if candidate.lower().startswith("pmid:"):
                candidate = candidate.split(":", 1)[1].strip()
            if candidate.isdigit():
                out.append(candidate)
        return tuple(dict.fromkeys(out))

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
    def _split_codes(cls, value: Any) -> tuple[str, ...]:
        if value is None or value == "":
            return ()
        if isinstance(value, (list, tuple, set)):
            values: list[str] = []
            for item in value:
                if isinstance(item, (list, tuple, set)):
                    values.extend(str(x).strip() for x in item if str(x).strip())
                elif str(item).strip():
                    values.append(str(item).strip())
        else:
            text = str(value).strip()
            if not text:
                return ()
            if text.startswith("[") and text.endswith("]"):
                values = cls._split_list(text)
            else:
                values = [
                    item.strip()
                    for item in text.replace(";", ",").replace("|", ",").split(",")
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
