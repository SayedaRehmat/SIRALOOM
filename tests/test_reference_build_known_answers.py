from __future__ import annotations

import os

import pytest

from backend.app.domain import reference as reference_module
from backend.app.domain.reference import EnsemblReference, ReferenceError


class _SequenceResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def read(self) -> bytes:
        return self.payload


@pytest.mark.parametrize(
    ("genome_build", "position", "expected_endpoint"),
    [
        ("GRCh37", 140453136, "https://grch37.rest.ensembl.org"),
        ("GRCh38", 140753336, "https://rest.ensembl.org"),
    ],
)
def test_braf_v600e_known_answer_selects_build_specific_reference_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    genome_build: str,
    position: int,
    expected_endpoint: str,
):
    requests: list[tuple[str, float]] = []

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, timeout))
        return _SequenceResponse(b"A")

    monkeypatch.setattr(reference_module, "urlopen", fake_urlopen)
    reference = EnsemblReference(genome_build, retry_attempts=1)

    observed_reference = reference._fetch_remote("7", position, position)

    assert observed_reference == "A"
    assert requests == [
        (
            f"{expected_endpoint}/sequence/region/human/7:{position}..{position}:1"
            "?content-type=text/plain",
            reference.timeout_seconds,
        )
    ]


def test_reference_provider_rejects_unqualified_genome_build():
    with pytest.raises(ReferenceError) as exc:
        EnsemblReference("GRCh39")

    assert exc.value.code == "ENSEMBL_INVALID_REGION"


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("SIRALOOM_ENABLE_LIVE_REFERENCE_TESTS") != "1",
    reason="Set SIRALOOM_ENABLE_LIVE_REFERENCE_TESTS=1 to query the authoritative Ensembl endpoints",
)
@pytest.mark.parametrize(
    ("genome_build", "position"),
    [
        ("GRCh37", 140453136),
        ("GRCh38", 140753336),
    ],
)
def test_live_ensembl_reference_matches_braf_v600e_known_answer(
    genome_build: str,
    position: int,
):
    """Verify the BRAF V600E reference allele against the selected live assembly."""
    with EnsemblReference(genome_build, retry_attempts=1) as reference:
        assert reference._fetch_remote("7", position, position) == "A"


@pytest.mark.parametrize(
    ("genome_build", "chromosome", "start", "end", "expected_reference", "expected_endpoint"),
    [
        ("GRCh37", "11", 5248232, 5248232, "T", "https://grch37.rest.ensembl.org"),
        ("GRCh38", "11", 5227002, 5227002, "T", "https://rest.ensembl.org"),
        ("GRCh37", "7", 55259515, 55259515, "T", "https://grch37.rest.ensembl.org"),
        ("GRCh38", "7", 55191822, 55191822, "T", "https://rest.ensembl.org"),
        ("GRCh37", "7", 117199646, 117199648, "CTT", "https://grch37.rest.ensembl.org"),
        ("GRCh38", "7", 117559592, 117559594, "CTT", "https://rest.ensembl.org"),
    ],
)
def test_additional_clinvar_known_answers_select_assembly_and_reference_sequence(
    monkeypatch: pytest.MonkeyPatch,
    genome_build: str,
    chromosome: str,
    start: int,
    end: int,
    expected_reference: str,
    expected_endpoint: str,
):
    requests: list[str] = []

    def fake_urlopen(request, timeout):
        requests.append(request.full_url)
        return _SequenceResponse(expected_reference.encode("ascii"))

    monkeypatch.setattr(reference_module, "urlopen", fake_urlopen)
    reference = EnsemblReference(genome_build, retry_attempts=1)

    observed_reference = reference._fetch_remote(chromosome, start, end)

    assert observed_reference == expected_reference
    assert requests == [
        f"{expected_endpoint}/sequence/region/human/{chromosome}:{start}..{end}:1"
        "?content-type=text/plain"
    ]


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("SIRALOOM_ENABLE_LIVE_REFERENCE_TESTS") != "1",
    reason="Set SIRALOOM_ENABLE_LIVE_REFERENCE_TESTS=1 to query authoritative Ensembl endpoints",
)
@pytest.mark.parametrize(
    ("genome_build", "chromosome", "start", "end", "expected_reference"),
    [
        ("GRCh37", "11", 5248232, 5248232, "T"),
        ("GRCh38", "11", 5227002, 5227002, "T"),
        ("GRCh37", "7", 55259515, 55259515, "T"),
        ("GRCh38", "7", 55191822, 55191822, "T"),
        ("GRCh37", "7", 117199646, 117199648, "CTT"),
        ("GRCh38", "7", 117559592, 117559594, "CTT"),
    ],
)
def test_live_ensembl_reference_matches_independent_clinvar_known_answers(
    genome_build: str,
    chromosome: str,
    start: int,
    end: int,
    expected_reference: str,
):
    with EnsemblReference(genome_build, retry_attempts=1) as reference:
        assert reference._fetch_remote(chromosome, start, end) == expected_reference
