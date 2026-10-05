from types import SimpleNamespace
import pytest

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


def test_reads_alt_specific_fields(monkeypatch):
    provider = LocalTabixSecondaryPopulationProvider.from_execution_contract(contract(
        info_fields={"AC": "AC", "AN": "AN", "AF": "AF", "HOM_ALT": "nhomalt"},
        population_code="GLOBAL", population_label="1000 Genomes Phase 3",
    ))
    monkeypatch.setattr(
        "backend.app.adapters.population.secondary.subprocess.run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stderr="",
            stdout="1\t100\trs1\tA\tC,G\t.\tPASS\tAC=2,4;AN=100;AF=0.02,0.04;nhomalt=0,1\n",
        ),
    )
    variant = SimpleNamespace(chromosome="1", position=100, reference="A", alternate="G")
    obs = provider.query_variant(variant)[0]
    assert (obs.allele_count, obs.allele_number, obs.allele_frequency, obs.homozygote_count) == (4, 100, 0.04, 1)


def test_rejects_remote_execution():
    from backend.app.domain.resource_source_contract import ResourceExecutionContract
    c = ResourceExecutionContract(
        provider_id="TOPMED", provider_version="1", access_method="API",
        endpoint="https://example.test", location=None, dataset="topmed",
        execution_scope="ORGANIZATION_MANAGED", toolchain={"info_fields": {"AF": "AF"}},
    )
    with pytest.raises(SecondaryPopulationProviderError, match="LOCAL/FILE"):
        LocalTabixSecondaryPopulationProvider.from_execution_contract(c)


def test_secondary_population_no_data_is_a_limitation_not_pipeline_failure():
    from backend.app.domain.workflow_decision import OutcomeKind, WorkflowAction, decide_step_outcome

    decision = decide_step_outcome(
        "population",
        OutcomeKind.NO_DATA,
        code="SECONDARY_POPULATION_NO_DATA",
    )
    assert decision.action is WorkflowAction.CONTINUE_WITH_LIMITATION
