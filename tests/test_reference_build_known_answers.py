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
