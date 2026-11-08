from __future__ import annotations

import hashlib

import pytest

from backend.app.adapters.gene_disease.g2p import G2PError, G2PProvider
from backend.app.domain.resource_source_contract import ResourceExecutionContract


HEADER = (
    "G2P ID,Gene symbol,Disease name,Disease MONDO,Allelic requirement,"
    "Molecular mechanism,Confidence,Publication,Publication phenotypes,"
    "Cross cutting modifier,Publication variant types,"
    "Evidence based variant consequence,Publication molecular mechanism evidence\n"
)


def _write(path, rows=None):
    path.write_text(HEADER + (rows or (
        "G2P00123,GENE1,Example disorder,MONDO:0000001,biallelic_autosomal,"
        "loss of function,definitive,PMID:123,HP:0001250;HP:0001263,"
        "consanguinity,frameshift_variant;stop_gained,absent_gene_product,"
        "functional evidence\n"
    )), encoding="utf-8")
    return path


def test_g2p_provider_pins_release_checksum_and_preserves_model_fields(tmp_path):
    path = _write(tmp_path / "g2p.csv")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    provider = G2PProvider(resource_path=str(path), expected_sha256=digest, release="v21.0.0")
    models = provider.query_gene(gene="gene1")

    assert len(models) == 1
    model = models[0]
    assert model.source_record_id == "G2P:G2P00123"
    assert model.disease_mondo == "MONDO:0000001"
    assert model.allelic_requirement == "biallelic_autosomal"
    assert model.molecular_mechanism == "loss of function"
    assert model.confidence == "definitive"
    assert model.publications == ("PMID:123",)
    assert model.phenotypes == ("HP:0001250", "HP:0001263")
    assert model.cross_cutting_modifiers == ("consanguinity",)
    assert model.record_sha256


def test_g2p_provider_requires_local_execution_and_explicit_resource_pins(tmp_path):
    path = _write(tmp_path / "g2p.csv")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    contract = ResourceExecutionContract(
        provider_id="Gene2Phenotype",
        provider_version="G2P_CSV",
        access_method="LOCAL",
        endpoint=None,
        location=str(path),
        dataset="v21.0.0",
        toolchain={"release": "v21.0.0", "sha256": digest},
    )
    assert G2PProvider.from_execution_contract(type("Resolved", (), {"contract": contract})()).release == "v21.0.0"

    remote = ResourceExecutionContract(
        provider_id="Gene2Phenotype",
        provider_version="G2P_CSV",
        access_method="HTTPS",
        endpoint="https://www.ebi.ac.uk/gene2phenotype/",
        location=None,
        dataset="v21.0.0",
        toolchain={"release": "v21.0.0", "sha256": digest},
    )
    with pytest.raises(G2PError, match="local export"):
        G2PProvider.from_execution_contract(type("Resolved", (), {"contract": remote})())


def test_g2p_provider_rejects_wrong_checksum_release_and_malformed_mondo(tmp_path):
    path = _write(tmp_path / "g2p.csv")
    with pytest.raises(G2PError, match="checksum"):
        G2PProvider(resource_path=str(path), expected_sha256="0" * 64, release="v21.0.0")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(G2PError, match="semantic version"):
        G2PProvider(resource_path=str(path), expected_sha256=digest, release="latest")
    malformed = _write(
        tmp_path / "bad.csv",
        "G2P00123,GENE1,Example disorder,MONDO:1,biallelic_autosomal,"
        "loss of function,definitive,PMID:123,HP:0001250,,,,\n",
    )
    with pytest.raises(G2PError, match="MONDO"):
        G2PProvider(resource_path=str(malformed), expected_sha256=hashlib.sha256(malformed.read_bytes()).hexdigest(), release="v21.0.0")
