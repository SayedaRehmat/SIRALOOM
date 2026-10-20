from pathlib import Path

from backend.app.adapters.population.gnomad import LocalGnomADTabixProvider, _parse_info, _array_value, _array_float
from backend.app.domain.schemas import CanonicalVariant


def test_gnomad_info_array_parsing():
    info = _parse_info("AC=2,5;AF=0.1,0.2;AC_mid=1,3;AN_mid=100;nhomalt_mid=0,1")
    assert _array_value(info["AC"], 1) == 5
    assert _array_float(info["AF"], 1) == 0.2
    assert _array_value(info["AC_mid"], 0) == 1
    assert _array_value(info["nhomalt_mid"], 1) == 1


def test_local_gnomad_no_exact_record_has_provenance_and_no_frequency(monkeypatch):
    from types import SimpleNamespace

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
