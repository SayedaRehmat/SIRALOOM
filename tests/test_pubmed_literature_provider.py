from __future__ import annotations

import httpx
import pytest

from backend.app.adapters.literature.pubmed import (
    PUBMED_EUTILS_BASE,
    PubMedLiteratureError,
    PubMedLiteratureProvider,
)


def _provider(handler):
    return PubMedLiteratureProvider(
        endpoint=PUBMED_EUTILS_BASE,
        contact_email="bioinformatics@example.org",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        timeout_seconds=1,
    )


def test_pubmed_search_returns_citation_candidates_without_abstracts():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/esearch.fcgi"):
            assert request.url.params["db"] == "pubmed"
            assert request.url.params["email"] == "bioinformatics@example.org"
            assert request.url.params["term"] == '("PAH"[Title/Abstract]) AND ("rs5030858"[Title/Abstract])'
            return httpx.Response(200, json={"esearchresult": {"count": "1", "idlist": ["12345678"]}})
        assert request.url.path.endswith("/esummary.fcgi")
        return httpx.Response(
            200,
            json={
                "result": {
                    "uids": ["12345678"],
                    "12345678": {
                        "uid": "12345678",
                        "title": "A relevant study.",
                        "pubdate": "2024 Jan",
                        "fulljournalname": "Journal of Example Medicine",
                        "volume": "7",
                        "pages": "10-20",
                        "authors": [{"name": "Example A"}],
                        "articleids": [{"idtype": "doi", "value": "10.1000/example"}],
                    },
                }
            },
        )

    result = _provider(handler).search_gene(gene_symbol="PAH", identifiers=("rs5030858",))

    assert len(calls) == 2
    assert result.status == "SUCCESS"
    assert result.result_count == 1
    assert len(result.response_sha256) == 64
    candidate = result.candidates[0].as_dict()
    assert candidate == {
        "pmid": "12345678",
        "title": "A relevant study",
        "citation": "Example A. Journal of Example Medicine. 2024 Jan. 7. 10-20",
        "publication_year": 2024,
        "doi": "10.1000/example",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
        "curation_status": "UNASSESSED_CANDIDATE",
    }
    assert "abstract" not in candidate


def test_pubmed_successful_zero_matches_is_distinct_from_provider_failure():
    provider = _provider(
        lambda _request: httpx.Response(200, json={"esearchresult": {"count": "0", "idlist": []}})
    )

    result = provider.search_gene(gene_symbol="PAH")

    assert result.status == "SUCCESS_NO_MATCH"
    assert result.result_count == 0
    assert result.candidates == ()


@pytest.mark.parametrize("gene", ["", "PAH patient 123", "PAH[All Fields]", "P AH"])
def test_pubmed_search_rejects_non_gene_or_injected_query_syntax(gene):
    provider = _provider(lambda _request: pytest.fail("invalid query must not make a network request"))

    with pytest.raises(PubMedLiteratureError, match="gene symbol"):
        provider.search_gene(gene_symbol=gene)


def test_pubmed_search_rejects_non_public_identifier():
    provider = _provider(lambda _request: pytest.fail("invalid identifier must not make a network request"))

    with pytest.raises(PubMedLiteratureError, match="public rs identifiers"):
        provider.search_gene(gene_symbol="PAH", identifiers=("PATIENT-100",))


def test_pubmed_provider_rejects_non_ncbi_endpoint():
    with pytest.raises(PubMedLiteratureError, match="official HTTPS NCBI"):
        PubMedLiteratureProvider(
            endpoint="https://example.org/eutils",
            contact_email="bioinformatics@example.org",
        )


def test_pubmed_provider_requires_ncbi_contact_email():
    with pytest.raises(PubMedLiteratureError) as exc:
        PubMedLiteratureProvider(endpoint=PUBMED_EUTILS_BASE, contact_email="")
    assert exc.value.code == "PUBMED_CONTACT_REQUIRED"


def test_pubmed_invalid_response_is_not_treated_as_no_match():
    provider = _provider(lambda _request: httpx.Response(200, json={"unexpected": {}}))

    with pytest.raises(PubMedLiteratureError) as exc:
        provider.search_gene(gene_symbol="PAH")
    assert exc.value.code == "PUBMED_RESPONSE_INVALID"
