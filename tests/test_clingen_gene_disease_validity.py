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
