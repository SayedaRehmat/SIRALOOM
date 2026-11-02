from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validation" / "prepare_giab_processing_input.py"
SPEC = importlib.util.spec_from_file_location("prepare_giab_processing_input", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write_source(path: Path) -> None:
    text = (
        "##fileformat=VCFv4.3\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tHG001\n"
        "3\t30804994\tstar\tGGCGGC\t*,G\t.\tPASS\t.\tGT\t1/2\n"
        "3\t30805010\tsnv\tA\tC\t.\tPASS\t.\tGT\t0/1\n"
    )
    if path.suffix == ".gz":
        with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
            handle.write(text)
    else:
        path.write_text(text, encoding="utf-8")


def test_quarantines_whole_multiallelic_star_record_and_preserves_original_genotype(tmp_path):
    source = tmp_path / "HG001.vcf.gz"
    output = tmp_path / "eligible.vcf"
    sidecar = tmp_path / "excluded.jsonl"
    provenance = tmp_path / "provenance.json"
    _write_source(source)

    report = MODULE.derive(source, output, sidecar, provenance)

    lines = output.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("3\t30805010\t") for line in lines)
    assert not any(line.startswith("3\t30804994\t") for line in lines)
    excluded = json.loads(sidecar.read_text(encoding="utf-8").splitlines()[0])
    assert excluded["alt"] == "*,G"
    assert excluded["raw_source_record"].endswith("\tGT\t1/2")
    assert excluded["reason_code"] == "SPANNING_DELETION_RECORD_QUARANTINED_WHOLE"
    assert report["source"]["record_count"] == 2
    assert report["derivative"]["eligible_record_count"] == 1
    assert report["derivative"]["excluded_record_count"] == 1
    assert report["source"]["sha256"] == MODULE.sha256_file(source)
    assert report["derivative"]["sha256"] == MODULE.sha256_file(output)


def test_refuses_to_overwrite_any_existing_evidence(tmp_path):
    source = tmp_path / "HG001.vcf"
    _write_source(source)
    output = tmp_path / "eligible.vcf"
    output.write_text("preserve\n")
    try:
        MODULE.derive(source, output, tmp_path / "excluded.jsonl", tmp_path / "provenance.json")
    except MODULE.DerivationError as exc:
        assert "overwrite" in str(exc).lower()
    else:
        raise AssertionError("must not overwrite existing evidence")
    assert output.read_text(encoding="utf-8") == "preserve\n"
