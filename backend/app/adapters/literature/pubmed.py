"""Retrieval-only NCBI PubMed adapter.

This adapter returns bibliographic candidates. It does not retrieve abstracts,
judge article content, or create pathogenicity evidence. Search terms are built
from an annotated gene and public variant identifiers, never patient metadata.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any
from urllib.parse import urlparse

import httpx

PUBMED_PROVIDER_ID = "PUBMED"
PUBMED_PROVIDER_VERSION = "ncbi-eutils-pubmed-v1"
PUBMED_EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_GENE_SYMBOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,30}$")
_PUBLIC_IDENTIFIER = re.compile(r"^(?:rs[1-9][0-9]*|PMID:[1-9][0-9]*)$", re.IGNORECASE)
_REQUEST_LOCK = Lock()
_LAST_REQUEST_AT = 0.0
_MINIMUM_REQUEST_INTERVAL_SECONDS = 0.34


class PubMedLiteratureError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class PubMedLiteratureCandidate:
    pmid: str
    title: str
    citation: str | None
    publication_year: int | None
    doi: str | None
    source_url: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "pmid": self.pmid,
            "title": self.title,
            "citation": self.citation,
            "publication_year": self.publication_year,
            "doi": self.doi,
            "source_url": self.source_url,
            "curation_status": "UNASSESSED_CANDIDATE",
        }


@dataclass(frozen=True)
class PubMedSearchResult:
    status: str
    query: str
    candidates: tuple[PubMedLiteratureCandidate, ...]
    retrieved_at: str
    response_sha256: str
    result_count: int
    provider_version: str = PUBMED_PROVIDER_VERSION


class PubMedLiteratureProvider:
    """NCBI E-utilities adapter that stores only citation metadata."""

    provider_id = PUBMED_PROVIDER_ID
    provider_version = PUBMED_PROVIDER_VERSION

    def __init__(
        self,
        *,
        endpoint: str,
        contact_email: str,
        tool_name: str = "SIRALOOM",
        api_key: str | None = None,
        timeout_seconds: float = 15.0,
        max_results: int = 10,
        client: httpx.Client | None = None,
    ) -> None:
        parsed = urlparse(endpoint.rstrip("/"))
        if (
            parsed.scheme != "https"
            or parsed.netloc.lower() != "eutils.ncbi.nlm.nih.gov"
            or parsed.path.rstrip("/") != "/entrez/eutils"
        ):
            raise PubMedLiteratureError(
                "PUBMED_ENDPOINT_INVALID",
                "PubMed retrieval requires the official HTTPS NCBI E-utilities endpoint",
            )
        if not contact_email or "@" not in contact_email or any(ch.isspace() for ch in contact_email):
            raise PubMedLiteratureError(
                "PUBMED_CONTACT_REQUIRED",
                "A valid laboratory contact email is required by the NCBI E-utilities contract",
            )
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", tool_name):
            raise PubMedLiteratureError("PUBMED_TOOL_NAME_INVALID", "NCBI tool name is invalid")
        if timeout_seconds <= 0 or not 1 <= max_results <= 50:
            raise PubMedLiteratureError("PUBMED_LIMIT_INVALID", "PubMed timeout or result limit is invalid")
        self.endpoint = endpoint.rstrip("/")
        self.contact_email = contact_email
        self.tool_name = tool_name
        self.api_key = api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
        self.timeout_seconds = timeout_seconds
        self.max_results = max_results
        self._client = client

    @classmethod
    def from_execution_contract(cls, contract) -> "PubMedLiteratureProvider":
        toolchain = dict(contract.toolchain or {})
        return cls(
            endpoint=str(contract.endpoint or ""),
            contact_email=str(toolchain.get("contact_email") or ""),
            tool_name=str(toolchain.get("tool_name") or "SIRALOOM"),
            timeout_seconds=float(toolchain.get("timeout_seconds") or 15.0),
            max_results=int(toolchain.get("max_results") or 10),
        )

    @staticmethod
    def _search_term(gene_symbol: str, identifiers: tuple[str, ...]) -> str:
        gene = gene_symbol.strip()
        if not _GENE_SYMBOL.fullmatch(gene):
            raise PubMedLiteratureError(
                "PUBMED_GENE_SYMBOL_INVALID",
                "Literature search requires a syntactically valid annotated gene symbol",
            )
        terms = [f'"{gene}"[Title/Abstract]']
        for identifier in identifiers:
            value = str(identifier).strip()
            if not _PUBLIC_IDENTIFIER.fullmatch(value):
                raise PubMedLiteratureError(
                    "PUBMED_VARIANT_IDENTIFIER_INVALID",
                    "Only public rs identifiers or PMID identifiers may be added to a gene search",
                )
            terms.append(f'"{value}"[Title/Abstract]')
        if len(terms) > 1:
            return f"({terms[0]}) AND ({' OR '.join(terms[1:])})"
        return terms[0]

    def _get_json(self, client: httpx.Client, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        global _LAST_REQUEST_AT
        with _REQUEST_LOCK:
            delay = _MINIMUM_REQUEST_INTERVAL_SECONDS - (time.monotonic() - _LAST_REQUEST_AT)
            if delay > 0:
                time.sleep(delay)
            _LAST_REQUEST_AT = time.monotonic()
        request_params = {
            **params,
            "tool": self.tool_name,
            "email": self.contact_email,
        }
        if self.api_key:
            request_params["api_key"] = self.api_key
        try:
            response = client.get(endpoint, params=request_params, timeout=self.timeout_seconds)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise PubMedLiteratureError("PUBMED_TIMEOUT", "NCBI PubMed request timed out", retryable=True) from exc
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code in {429, 500, 502, 503, 504}
            code = "PUBMED_RATE_LIMITED" if exc.response.status_code == 429 else "PUBMED_HTTP_ERROR"
            raise PubMedLiteratureError(code, f"NCBI PubMed returned HTTP {exc.response.status_code}", retryable=retryable) from exc
        except httpx.HTTPError as exc:
            raise PubMedLiteratureError("PUBMED_PROVIDER_UNAVAILABLE", "NCBI PubMed is unavailable", retryable=True) from exc
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise PubMedLiteratureError("PUBMED_RESPONSE_INVALID", "NCBI PubMed returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise PubMedLiteratureError("PUBMED_RESPONSE_INVALID", "NCBI PubMed response must be a JSON object")
        return data

    @staticmethod
    def _candidate(pmid: str, payload: dict[str, Any]) -> PubMedLiteratureCandidate:
        title = str(payload.get("title") or "").strip().rstrip(".")
        if not pmid.isdigit() or not title:
            raise PubMedLiteratureError("PUBMED_RECORD_INVALID", "NCBI PubMed citation is missing a PMID or title")
        pubdate = str(payload.get("pubdate") or "")
        year_match = re.search(r"\b(?:18|19|20|21)\d{2}\b", pubdate)
        author_list = payload.get("authors") or []
        first_author = str(author_list[0].get("name") or "").strip() if author_list and isinstance(author_list[0], dict) else ""
        journal = str(payload.get("fulljournalname") or payload.get("source") or "").strip()
        volume = str(payload.get("volume") or "").strip()
        pages = str(payload.get("pages") or "").strip()
        citation_parts = [part for part in (first_author, journal, pubdate, volume, pages) if part]
        article_ids = payload.get("articleids") or []
        doi = next(
            (str(item.get("value") or "").strip() for item in article_ids if isinstance(item, dict) and str(item.get("idtype") or "").lower() == "doi"),
            None,
        )
        return PubMedLiteratureCandidate(
            pmid=pmid,
            title=title,
            citation=". ".join(citation_parts) or None,
            publication_year=int(year_match.group(0)) if year_match else None,
            doi=doi,
            source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        )

    def search_gene(self, *, gene_symbol: str, identifiers: tuple[str, ...] = ()) -> PubMedSearchResult:
        """Search PubMed for bibliographic candidates; do not retrieve abstracts."""
        query = self._search_term(gene_symbol, identifiers)
        search_url = f"{self.endpoint}/esearch.fcgi"
        summary_url = f"{self.endpoint}/esummary.fcgi"
        client = self._client or httpx.Client()
        close_client = self._client is None
        try:
            search_data = self._get_json(
                client,
                search_url,
                {"db": "pubmed", "term": query, "retmode": "json", "retmax": str(self.max_results), "sort": "relevance"},
            )
            search_result = search_data.get("esearchresult")
            if not isinstance(search_result, dict) or not isinstance(search_result.get("idlist"), list):
                raise PubMedLiteratureError("PUBMED_RESPONSE_INVALID", "NCBI PubMed ESearch response lacks idlist")
            ids = [str(item) for item in search_result["idlist"]]
            count_text = str(search_result.get("count") or len(ids))
            if not count_text.isdigit():
                raise PubMedLiteratureError("PUBMED_RESPONSE_INVALID", "NCBI PubMed ESearch count is invalid")
            summary_data: dict[str, Any] = {"result": {"uids": []}}
            if ids:
                summary_data = self._get_json(
                    client,
                    summary_url,
                    {"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
                )
            summary = summary_data.get("result")
            if not isinstance(summary, dict) or not isinstance(summary.get("uids"), list):
                raise PubMedLiteratureError("PUBMED_RESPONSE_INVALID", "NCBI PubMed ESummary response lacks uids")
            if set(map(str, summary["uids"])) != set(ids):
                raise PubMedLiteratureError("PUBMED_RESPONSE_INVALID", "NCBI PubMed ESummary IDs differ from the search result")
            candidates = tuple(
                self._candidate(pmid, summary[pmid])
                for pmid in ids
                if isinstance(summary.get(pmid), dict)
            )
            if len(candidates) != len(ids):
                raise PubMedLiteratureError("PUBMED_RESPONSE_INVALID", "NCBI PubMed ESummary omitted a requested citation")
            snapshot = json.dumps(
                {"search": search_data, "summary": summary_data},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            return PubMedSearchResult(
                status="SUCCESS" if candidates else "SUCCESS_NO_MATCH",
                query=query,
                candidates=candidates,
                retrieved_at=datetime.now(UTC).isoformat(),
                response_sha256=hashlib.sha256(snapshot).hexdigest(),
                result_count=int(count_text),
            )
        finally:
            if close_client:
                client.close()
