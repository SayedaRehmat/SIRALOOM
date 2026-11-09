from __future__ import annotations

import hashlib

import pytest

from backend.app.adapters.gene_disease.g2p import G2PError, G2PProvider
from backend.app.domain.resource_source_contract import ResourceExecutionContract


HEADER = (
    "G2P ID,Gene symbol,HGNC ID,Disease name,Disease MONDO,Allelic requirement,"
    "Molecular mechanism,Confidence,Publication,Publication phenotypes,"
    "Cross cutting modifier,Publication variant types,"
    "Evidence based variant consequence,Publication molecular mechanism evidence\n"
)


def _write(path, rows=None):
    path.write_text(HEADER + (rows or (
        "G2P00123,GENE1,HGNC:1,Example disorder,MONDO:0000001,biallelic_autosomal,"
        "loss of function,definitive,PMID:123,HP:0001250;HP:0001263,"
        "consanguinity,frameshift_variant;stop_gained,absent_gene_product,"
        "functional evidence\n"
    )), encoding="utf-8")
    return path


def test_g2p_provider_pins_release_checksum_and_preserves_model_fields(tmp_path):
    path = _write(tmp_path / "g2p.csv")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    provider = G2PProvider(resource_path=str(path), expected_sha256=digest, release="2026-11-08")
    models = provider.query_gene(gene="gene1")

    assert len(models) == 1
    model = models[0]
    assert model.source_record_id == "G2P:G2P00123"
    assert model.hgnc_id == "HGNC:1"
    assert model.disease_mondo == "MONDO:0000001"
    assert model.allelic_requirement == "biallelic_autosomal"
    assert model.molecular_mechanism == "loss of function"
    assert model.confidence == "definitive"
    assert model.publications == ("PMID:123",)
    assert model.phenotypes == ("HP:0001250", "HP:0001263")
    assert model.cross_cutting_modifiers == ("consanguinity",)
    assert model.record_sha256
    assert model.inheritance_modes == ("AUTOSOMAL_RECESSIVE",)
    assert model.penetrance == {"status": "NOT_RECORDED", "source": "NOT_RECORDED_IN_G2P"}


def test_g2p_provider_requires_local_execution_and_explicit_resource_pins(tmp_path):
    path = _write(tmp_path / "g2p.csv")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    contract = ResourceExecutionContract(
        provider_id="Gene2Phenotype",
        provider_version="G2P_CSV",
        access_method="LOCAL",
        endpoint=None,
        location=str(path),
        dataset="2026-11-08",
        toolchain={"release": "2026-11-08", "sha256": digest},
    )
    assert G2PProvider.from_execution_contract(type("Resolved", (), {"contract": contract})()).release == "2026-11-08"

    remote = ResourceExecutionContract(
        provider_id="Gene2Phenotype",
        provider_version="G2P_CSV",
        access_method="HTTPS",
        endpoint="https://www.ebi.ac.uk/gene2phenotype/",
        location=None,
        dataset="2026-11-08",
        toolchain={"release": "2026-11-08", "sha256": digest},
    )
    with pytest.raises(G2PError, match="local export"):
        G2PProvider.from_execution_contract(type("Resolved", (), {"contract": remote})())


def test_g2p_provider_rejects_wrong_checksum_release_and_malformed_mondo(tmp_path):
    path = _write(tmp_path / "g2p.csv")
    with pytest.raises(G2PError, match="checksum"):
        G2PProvider(resource_path=str(path), expected_sha256="0" * 64, release="2026-11-08")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(G2PError, match="release"):
        G2PProvider(resource_path=str(path), expected_sha256=digest, release="latest")
    malformed = _write(
        tmp_path / "bad.csv",
        "G2P00123,GENE1,HGNC:1,Example disorder,MONDO:1,biallelic_autosomal,"
        "loss of function,definitive,PMID:123,HP:0001250,,,,\n",
    )
    with pytest.raises(G2PError, match="MONDO"):
        G2PProvider(resource_path=str(malformed), expected_sha256=hashlib.sha256(malformed.read_bytes()).hexdigest(), release="2026-11-08")


@pytest.mark.parametrize(
    ("allelic_requirement", "expected"),
    [
        ("monoallelic_autosomal", ("AUTOSOMAL_DOMINANT",)),
        ("biallelic_autosomal", ("AUTOSOMAL_RECESSIVE",)),
        ("monoallelic_X_hemizygous", ("X_LINKED_RECESSIVE",)),
        ("monoallelic_X_heterozygous", ("X_LINKED_DOMINANT",)),
        ("monoallelic_Y_hemizygous", ("Y_LINKED",)),
        ("monoallelic_y_hemizygous", ("Y_LINKED",)),
        ("semidominant", ("AUTOSOMAL_SEMIDOMINANT",)),
        ("unrecognized_requirement", ("UNKNOWN",)),
    ],
)
def test_g2p_allelic_requirement_mapping_preserves_dominant_recessive_and_unknown(
    tmp_path, allelic_requirement, expected
):
    path = _write(
        tmp_path / "g2p.csv",
        "G2P00123,GENE1,HGNC:1,Example disorder,MONDO:0000001,"
        f"{allelic_requirement},loss of function,definitive,PMID:123,,,,,\n",
    )
    provider = G2PProvider(
        resource_path=str(path),
        expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        release="2026-11-08",
    )
    assert provider.query_gene(gene="GENE1")[0].inheritance_modes == expected


def test_g2p_is_an_executable_governed_provider():
    from backend.app.domain.provider_registry import register_builtin_providers

    provider = register_builtin_providers().require(
        provider_id=G2PProvider.provider_id,
        provider_version=G2PProvider.provider_version,
    )
    assert provider.descriptor.capabilities
    assert any(capability.value == "GENE_DISEASE" for capability in provider.descriptor.capabilities)


def test_g2p_accepts_date_pinned_archive_release(tmp_path):
    from backend.app.adapters.gene_disease.g2p import G2PError, G2PProvider

    path = tmp_path / "g2p.csv"
    path.write_text(
        "g2p id,gene symbol,hgnc id,disease name,allelic requirement,molecular mechanism,confidence,publication\n"
        "G2P:1,GENE1,HGNC:1,Disease,monoallelic autosomal,loss of function,definitive,PMID:1\n",
        encoding="utf-8",
    )
    import hashlib
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    provider = G2PProvider(
        resource_path=str(path),
        expected_sha256=digest,
        release="2026-11-08",
    )
    assert provider.release == "2026-11-08"



def test_g2p_rejects_malformed_source_native_hgnc_identifier(tmp_path):
    path = _write(
        tmp_path / "bad-hgnc.csv",
        "G2P00123,GENE1,HGNC:bad,Example disorder,MONDO:0000001,biallelic_autosomal,"
        "loss of function,definitive,PMID:123,,,,,\n",
    )
    with pytest.raises(G2PError, match="invalid HGNC"):
        G2PProvider(
            resource_path=str(path),
            expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            release="2026-11-08",
        )



def test_g2p_rejects_duplicate_headers_extra_columns_and_missing_hgnc_column(tmp_path):
    duplicate = tmp_path / "duplicate.csv"
    duplicate.write_text(
        HEADER.replace("Gene symbol,HGNC ID", "Gene symbol,Gene symbol")
        + "G2P00123,GENE1,GENE1,Example disorder,MONDO:0000001,biallelic_autosomal,"
        "loss of function,definitive,PMID:123,,,,,\n",
        encoding="utf-8",
    )
    with pytest.raises(G2PError, match="duplicate"):
        G2PProvider(
            resource_path=str(duplicate),
            expected_sha256=hashlib.sha256(duplicate.read_bytes()).hexdigest(),
            release="2026-11-08",
        )

    extra = tmp_path / "extra.csv"
    extra.write_text(
        HEADER
        + "G2P00123,GENE1,HGNC:1,Example disorder,MONDO:0000001,biallelic_autosomal,"
        "loss of function,definitive,PMID:123,,,,,UNEXPECTED\n",
        encoding="utf-8",
    )
    with pytest.raises(G2PError, match="extra columns"):
        G2PProvider(
            resource_path=str(extra),
            expected_sha256=hashlib.sha256(extra.read_bytes()).hexdigest(),
            release="2026-11-08",
        )

    missing = tmp_path / "missing-hgnc.csv"
    missing.write_text(
        "G2P ID,Gene symbol,Disease name,Disease MONDO,Allelic requirement,Molecular mechanism,Confidence\n"
        "G2P00123,GENE1,Example disorder,MONDO:0000001,biallelic_autosomal,loss of function,definitive\n",
        encoding="utf-8",
    )
    with pytest.raises(G2PError, match="hgnc_id"):
        G2PProvider(
            resource_path=str(missing),
            expected_sha256=hashlib.sha256(missing.read_bytes()).hexdigest(),
            release="2026-11-08",
        )



def test_g2p_rejects_impossible_calendar_release_date(tmp_path):
    path = _write(tmp_path / "g2p.csv")
    with pytest.raises(G2PError, match="calendar date"):
        G2PProvider(
            resource_path=str(path),
            expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            release="2026-13-40",
        )
