from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.adapters.population.gnomad import LocalGnomADTabixProvider, _parse_info, _array_value, _array_float
from backend.app.domain.schemas import CanonicalVariant


def test_gnomad_info_array_parsing():
    info = _parse_info("AC=2,5;AF=0.1,0.2;AC_mid=1,3;AN_mid=100;nhomalt_mid=0,1")
    assert _array_value(info["AC"], 1) == 5
    assert _array_float(info["AF"], 1) == 0.2
    assert _array_value(info["AC_mid"], 0) == 1
    assert _array_value(info["nhomalt_mid"], 1) == 1


def test_local_gnomad_no_exact_record_has_provenance_and_no_frequency(monkeypatch):
    import backend.app.adapters.population.gnomad as gnomad

    monkeypatch.setattr(
        gnomad.subprocess,
        "Popen",
        lambda *args, **kwargs: SimpleNamespace(
            pid=123, returncode=0,
            communicate=lambda timeout: ("1\t555\t.\tT\tA\t.\tPASS\tAC=4;AN=100\n", ""),
        ),
    )
    provider = LocalGnomADTabixProvider("/qualified/gnomad.vcf.gz")
    observations = provider.query_variant(CanonicalVariant(
        genome_build="GRCh38", chromosome="1", position=555, reference="T", alternate="C"
    ))

    assert {item.availability for item in observations} == {"NOT_FOUND"}
    assert {item.quality_status for item in observations} == {"NO_MATCH"}
    assert all(item.allele_count is None and item.allele_number is None and item.allele_frequency is None for item in observations)
    assert all(len(item.request_fingerprint) == 64 and len(item.response_sha256) == 64 for item in observations)
    assert all(item.request_metadata["resource_location"] == "/qualified/gnomad.vcf.gz" for item in observations)


@pytest.mark.parametrize("denominator", [".", "0"])
def test_local_gnomad_does_not_expose_source_af_without_positive_an(monkeypatch, denominator):
    import backend.app.adapters.population.gnomad as gnomad

    info = (
        f"AC=0;AN={denominator};AF=0;nhomalt=0;"
        f"AC_mid=0;AN_mid={denominator};AF_mid=0;nhomalt_mid=0"
    )
    monkeypatch.setattr(
        gnomad.subprocess,
        "Popen",
        lambda *args, **kwargs: SimpleNamespace(
            pid=123,
            returncode=0,
            communicate=lambda timeout: (f"1\t555\t.\tT\tC\t.\tPASS\t{info}\n", ""),
        ),
    )
    provider = LocalGnomADTabixProvider("/qualified/gnomad.vcf.gz")
    observations = provider.query_variant(CanonicalVariant(
        genome_build="GRCh38", chromosome="1", position=555, reference="T", alternate="C"
    ))

    assert len(observations) == 2
    assert all(item.allele_count == 0 for item in observations)
    assert all(item.allele_number in (None, 0) for item in observations)
    assert all(item.allele_frequency is None for item in observations)
    assert all(item.availability == "NOT_AVAILABLE" for item in observations)


@pytest.mark.parametrize(
    "info",
    [
        "AC=-1;AN=100;AF=0;nhomalt=0;AC_mid=0;AN_mid=100;AF_mid=0;nhomalt_mid=0",
        "AC=0;AN=-1;AF=0;nhomalt=0;AC_mid=0;AN_mid=100;AF_mid=0;nhomalt_mid=0",
        "AC=101;AN=100;AF=1;nhomalt=0;AC_mid=0;AN_mid=100;AF_mid=0;nhomalt_mid=0",
        "AC=0;AN=100;AF=0;nhomalt=-1;AC_mid=0;AN_mid=100;AF_mid=0;nhomalt_mid=0",
        "AC=not-an-integer;AN=100;AF=0;nhomalt=0;AC_mid=0;AN_mid=100;AF_mid=0;nhomalt_mid=0",
    ],
)
def test_local_gnomad_rejects_invalid_count_fields(monkeypatch, info):
    import backend.app.adapters.population.gnomad as gnomad

    monkeypatch.setattr(
        gnomad.subprocess,
        "Popen",
        lambda *args, **kwargs: SimpleNamespace(
            pid=123,
            returncode=0,
            communicate=lambda timeout: (f"1\t555\t.\tT\tC\t.\tPASS\t{info}\n", ""),
        ),
    )
    provider = LocalGnomADTabixProvider("/qualified/gnomad.vcf.gz")

    with pytest.raises(gnomad.GnomADProviderError, match="Local gnomAD"):
        provider.query_variant(CanonicalVariant(
            genome_build="GRCh38", chromosome="1", position=555, reference="T", alternate="C"
        ))


@pytest.mark.parametrize("frequency", ["-0.01", "1.01", "nan", "inf", "not-a-float"])
def test_local_gnomad_rejects_invalid_source_allele_frequency(monkeypatch, frequency):
    import backend.app.adapters.population.gnomad as gnomad

    info = (
        f"AC=1;AN=100;AF={frequency};nhomalt=0;"
        "AC_mid=1;AN_mid=100;AF_mid=0.01;nhomalt_mid=0"
    )
    monkeypatch.setattr(
        gnomad.subprocess,
        "Popen",
        lambda *args, **kwargs: SimpleNamespace(
            pid=123,
            returncode=0,
            communicate=lambda timeout: (f"1\t555\t.\tT\tC\t.\tPASS\t{info}\n", ""),
        ),
    )
    provider = LocalGnomADTabixProvider("/qualified/gnomad.vcf.gz")

    with pytest.raises(gnomad.GnomADProviderError, match="Local gnomAD AF"):
        provider.query_variant(CanonicalVariant(
            genome_build="GRCh38", chromosome="1", position=555, reference="T", alternate="C"
        ))


def test_local_gnomad_does_not_expose_source_af_without_allele_count(monkeypatch):
    import backend.app.adapters.population.gnomad as gnomad

    info = "AC=.;AN=100;AF=0.25;nhomalt=0;AC_mid=.;AN_mid=100;AF_mid=0.25;nhomalt_mid=0"
    monkeypatch.setattr(
        gnomad.subprocess,
        "Popen",
        lambda *args, **kwargs: SimpleNamespace(
            pid=123,
            returncode=0,
            communicate=lambda timeout: (f"1\t555\t.\tT\tC\t.\tPASS\t{info}\n", ""),
        ),
    )
    provider = LocalGnomADTabixProvider("/qualified/gnomad.vcf.gz")
    observations = provider.query_variant(CanonicalVariant(
        genome_build="GRCh38", chromosome="1", position=555, reference="T", alternate="C"
    ))

    assert len(observations) == 2
    assert all(item.allele_count is None for item in observations)
    assert all(item.allele_number == 100 for item in observations)
    assert all(item.allele_frequency is None for item in observations)
    assert all(item.availability == "NOT_AVAILABLE" for item in observations)
