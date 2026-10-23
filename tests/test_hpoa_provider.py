from __future__ import annotations

import gzip
import hashlib

import pytest

from backend.app.adapters.phenotype.hpoa import HPOAError, HPOAProvider
from backend.app.domain.resource_source_contract import ResourceExecutionContract

HEADER = (
    "database_id\tdisease_name\tqualifier\thpo_id\treference\tevidence\t"
    "onset\tfrequency\tsex\tmodifier\taspect\tbiocuration\n"
)


def _write_hpoa(
    tmp_path, rows=(), *, release="2026-09-02", hpo_release="2026-09-01", gzip_file=False
):
    content = (
        f"#version: {release}\n"
        f"#hpo-version: http://purl.obolibrary.org/obo/hp/releases/{hpo_release}/hp.json\n"
        + HEADER
        + "".join(f"{row}\n" for row in rows)
    ).encode()
    path = tmp_path / ("phenotype.hpoa.gz" if gzip_file else "phenotype.hpoa")
    path.write_bytes(gzip.compress(content) if gzip_file else content)
    return path


def _provider(path, *, release="2026-09-02", hpo_release="2026-09-01"):
    return HPOAProvider(
        path,
        expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        expected_release=release,
        expected_hpo_release=hpo_release,
    )


def test_hpoa_parses_and_preserves_assertion_evidence_without_scoring(tmp_path):
    path = _write_hpoa(
        tmp_path,
        [
            (
                "MONDO:0000001\tExample disorder\t\tHP:0001250\tPMID:123\tPCS\t"
                "HP:0003593\t1/2\t\tHP:0025257;HP:0025161\tP\tHPO:curator[2026-01-01]"
            ),
            (
                "MONDO:0000001\tExample disorder\tNOT\tHP:0001251\tPMID:456\tTAS\t"
                "\t0/3\t\t\tP\tHPO:curator[2026-01-02]"
            ),
        ],
    )
    provider = _provider(path)

    annotations = provider.query_disease("mondo:0000001")
    assert len(annotations) == 2
    positive, negative = annotations
    assert (positive.hpo_id, positive.qualifier, positive.frequency, positive.evidence) == (
        "HP:0001250",
        "",
        "1/2",
        "PCS",
    )
    assert positive.modifiers == ("HP:0025257", "HP:0025161")
    assert positive.biocuration == ("HPO:curator[2026-01-01]",)
    assert negative.qualifier == "NOT"
    assert negative.frequency == "0/3"
    assert provider.query_disease("MONDO:0000002") == ()
    assert provider.release == "2026-09-02"
    assert provider.hpo_release == "2026-09-01"


def test_hpoa_accepts_gzip_and_uncommented_column_header(tmp_path):
    path = _write_hpoa(
        tmp_path,
        ["ORPHA:123\tExample\t\tHP:0001250\tPMID:123\tPCS\t\t\t\t\tP\tHPO:curator[2026-01-01]"],
        gzip_file=True,
    )
    provider = _provider(path)
    assert provider.query_disease("ORPHA:123")[0].hpo_id == "HP:0001250"


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("MONDO:1\tDisease\t\tHP:123\tPMID:1\tPCS\t\t\t\t\tP\tHPO:x", "invalid HPO identifier"),
        (
            "MONDO:1\tDisease\tMAYBE\tHP:0001250\tPMID:1\tPCS\t\t\t\t\tP\tHPO:x",
            "unsupported qualifier",
        ),
        ("MONDO:1\tDisease\t\tHP:0001250\t\tPCS\t\t\t\t\tP\tHPO:x", "missing required reference"),
        ("MONDO:1\tDisease\t\tHP:0001250\tPMID:1\tPCS\t\t\t\t\tZ\tHPO:x", "unsupported aspect"),
    ],
)
def test_hpoa_rejects_malformed_assertions(tmp_path, row, message):
    path = _write_hpoa(tmp_path, [row])
    with pytest.raises(HPOAError, match=message):
        _provider(path)


def test_hpoa_requires_matching_checksum_and_both_release_pins(tmp_path):
    path = _write_hpoa(tmp_path, ["MONDO:1\tDisease\t\tHP:0001250\tPMID:1\tPCS\t\t\t\t\tP\tHPO:x"])
    with pytest.raises(HPOAError, match="checksum"):
        HPOAProvider(
            path,
            expected_sha256="0" * 64,
            expected_release="2026-09-02",
            expected_hpo_release="2026-09-01",
        )
    with pytest.raises(HPOAError, match="release mismatch"):
        _provider(path, release="2026-06-23")
    with pytest.raises(HPOAError, match="ontology release mismatch"):
        _provider(path, hpo_release="2026-06-23")


def test_hpoa_execution_contract_requires_local_access_and_pins(tmp_path):
    path = _write_hpoa(tmp_path, ["MONDO:1\tDisease\t\tHP:0001250\tPMID:1\tPCS\t\t\t\t\tP\tHPO:x"])
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    contract = ResourceExecutionContract(
        provider_id="HPOA",
        provider_version="HPOA_TSV",
        access_method="LOCAL",
        endpoint=None,
        location=str(path),
        dataset="2026-09-02",
        toolchain={"sha256": checksum, "release": "2026-09-02", "hpo_release": "2026-09-01"},
    )
    provider = HPOAProvider.from_execution_contract(contract)
    assert provider.query_disease("MONDO:1")[0].hpo_id == "HP:0001250"

    remote_contract = ResourceExecutionContract(
        provider_id="HPOA",
        provider_version="HPOA_TSV",
        access_method="HTTPS",
        endpoint="https://example.invalid",
        location=None,
        dataset="2026-09-02",
        toolchain={"sha256": checksum, "release": "2026-09-02", "hpo_release": "2026-09-01"},
    )
    with pytest.raises(HPOAError, match="local file"):
        HPOAProvider.from_execution_contract(remote_contract)
