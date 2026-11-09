from __future__ import annotations

import hashlib

import pytest

from backend.app.adapters.clingen.gene_disease_validity import (
    ClinGenGeneDiseaseValidityError,
    ClinGenGeneDiseaseValidityProvider,
)
from backend.app.domain.resource_source_contract import ResourceExecutionContract


def _write_export(path):
    path.write_text(
        "CLINGEN GENE VALIDITY CURATIONS\n"
        "FILE CREATED: 2026-11-08\n"
        "GENE SYMBOL,GENE ID (HGNC),DISEASE LABEL,DISEASE ID (MONDO),SOP,CLASSIFICATION,ONLINE REPORT,CLASSIFICATION DATE,GCEP,MOI\n"
        "GENE1,HGNC:1,Example disorder,MONDO_0000001,SOP9,Definitive,"
        "https://search.clinicalgenome.org/kb/gene-validity/example,2026-11-08,Expert Panel,Autosomal recessive inheritance\n",
        encoding="utf-8",
    )
    return path


def test_clingen_gene_disease_validity_pins_release_checksum_and_exact_pair(tmp_path):
    path = _write_export(tmp_path / "clingen.csv")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    provider = ClinGenGeneDiseaseValidityProvider(
        resource_path=str(path),
        expected_sha256=digest,
        expected_release="2026-11-08",
    )
    assertions = provider.query_gene(gene="gene1")
    assert provider.release_date == "2026-11-08"
    assert len(assertions) == 1
    assert assertions[0].gene == "GENE1"
    assert assertions[0].mondo_id == "MONDO:0000001"
    assert assertions[0].classification == "Definitive"
    assert assertions[0].moi == "Autosomal recessive inheritance"
    assert assertions[0].source_record_id.startswith("ClinGen-GDV:")
    assert assertions[0].record_sha256


def test_clingen_gene_disease_validity_rejects_release_or_checksum_drift(tmp_path):
    path = _write_export(tmp_path / "clingen.csv")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ClinGenGeneDiseaseValidityError, match="release mismatch"):
        provider = ClinGenGeneDiseaseValidityProvider(
            resource_path=str(path),
            expected_sha256=digest,
            expected_release="2026-11-07",
        )
        provider.query_gene(gene="GENE1")
    with pytest.raises(ClinGenGeneDiseaseValidityError, match="checksum"):
        ClinGenGeneDiseaseValidityProvider(
            resource_path=str(path),
            expected_sha256="0" * 64,
            expected_release="2026-11-08",
        )


def test_clingen_execution_contract_uses_registered_resource_release(tmp_path):
    path = _write_export(tmp_path / "clingen.csv")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    contract = ResourceExecutionContract(
        provider_id="ClinGen Gene-Disease Validity",
        provider_version="GeneValidity",
        access_method="LOCAL",
        endpoint=None,
        location=str(path),
        dataset="ClinGen-GDV",
        toolchain={"release": "2026-11-08", "sha256": digest},
    )
    resolved = type(
        "Resolved",
        (),
        {"contract": contract, "resource_version": "2026-11-08"},
    )()
    provider = ClinGenGeneDiseaseValidityProvider.from_execution_contract(
        resolved,
        expected_sha256=digest,
    )
    assert provider.query_gene(gene="GENE1")[0].classification == "Definitive"



def test_clingen_rejects_malformed_mondo_and_hgnc_identifiers(tmp_path):
    malformed_mondo = _write_export(tmp_path / "bad-mondo.csv")
    malformed_mondo.write_text(
        malformed_mondo.read_text(encoding="utf-8").replace("MONDO_0000001", "MONDO:1"),
        encoding="utf-8",
    )
    mondo_provider = ClinGenGeneDiseaseValidityProvider(
        resource_path=str(malformed_mondo),
        expected_sha256=hashlib.sha256(malformed_mondo.read_bytes()).hexdigest(),
        expected_release="2026-11-08",
    )
    with pytest.raises(ClinGenGeneDiseaseValidityError, match="invalid MONDO"):
        mondo_provider.query_gene(gene="GENE1")

    malformed_hgnc = _write_export(tmp_path / "bad-hgnc.csv")
    malformed_hgnc.write_text(
        malformed_hgnc.read_text(encoding="utf-8").replace("HGNC:1", "HGNC:abc"),
        encoding="utf-8",
    )
    hgnc_provider = ClinGenGeneDiseaseValidityProvider(
        resource_path=str(malformed_hgnc),
        expected_sha256=hashlib.sha256(malformed_hgnc.read_bytes()).hexdigest(),
        expected_release="2026-11-08",
    )
    with pytest.raises(ClinGenGeneDiseaseValidityError, match="invalid HGNC"):
        hgnc_provider.query_gene(gene="GENE1")


def test_clingen_rejects_duplicate_headers_and_unexpected_columns(tmp_path):
    duplicate_header = _write_export(tmp_path / "duplicate-header.csv")
    duplicate_header.write_text(
        duplicate_header.read_text(encoding="utf-8").replace(
            "GENE SYMBOL,GENE ID (HGNC),",
            "GENE SYMBOL,GENE SYMBOL,GENE ID (HGNC),",
        ),
        encoding="utf-8",
    )
    duplicate_provider = ClinGenGeneDiseaseValidityProvider(
        resource_path=str(duplicate_header),
        expected_sha256=hashlib.sha256(duplicate_header.read_bytes()).hexdigest(),
        expected_release="2026-11-08",
    )
    with pytest.raises(ClinGenGeneDiseaseValidityError, match="duplicate headers"):
        duplicate_provider.query_gene(gene="GENE1")

    extra_column = _write_export(tmp_path / "extra-column.csv")
    extra_column.write_text(
        extra_column.read_text(encoding="utf-8").replace(
            "Expert Panel,Autosomal recessive inheritance",
            "Expert Panel,Autosomal recessive inheritance,UNEXPECTED",
        ),
        encoding="utf-8",
    )
    extra_provider = ClinGenGeneDiseaseValidityProvider(
        resource_path=str(extra_column),
        expected_sha256=hashlib.sha256(extra_column.read_bytes()).hexdigest(),
        expected_release="2026-11-08",
    )
    with pytest.raises(ClinGenGeneDiseaseValidityError, match="unexpected extra columns"):
        extra_provider.query_gene(gene="GENE1")


def test_clingen_fallback_record_ids_include_row_digest(tmp_path):
    path = tmp_path / "clingen-multiple.csv"
    path.write_text(
        "CLINGEN GENE VALIDITY CURATIONS\n"
        "FILE CREATED: 2026-11-08\n"
        "GENE SYMBOL,GENE ID (HGNC),DISEASE LABEL,DISEASE ID (MONDO),SOP,CLASSIFICATION,ONLINE REPORT,CLASSIFICATION DATE,GCEP,MOI\n"
        "GENE1,HGNC:1,Example disorder,MONDO:0000001,SOP9,Definitive,,2026-11-08,Expert Panel,Autosomal recessive inheritance\n"
        "GENE1,HGNC:1,Example disorder,MONDO:0000001,SOP9,Strong,,2026-11-08,Expert Panel,Autosomal recessive inheritance\n",
        encoding="utf-8",
    )
    provider = ClinGenGeneDiseaseValidityProvider(
        resource_path=str(path),
        expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        expected_release="2026-11-08",
    )
    assertions = provider.query_gene(gene="GENE1")
    assert len(assertions) == 2
    assert len({item.source_record_id for item in assertions}) == 2
