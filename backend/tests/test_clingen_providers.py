from pathlib import Path

from backend.app.adapters.clingen.gene_disease_validity import ClinGenGeneDiseaseValidityProvider
from backend.app.adapters.clingen.variant_pathogenicity import ClinGenVariantPathogenicityProvider
from backend.app.domain.provider_registry import register_builtin_providers


def test_clingen_providers_are_distinct_and_registered():
    registry = register_builtin_providers()
    assert registry.resolve(
        provider_id="ClinGen Variant Pathogenicity", provider_version="ERepo"
    ) is not None
    assert registry.resolve(
        provider_id="ClinGen Gene-Disease Validity", provider_version="GeneValidity"
    ) is not None
    assert registry.resolve(
        provider_id="ClinGen Variant Pathogenicity", provider_version="ERepo"
    ).descriptor.capabilities
    assert registry.resolve(
        provider_id="ClinGen Gene-Disease Validity", provider_version="GeneValidity"
    ).descriptor.capabilities


def test_clingen_variant_pathogenicity_matches_gene_and_hgvs(tmp_path: Path):
    path = tmp_path / "variant.tsv"
    path.write_text(
        "Gene\tPreferred Variant Title\tClassification\tCondition\tMOI\tMet Codes\tUnmet Codes\tVersion\tCAID\tClinVar Id\tExpert Panel\n"
        "ABCA4\tNM_000350.3:c.2828G>A (p.Arg943Gln)\tLikely Pathogenic\tABCA4-related retinopathy\tAutosomal recessive inheritance\tPM2_Supporting,PP4\t\t1.0\tCA119146\t7913\tRetina VCEP\n",
        encoding="utf-8",
    )
    provider = ClinGenVariantPathogenicityProvider(resource_path=str(path), delimiter="\t")
    rows = provider.query_variant(
        gene="ABCA4",
        hgvs=["NM_000350.3:c.2828G>A (p.Arg943Gln)"],
    )
    assert len(rows) == 1
    assert rows[0].classification == "Likely Pathogenic"
    assert rows[0].caid == "CA119146"
    assert rows[0].met_codes == ("PM2_Supporting", "PP4")


def test_clingen_gene_disease_validity_matches_gene(tmp_path: Path):
    path = tmp_path / "gene-validity.csv"
    path.write_text(
        '"CLINGEN GENE DISEASE VALIDITY CURATIONS","","","","","","","","",""\n'
        '"FILE CREATED: 2026-10-06","","","","","","","","",""\n'
        '"GENE SYMBOL","GENE ID (HGNC)","DISEASE LABEL","DISEASE ID (MONDO)","MOI","SOP","CLASSIFICATION","ONLINE REPORT","CLASSIFICATION DATE","GCEP"\n'
        '"ABCA4","HGNC:34","ABCA4-related retinopathy","MONDO:0800406","AR","SOP9","Definitive","https://search.clinicalgenome.org/kb/gene-validity/example","2022-10-06T16:00:00.000Z","Retina Gene Curation Expert Panel"\n',
        encoding="utf-8",
    )
    provider = ClinGenGeneDiseaseValidityProvider(resource_path=str(path))
    rows = provider.query_gene(gene="ABCA4")
    assert len(rows) == 1
    assert rows[0].classification == "Definitive"
    assert rows[0].mondo_id == "MONDO:0800406"
    assert rows[0].expert_panel == "Retina Gene Curation Expert Panel"
