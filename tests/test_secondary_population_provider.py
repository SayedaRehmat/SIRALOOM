import hashlib
from types import SimpleNamespace

import pytest

from backend.app.adapters.population import secondary
from backend.app.adapters.population.secondary import (
    LocalTabixSecondaryPopulationProvider,
    SecondaryPopulationProviderError,
)


def contract(**toolchain):
    from backend.app.domain.resource_source_contract import ResourceExecutionContract
    return ResourceExecutionContract(
        provider_id="1000GENOMES", provider_version="phase3", access_method="LOCAL",
        endpoint=None, location="/resources/1000g.vcf.gz", dataset="phase3",
        execution_scope="ORGANIZATION_MANAGED", toolchain=toolchain,
    )


def test_requires_explicit_info_mapping():
    with pytest.raises(SecondaryPopulationProviderError, match="info_fields"):
        LocalTabixSecondaryPopulationProvider.from_execution_contract(contract())


def test_requires_frequency_or_count_denominator_mapping():
    with pytest.raises(SecondaryPopulationProviderError, match="AF or both AC and AN"):
        LocalTabixSecondaryPopulationProvider.from_execution_contract(contract(
            info_fields={"AC": "AC"},
        ))


def test_rejects_unknown_contig_policy():
    with pytest.raises(SecondaryPopulationProviderError, match="contig_policy"):
        LocalTabixSecondaryPopulationProvider.from_execution_contract(contract(
            info_fields={"AF": "AF"},
            contig_policy="SILENT_ALIAS",
        ))


def test_rejects_remote_execution():
    from backend.app.domain.resource_source_contract import ResourceExecutionContract
    c = ResourceExecutionContract(
        provider_id="TOPMED", provider_version="1", access_method="API",
        endpoint="https://example.test", location=None, dataset="topmed",
        execution_scope="ORGANIZATION_MANAGED", toolchain={"info_fields": {"AF": "AF"}},
    )
    with pytest.raises(SecondaryPopulationProviderError, match="LOCAL/FILE"):
        LocalTabixSecondaryPopulationProvider.from_execution_contract(c)


def test_local_provider_fails_closed_until_case_bound_executor_is_injected():
    provider = LocalTabixSecondaryPopulationProvider.from_execution_contract(contract(
        info_fields={"AC": "AC", "AN": "AN"},
    ))
    variant = SimpleNamespace(chromosome="1", position=100, reference="A", alternate="G")
    with pytest.raises(SecondaryPopulationProviderError, match="GOVERNED_EXECUTION_UNAVAILABLE"):
        provider.query_variant(variant)


def test_info_parser_and_alt_specific_values():
    info = secondary._parse_info("AC=2,4;AN=100;AF=0.02,0.04;nhomalt=0,1")
    assert secondary._array_int(info["AC"], 1) == 4
    assert secondary._scalar_int(info["AN"]) == 100
    assert secondary._array_value(info["AF"], 1) == "0.04"
    assert secondary._array_int(info["nhomalt"], 1) == 1


@pytest.mark.parametrize(
    ("info", "message"),
    [
        ("AC=2;AN=-1;AF=0.02", "allele number cannot be negative"),
        ("AC=-1;AN=100;AF=0.02", "allele count cannot be negative"),
        ("AC=101;AN=100;AF=1.0", "cannot exceed allele number"),
        ("AC=1;AN=100;AF=0.02", "inconsistent with AC/AN"),
        ("AC=1;AN=100;AF=0", "inconsistent with AC/AN"),
    ],
)
def test_rejects_invalid_population_metrics(info, message):
    parsed = secondary._parse_info(info)
    ac = secondary._scalar_int(parsed.get("AC"))
    an = secondary._scalar_int(parsed.get("AN"))
    af_text = parsed.get("AF")
    af = secondary._parse_frequency(af_text)
    with pytest.raises(SecondaryPopulationProviderError, match=message):
        secondary._validate_population_metrics(ac=ac, an=an, af=af, af_text=af_text)


@pytest.mark.parametrize("value", ["1.2", "NaN", "inf", "-0.1", "not-a-number"])
def test_rejects_invalid_frequency_values(value):
    with pytest.raises(SecondaryPopulationProviderError):
        secondary._parse_frequency(value)


def test_rounded_source_af_is_validated_then_normalized_from_counts():
    parsed = secondary._parse_info("AC=1;AN=300;AF=0.0033")
    af = secondary._parse_frequency(parsed["AF"])
    result = secondary._validate_population_metrics(
        ac=secondary._scalar_int(parsed["AC"]),
        an=secondary._scalar_int(parsed["AN"]),
        af=af,
        af_text=parsed["AF"],
    )
    assert result == 1 / 300


def test_zero_allele_number_never_produces_af():
    parsed = secondary._parse_info("AC=0;AN=0;AF=0")
    af = secondary._parse_frequency(parsed["AF"])
    result = secondary._validate_population_metrics(
        ac=secondary._scalar_int(parsed["AC"]),
        an=secondary._scalar_int(parsed["AN"]),
        af=af,
        af_text=parsed["AF"],
    )
    assert result is None


def test_contig_aliasing_requires_explicit_contract_policy():
    assert secondary._contigs_match("chr1", "1", "CHR_PREFIX") is True
    assert secondary._contigs_match("chr1", "1", "EXACT") is False


def test_secondary_population_no_data_is_a_limitation_not_pipeline_failure():
    from backend.app.domain.workflow_decision import (
        OutcomeKind,
        WorkflowAction,
        decide_step_outcome,
    )

    decision = decide_step_outcome(
        "population",
        OutcomeKind.NO_DATA,
        code="SECONDARY_POPULATION_NO_DATA",
    )
    assert decision.action is WorkflowAction.CONTINUE_WITH_LIMITATION
