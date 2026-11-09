from types import SimpleNamespace

import pytest
from backend.app.domain.gene_disease_source_assertions import build_gene_disease_source_assertions
from backend.app.domain.gene_disease_reconciliation import ReconciliationStatus, DimensionStatus, reconcile_gene_disease_assertions
from backend.app.domain.hgnc_crosswalk import HGNCResolution, HGNCResolutionStatus


def test_provider_adapter_preserves_native_identifiers_and_raw_assertions():
    g2p = SimpleNamespace(source_record_id="G2P:1", gene_symbol="GENE1", disease_mondo="MONDO:0000001", raw={"Gene Symbol":"GENE1"}, allelic_requirement="biallelic_autosomal", inheritance_modes=("AUTOSOMAL_RECESSIVE",), molecular_mechanism="loss of function")
    clingen = SimpleNamespace(source_record_id="ClinGen-GDV:1", gene="GENE1", hgnc_id="HGNC:1", mondo_id="MONDO:0000001", payload={"GENE ID (HGNC)":"HGNC:1"}, classification="Definitive", moi="Autosomal recessive")
    items = build_gene_disease_source_assertions(g2p_models=[g2p], clingen_assertions=[clingen], g2p_resource_id="g2p", g2p_resource_name="G2P", g2p_resource_version="r1", g2p_resource_sha256="a"*64, clingen_resource_id="gdv", clingen_resource_name="ClinGen", clingen_resource_version="r2", clingen_resource_sha256="b"*64)
    assert items[0].hgnc_id is None and items[0].raw_assertion == g2p.raw
    assert items[1].hgnc_id == "HGNC:1" and items[1].raw_assertion == clingen.payload
    assert {x.status for x in reconcile_gene_disease_assertions(items)} == {ReconciliationStatus.G2P_ONLY, ReconciliationStatus.CLINGEN_ONLY}


def test_provider_adapter_retains_missing_mondo_g2p_assertion():
    g2p = SimpleNamespace(source_record_id="G2P:2", gene_symbol="GENE2", disease_mondo=None, raw={"Gene Symbol":"GENE2"}, allelic_requirement="biallelic_autosomal", inheritance_modes=("AUTOSOMAL_RECESSIVE",), molecular_mechanism="loss of function")
    items = build_gene_disease_source_assertions(g2p_models=[g2p], clingen_assertions=[], g2p_resource_id="g2p", g2p_resource_name="G2P", g2p_resource_version="r1", g2p_resource_sha256="a"*64, clingen_resource_id=None, clingen_resource_name=None, clingen_resource_version=None, clingen_resource_sha256=None)
    assert len(items) == 1 and items[0].mondo_id is None
    assert reconcile_gene_disease_assertions(items)[0].status == ReconciliationStatus.UNMATCHABLE_MISSING_MONDO



class _QualifiedHGNCResolver:
    release = "2026-10-06"
    complete_sha256 = "a" * 64
    withdrawn_sha256 = "b" * 64

    def resolve(self, identifier):
        normalized = str(identifier).strip().upper()
        if normalized in {"GENE1", "HGNC:1"}:
            status = (
                HGNCResolutionStatus.HGNC_ID
                if normalized.startswith("HGNC:")
                else HGNCResolutionStatus.APPROVED_SYMBOL
            )
            return HGNCResolution(
                input_identifier=identifier,
                normalized_identifier=normalized,
                status=status,
                hgnc_id="HGNC:1",
                approved_symbol="GENE1",
                matched_field="hgnc_id" if status == HGNCResolutionStatus.HGNC_ID else "symbol",
            )
        if normalized == "AMBIGUOUS_GENE":
            return HGNCResolution(
                input_identifier=identifier,
                normalized_identifier=normalized,
                status=HGNCResolutionStatus.AMBIGUOUS,
                hgnc_id=None,
                approved_symbol=None,
                matched_field="historical_symbol",
                candidate_hgnc_ids=("HGNC:1", "HGNC:2"),
            )
        return HGNCResolution(
            input_identifier=identifier,
            normalized_identifier=normalized,
            status=HGNCResolutionStatus.NOT_FOUND,
            hgnc_id=None,
            approved_symbol=None,
            matched_field=None,
        )


def _g2p_model(gene="GENE1"):
    return SimpleNamespace(
        source_record_id="G2P:1",
        gene_symbol=gene,
        disease_mondo="MONDO:0000001",
        raw={"Gene Symbol": gene},
        allelic_requirement="biallelic_autosomal",
        inheritance_modes=("AUTOSOMAL_RECESSIVE",),
        molecular_mechanism="loss of function",
        record_sha256="c" * 64,
    )


def _clingen_assertion(moi="Autosomal recessive inheritance"):
    return SimpleNamespace(
        source_record_id="ClinGen-GDV:1",
        gene="GENE1",
        hgnc_id="HGNC:1",
        mondo_id="MONDO:0000001",
        payload={"GENE ID (HGNC)": "HGNC:1", "MOI": moi},
        classification="Definitive",
        moi=moi,
        record_sha256="d" * 64,
    )


def _build(g2p_models, clingen_assertions, resolver):
    return build_gene_disease_source_assertions(
        g2p_models=g2p_models,
        clingen_assertions=clingen_assertions,
        g2p_resource_id="g2p",
        g2p_resource_name="G2P",
        g2p_resource_version="2026-11-08",
        g2p_resource_sha256="e" * 64,
        clingen_resource_id="gdv",
        clingen_resource_name="ClinGen GDV",
        clingen_resource_version="2026-11-08",
        clingen_resource_sha256="f" * 64,
        hgnc_resolver=resolver,
    )


def test_qualified_hgnc_crosswalk_enables_exact_gene_and_mondo_matching():
    assertions = _build(
        [_g2p_model()],
        [_clingen_assertion()],
        _QualifiedHGNCResolver(),
    )
    assert assertions[0].hgnc_id == assertions[1].hgnc_id == "HGNC:1"
    assert assertions[0].gene_identifier_resolution["release"] == "2026-10-06"
    reconciliations = reconcile_gene_disease_assertions(assertions)
    assert len(reconciliations) == 1
    assert reconciliations[0].status == ReconciliationStatus.MATCHED
    assert reconciliations[0].dimensions["inheritance_mode"].status == DimensionStatus.AGREE


def test_ambiguous_hgnc_resolution_never_enables_cross_source_match():
    assertions = _build(
        [_g2p_model(gene="AMBIGUOUS_GENE")],
        [_clingen_assertion()],
        _QualifiedHGNCResolver(),
    )
    assert assertions[0].hgnc_id is None
    assert assertions[0].gene_identifier_resolution["status"] == HGNCResolutionStatus.AMBIGUOUS
    assert {item.status for item in reconcile_gene_disease_assertions(assertions)} == {
        ReconciliationStatus.G2P_ONLY,
        ReconciliationStatus.CLINGEN_ONLY,
    }


def test_unrecognized_clingen_moi_is_preserved_as_unmapped_not_as_agreement():
    assertions = _build(
        [_g2p_model()],
        [_clingen_assertion("X-linked inheritance")],
        _QualifiedHGNCResolver(),
    )
    reconciled = reconcile_gene_disease_assertions(assertions)[0]
    assert reconciled.status == ReconciliationStatus.MATCHED
    inheritance = reconciled.dimensions["inheritance_mode"]
    assert inheritance.status == DimensionStatus.UNMAPPED
    assert inheritance.clingen_unmapped_values == ("x-linked inheritance",)
    assert "SOURCE_DIMENSION_UNMAPPED" in reconciled.review_reasons



def test_g2p_native_hgnc_id_does_not_bypass_qualified_resource_gate():
    model = _g2p_model()
    model.hgnc_id = "HGNC:1"
    assertions = build_gene_disease_source_assertions(
        g2p_models=[model],
        clingen_assertions=[],
        g2p_resource_id="g2p",
        g2p_resource_name="G2P",
        g2p_resource_version="2026-11-08",
        g2p_resource_sha256="e" * 64,
        clingen_resource_id=None,
        clingen_resource_name=None,
        clingen_resource_version=None,
        clingen_resource_sha256=None,
        hgnc_resolver=None,
    )
    assert assertions[0].hgnc_id is None
    assert assertions[0].gene_identifier_resolution["status"] == "NOT_CONFIGURED"
    assert assertions[0].gene_identifier_resolution["source_native_hgnc_id"] == "HGNC:1"



@pytest.mark.parametrize(
    ("allelic_requirement", "g2p_modes", "clingen_moi"),
    [
        ("monoallelic_autosomal", ("AUTOSOMAL_DOMINANT",), "AD"),
        ("biallelic_autosomal", ("AUTOSOMAL_RECESSIVE",), "AR"),
        ("semidominant", ("AUTOSOMAL_SEMIDOMINANT",), "SD"),
    ],
)
def test_official_clingen_moi_codes_normalize_to_the_same_controlled_modes(
    allelic_requirement, g2p_modes, clingen_moi
):
    model = _g2p_model()
    model.allelic_requirement = allelic_requirement
    model.inheritance_modes = g2p_modes
    assertions = _build([model], [_clingen_assertion(clingen_moi)], _QualifiedHGNCResolver())
    reconciliation = reconcile_gene_disease_assertions(assertions)[0]
    assert reconciliation.dimensions["inheritance_mode"].status == DimensionStatus.AGREE


@pytest.mark.parametrize("clingen_moi", ["XL", "UD"])
def test_generic_x_linked_and_undetermined_clingen_codes_remain_unmapped(clingen_moi):
    assertions = _build(
        [_g2p_model()],
        [_clingen_assertion(clingen_moi)],
        _QualifiedHGNCResolver(),
    )
    inheritance = reconcile_gene_disease_assertions(assertions)[0].dimensions["inheritance_mode"]
    assert inheritance.status == DimensionStatus.UNMAPPED
    assert inheritance.clingen_unmapped_values == (clingen_moi.casefold(),)
