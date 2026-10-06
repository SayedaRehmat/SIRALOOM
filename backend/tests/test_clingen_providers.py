from pathlib import Path

from backend.app.adapters.clingen.gene_disease_validity import ClinGenGeneDiseaseValidityProvider
from backend.app.adapters.clingen.variant_pathogenicity import ClinGenVariantPathogenicityProvider
from backend.app.adapters.clingen.cspec_provider import ClinGenCSpecProvider
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
    assert registry.resolve(
        provider_id=ClinGenCSpecProvider.provider_id, provider_version="CSpec"
    ) is not None
    assert registry.resolve(
        provider_id=ClinGenCSpecProvider.provider_id, provider_version="CSpec"
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


def test_clingen_gene_disease_validity_accepts_current_official_header_shape(tmp_path: Path):
    path = tmp_path / "official-current.csv"
    path.write_text(
        '"CLINGEN GENE DISEASE VALIDITY CURATIONS","","","","","","","","",""\\n'
        '"FILE CREATED: 2026-10-06","","","","","","","","",""\\n'
        '"GENE SYMBOL","GENE ID (HGNC)","DISEASE LABEL","DISEASE ID (MONDO)","MOI","SOP","CLASSIFICATION","ONLINE REPORT","CLASSIFICATION DATE","GCEP"\\n'
        '"ABCA4","HGNC:34","ABCA4-related retinopathy","MONDO:0800406","AR","SOP9","Definitive","https://search.clinicalgenome.org/kb/gene-validity/CGGV:assertion_38729563-bf36-48ae-929e-fa69a225de39-2022-10-06T160000.000Z","2022-10-06T16:00:00.000Z","Retina Gene Curation Expert Panel"\\n',
        encoding="utf-8",
    )
    rows = ClinGenGeneDiseaseValidityProvider(resource_path=str(path)).query_gene(gene="ABCA4")
    assert len(rows) == 1
    assert rows[0].source_record_id.startswith("ClinGen-GDV:CGGV:assertion_")
    assert rows[0].sop == "SOP9"


def test_clingen_variant_pathogenicity_parses_current_erepo_summary_columns_and_criteria(
    tmp_path: Path,
):
    path = tmp_path / "erepo-current.tsv"
    path.write_text(
        "Preferred Variant Title\tClassification\tCondition\tMOI\tPublished Date\t"
        "Met Codes\tVersion\tClinVar Id\tCAID\tExpert Panel\tGene\tMONDO\t"
        "Unmet Codes\tHGVS\n"
        "NM_000546.6(TP53):c.379T>C (p.Ser127Pro)\tLikely Pathogenic\t"
        "Li-Fraumeni syndrome\tAutosomal dominant inheritance\t2026-04-22\t"
        "PM1_Supporting, PM2_Supporting, PS3, PP4, PP3_Moderate\t1.0\t934410\t"
        "CA397843917\tTP53 VCEP\tTP53\tMONDO:0018875\t"
        "PM5, BS2, BS4, BS3, BS1, BP4, PS4, PS1, PS2, BA1, PP1\t"
        "NM_000546.6:c.379T>C|NM_000546.6(TP53):c.379T>C (p.Ser127Pro)\n",
        encoding="utf-8",
    )
    provider = ClinGenVariantPathogenicityProvider(
        resource_path=str(path), delimiter="\\t"
    )
    rows = provider.query_variant(
        gene="TP53",
        hgvs=["NM_000546.6:c.379T>C"],
        caid="CA397843917",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.classification == "Likely Pathogenic"
    assert row.condition == "Li-Fraumeni syndrome"
    assert row.inheritance == "Autosomal dominant inheritance"
    assert row.caid == "CA397843917"
    assert row.clinvar_id == "934410"
    assert row.payload["mondo_id"] == "MONDO:0018875"
    assert row.met_codes == (
        "PM1_Supporting",
        "PM2_Supporting",
        "PS3",
        "PP4",
        "PP3_Moderate",
    )
    assert row.unmet_codes == (
        "PM5",
        "BS2",
        "BS4",
        "BS3",
        "BS1",
        "BP4",
        "PS4",
        "PS1",
        "PS2",
        "BA1",
        "PP1",
    )
    assert {item.status for item in row.criterion_assertions} == {"MET", "NOT_MET"}
    assert {
        item.code for item in row.criterion_assertions if item.status == "MET"
    } == set(row.met_codes)
    assert {
        item.code for item in row.criterion_assertions if item.status == "NOT_MET"
    } == set(row.unmet_codes)
    assert row.payload["criterion_detail_available"] is False


def test_clingen_variant_pathogenicity_normalizes_full_erepo_api_document():
    document = {
        "@id": "https://erepo.genome.network/evrepo/api/classification/abc-123",
        "classification": "Pathogenic",
        "condition": "Example disease",
        "gene": "TP53",
        "caId": "CA123",
        "cvId": "456789",
        "expertPanel": "Example VCEP",
        "hgvs": ["NM_000546.6:c.215C>G"],
        "metCodes": ["PS3", "PM2_Supporting"],
        "unmetCodes": ["BS1"],
        "version": "2.0",
        "publishedOn": "2026-09-01",
        "evidenceLine": [
            {
                "evidenceItem": [
                    {
                        "type": "CriterionAssessment",
                        "criterion": {
                            "id": "0087",
                            "label": "PS3",
                            "defaultStrength": {"label": "Strong"}
                        },
                        "statementOutcome": {"label": "Met"},
                        "contribution": [
                            {"comments": "Functional assay supports the classification.", "pmids": ["https://pubmed.ncbi.nlm.nih.gov/12345678/"]}
                        ]
                    }
                ]
            }
        ],
    }
    normalized = ClinGenVariantPathogenicityProvider._normalize_api_document(document)
    assert normalized["classification"] == "Pathogenic"
    assert normalized["gene"] == "TP53"
    assert normalized["caid"] == "CA123"
    assert normalized["clinvar_id"] == "456789"
    assert normalized["hgvs"] == ("NM_000546.6:c.215C>G",)
    assert normalized["met_codes"] == ("PS3", "PM2_Supporting")
    assert normalized["unmet_codes"] == ("BS1",)
    criterion = next(item for item in normalized["criterion_assertions"] if item.code == "PS3")
    assert criterion.status == "MET"
    assert criterion.rationale == "Functional assay supports the classification."
    assert criterion.pmids == ("12345678",)
    assert criterion.strength == "Strong"
    assert criterion.pmids == ("12345678",)
    assert normalized["source_record_id"].endswith("abc-123")
    assert normalized["raw"] == document
