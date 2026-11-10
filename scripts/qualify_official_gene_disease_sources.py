"""Qualify real G2P/ClinGen assertions against the pinned HGNC release.

This is a technical cross-source identity check only. It does not emit
patient-specific inheritance compatibility or variant pathogenicity evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from backend.app.adapters.clingen.gene_disease_validity import ClinGenGeneDiseaseValidityProvider
from backend.app.adapters.gene_disease.g2p import G2PProvider
from backend.app.domain.gene_disease_reconciliation import (
    GeneDiseaseSource,
    ReconciliationStatus,
    reconcile_gene_disease_assertions,
)
from backend.app.domain.gene_disease_source_assertions import build_gene_disease_source_assertions
from backend.app.domain.hgnc_crosswalk import HGNC_ARCHIVE_RELEASE, HGNCResolver


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _one_synthetic_pair(resolver, symbol: str, target_hgnc: str, *, mondo: str | None):
    model = SimpleNamespace(
        source_record_id=f"G2P:qualification:{symbol}",
        gene_symbol=symbol,
        hgnc_id=None,
        disease_mondo=mondo,
        allelic_requirement="biallelic_autosomal",
        inheritance_modes=("AUTOSOMAL_RECESSIVE",),
        molecular_mechanism="loss of function",
        raw={"gene_symbol": symbol, "disease_mondo": mondo},
        record_sha256=_sha(symbol),
    )
    clingen = SimpleNamespace(
        source_record_id=f"ClinGen-GDV:qualification:{target_hgnc}",
        gene=resolver._approved[target_hgnc]["symbol"],
        hgnc_id=target_hgnc,
        mondo_id=mondo,
        payload={"GENE ID (HGNC)": target_hgnc, "DISEASE ID (MONDO)": mondo},
        record_sha256=_sha(target_hgnc),
        moi="AR",
        classification="Definitive",
    )
    assertions = build_gene_disease_source_assertions(
        g2p_models=(model,),
        clingen_assertions=(clingen,),
        g2p_resource_id="qualification:G2P",
        g2p_resource_name="G2P qualification fixture",
        g2p_resource_version="qualification",
        g2p_resource_sha256="a" * 64,
        clingen_resource_id="qualification:ClinGen",
        clingen_resource_name="ClinGen qualification fixture",
        clingen_resource_version="qualification",
        clingen_resource_sha256="b" * 64,
        hgnc_resolver=resolver,
    )
    return assertions, reconcile_gene_disease_assertions(assertions)


def qualify(hgnc_directory: Path, acquisition_directory: Path, managed_directory: Path) -> dict:
    hgnc_manifest = json.loads((hgnc_directory / "manifest.json").read_text(encoding="utf-8"))
    hgnc = HGNCResolver(
        hgnc_directory / "hgnc_complete_set.txt",
        hgnc_directory / "withdrawn.txt",
        release=HGNC_ARCHIVE_RELEASE,
    )
    acquisition = json.loads((acquisition_directory / "manifest.json").read_text(encoding="utf-8"))
    records = {item["provider"]: item for item in acquisition["artifacts"]}
    g2p_item = records["Gene2Phenotype"]
    clingen_item = records["ClinGen Gene-Disease Validity"]
    g2p_path = (
        managed_directory
        / "Gene2Phenotype"
        / f'{g2p_item["release_identity"]}-{g2p_item["sha256"][:12]}'
        / g2p_item["filename"]
    )
    clingen_path = (
        managed_directory
        / "ClinGen_Gene-Disease_Validity"
        / f'{clingen_item["release_identity"]}-{clingen_item["sha256"][:12]}'
        / clingen_item["filename"]
    )
    if not g2p_path.is_file() or not clingen_path.is_file():
        raise RuntimeError("Managed G2P/ClinGen source artifacts are missing")

    g2p = G2PProvider(
        resource_path=str(g2p_path),
        expected_sha256=g2p_item["sha256"],
        release=g2p_item["release_identity"],
    )
    clingen = ClinGenGeneDiseaseValidityProvider(
        resource_path=str(clingen_path),
        expected_sha256=clingen_item["sha256"],
        expected_release=clingen_item["release_identity"],
    )
    clingen_assertions = tuple(
        assertion
        for gene_assertions in clingen._load_index().values()
        for assertion in gene_assertions
    )
    g2p_models = tuple(g2p._records)
    source_assertions = build_gene_disease_source_assertions(
        g2p_models=g2p_models,
        clingen_assertions=clingen_assertions,
        g2p_resource_id="official:G2P",
        g2p_resource_name="Official G2P all-panels export",
        g2p_resource_version=g2p_item["release_identity"],
        g2p_resource_sha256=g2p_item["sha256"],
        clingen_resource_id="official:ClinGen-GDV",
        clingen_resource_name="Official ClinGen Gene-Disease Validity export",
        clingen_resource_version=clingen_item["release_identity"],
        clingen_resource_sha256=clingen_item["sha256"],
        hgnc_resolver=hgnc,
        hgnc_request_fingerprint=_sha({
            "hgnc_release": hgnc.release,
            "complete_sha256": hgnc.complete_sha256,
            "withdrawn_sha256": hgnc.withdrawn_sha256,
        }),
    )
    reconciliations = reconcile_gene_disease_assertions(source_assertions)
    matched = [
        item for item in reconciliations
        if item.status == ReconciliationStatus.MATCHED
    ]
    if not matched:
        raise AssertionError("Official G2P and ClinGen snapshots produced no exact HGNC+MONDO matches")
    for item in matched:
        if item.gene_identifier_namespace.value != "HGNC" or not item.gene_identifier or not item.mondo_id:
            raise AssertionError("A MATCHED result lacks canonical HGNC and MONDO identity")
        if any(not assertion.hgnc_id or not assertion.mondo_id for assertion in (*item.g2p_assertions, *item.clingen_assertions)):
            raise AssertionError("A MATCHED result contains an unresolved gene or missing MONDO identifier")

    # Exercise historical and ambiguous resolution against the actual pinned
    # HGNC release, then pass those results through the production reconciler.
    unique_aliases = sorted(
        alias for alias, ids in hgnc._alias_index.items()
        if len(ids) == 1 and alias not in hgnc._approved_symbols
        and alias not in hgnc._previous and alias not in hgnc._withdrawn
    )
    if not unique_aliases:
        raise AssertionError("No unique alias available in the pinned HGNC release")
    alias = unique_aliases[0]
    alias_target = sorted(hgnc._alias_index[alias])[0]
    alias_assertions, alias_reconciliations = _one_synthetic_pair(
        hgnc, alias, alias_target, mondo="MONDO:0000001"
    )
    if not any(item.status == ReconciliationStatus.MATCHED for item in alias_reconciliations):
        raise AssertionError("Unique HGNC alias did not resolve to an exact cross-source match")

    merged_symbols = sorted(
        symbol for symbol in hgnc._withdrawn
        if hgnc.resolve(symbol).status.value == "WITHDRAWN_MERGED"
    )
    if not merged_symbols:
        raise AssertionError("No single-target withdrawn HGNC symbol available in pinned release")
    retired_symbol = merged_symbols[0]
    retired_resolution = hgnc.resolve(retired_symbol)
    retired_assertions, retired_reconciliations = _one_synthetic_pair(
        hgnc, retired_symbol, retired_resolution.hgnc_id, mondo="MONDO:0000001"
    )
    if not any(item.status == ReconciliationStatus.MATCHED for item in retired_reconciliations):
        raise AssertionError("Single-target withdrawn HGNC symbol did not resolve to an exact cross-source match")

    ambiguous_aliases = sorted(
        alias for alias, ids in hgnc._alias_index.items() if len(ids) > 1
    )
    if not ambiguous_aliases:
        raise AssertionError("No ambiguous alias available in the pinned HGNC release")
    ambiguous_alias = ambiguous_aliases[0]
    ambiguous_target = sorted(hgnc._alias_index[ambiguous_alias])[0]
    ambiguous_assertions, ambiguous_reconciliations = _one_synthetic_pair(
        hgnc, ambiguous_alias, ambiguous_target, mondo="MONDO:0000001"
    )
    if any(item.status == ReconciliationStatus.MATCHED for item in ambiguous_reconciliations):
        raise AssertionError("Ambiguous HGNC alias incorrectly produced a cross-source match")
    if not any(assertion.hgnc_id is None for assertion in ambiguous_assertions if assertion.source == GeneDiseaseSource.G2P):
        raise AssertionError("Ambiguous G2P symbol did not remain unresolved")

    missing_assertions, missing_reconciliations = _one_synthetic_pair(
        hgnc, alias, alias_target, mondo=None
    )
    if not any(item.status == ReconciliationStatus.UNMATCHABLE_MISSING_MONDO for item in missing_reconciliations):
        raise AssertionError("Missing MONDO assertion was not retained as explicitly unmatchable")

    return {
        "status": "REAL_SOURCE_HGNC_RECONCILIATION_QUALIFICATION_PASSED",
        "hgnc_release": hgnc.release,
        "hgnc_manifest_sha256": _sha(hgnc_manifest),
        "g2p_release": g2p.release,
        "g2p_sha256": g2p.sha256,
        "g2p_record_count": len(g2p_models),
        "clingen_release": clingen.release_date,
        "clingen_sha256": clingen.sha256,
        "clingen_record_count": len(clingen_assertions),
        "reconciliation_count": len(reconciliations),
        "exact_matched_count": len(matched),
        "unmatchable_missing_mondo_count": sum(
            item.status == ReconciliationStatus.UNMATCHABLE_MISSING_MONDO
            for item in reconciliations
        ),
        "alias_known_answer": {"input": alias, "hgnc_id": alias_target, "status": "MATCHED"},
        "retired_symbol_known_answer": {
            "input": retired_symbol,
            "hgnc_id": retired_resolution.hgnc_id,
            "status": retired_resolution.status.value,
        },
        "ambiguous_alias_known_answer": {
            "input": ambiguous_alias,
            "candidate_hgnc_ids": list(hgnc.resolve(ambiguous_alias).candidate_hgnc_ids),
            "status": "UNRESOLVED_NO_MATCH",
        },
        "missing_mondo_known_answer": "UNMATCHABLE_MISSING_MONDO",
        "activation_or_clinical_conclusion": "NOT_PERFORMED",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hgnc-directory", required=True, type=Path)
    parser.add_argument("--acquisition-directory", required=True, type=Path)
    parser.add_argument("--managed-directory", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = qualify(args.hgnc_directory, args.acquisition_directory, args.managed_directory)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
