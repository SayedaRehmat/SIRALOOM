import pytest

from backend.app.adapters.population.gnomad import (
    GnomADProviderError,
    LocalGnomADTabixProvider,
    _array_count,
    _array_float,
    _array_text,
    _array_value,
    _nonnegative_count,
    _parse_info,
    _validate_source_af_matches_counts,
)
from backend.app.domain.schemas import CanonicalVariant


def test_gnomad_info_array_parsing_is_alternate_specific():
    info = _parse_info("AC=2,5;AF=0.1,0.2;AC_mid=1,3;AN_mid=100;nhomalt_mid=0,1")
    assert _array_value(info["AC"], 1) == 5
    assert _array_float(info["AF"], 1) == 0.2
    assert _array_value(info["AC_mid"], 0) == 1
    assert _array_value(info["nhomalt_mid"], 1) == 1


def test_gnomad_missing_values_are_not_converted_to_zero():
    info = _parse_info("AC=.;AN=100;AF=0.25;nhomalt=.;AC_mid=0;AN_mid=.;AF_mid=0")
    assert _array_count(info["AC"], 0, field="AC") is None
    assert _array_count(info["nhomalt"], 0, field="nhomalt") is None
    assert _array_value(info["AN_mid"], 0) is None
    assert _array_text(info["AF"], 0) == "0.25"


@pytest.mark.parametrize("value", ["-1", "1.2", "NaN", "not-an-integer", "+-1"])
def test_gnomad_counts_reject_negative_or_malformed_values(value):
    with pytest.raises(GnomADProviderError, match="non-negative integer"):
        _nonnegative_count(value, field="AC")


@pytest.mark.parametrize("value", ["-0.01", "1.01", "nan", "inf", "not-a-float"])
def test_gnomad_frequency_rejects_nonfinite_or_out_of_range_values(value):
    with pytest.raises(GnomADProviderError, match="frequency|between zero and one"):
        _array_float(value, 0)


@pytest.mark.parametrize(
    ("ac", "an", "af"),
    [
        (1, 100, "0.02"),
        (10, 100, "0.11"),
        (1, 100, "0"),
        (101, 100, "1.01"),
    ],
)
def test_gnomad_source_af_must_agree_with_counts(ac, an, af):
    with pytest.raises(GnomADProviderError, match="inconsistent with AC/AN|finite frequency"):
        _validate_source_af_matches_counts(af, ac=ac, an=an, context="global")


def test_gnomad_source_af_rounding_is_checked_at_source_precision():
    _validate_source_af_matches_counts("0.0033", ac=1, an=300, context="global")


def test_gnomad_source_af_is_not_authoritative_without_both_counts():
    _validate_source_af_matches_counts("0.25", ac=None, an=100, context="global")
    _validate_source_af_matches_counts("0.25", ac=1, an=None, context="global")


def test_gnomad_array_requires_value_for_requested_alternate():
    with pytest.raises(GnomADProviderError, match="no value for the requested alternate"):
        _array_text("0.1", 1)


def test_local_gnomad_query_fails_closed_without_case_bound_oci_execution():
    provider = LocalGnomADTabixProvider("/qualified/gnomad.vcf.gz")
    variant = CanonicalVariant(
        genome_build="GRCh38", chromosome="1", position=555, reference="T", alternate="C"
    )
    with pytest.raises(GnomADProviderError, match="LOCAL_GNOMAD_GOVERNED_EXECUTION_UNAVAILABLE"):
        provider.query_variant(variant)
