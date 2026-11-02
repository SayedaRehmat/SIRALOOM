from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validation" / "diagnose_giab_spanning_deletions.py"
SPEC = importlib.util.spec_from_file_location("diagnose_giab_spanning_deletions", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _write_vcf(path: Path, records: str) -> None:
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=3,length=198295559>\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tHG001\n"
        + records,
        encoding="utf-8",
    )


def test_context_capture_records_orphan_star_without_weakening_validator(tmp_path):
    path = tmp_path / "orphan.vcf"
    _write_vcf(path, "3\t30804994\tstar\tGGCGGC\t*,G\t.\tPASS\t.\tGT\t1/2\n")

    result = MODULE.collect_context(path, "GRCh37")

    assert result["target_record"]["position"] == 30_804_994
    assert result["target_record"]["alt"] == "*,G"
    assert result["target_star_carrier_sample_indexes"] == [0]
    assert result["overlapping_deletion_candidate_count"] == 0
    assert result["same_sample_deletion_context_found"] is False
    assert result["same_sample_deletion_context_indeterminate"] is False


def test_context_capture_identifies_same_sample_deletion_context(tmp_path):
    path = tmp_path / "contextual.vcf"
    _write_vcf(
        path,
        "3\t30804993\tdel\tAGGCGGC\tA\t.\tPASS\t.\tGT\t0/1\n"
        "3\t30804994\tstar\tGGCGGC\t*,G\t.\tPASS\t.\tGT\t1/2\n",
    )

    result = MODULE.collect_context(path, "GRCh37")

    assert result["overlapping_deletion_candidate_count"] == 1
    assert result["candidate_carrier_matches"] == [True]
    assert result["same_sample_deletion_context_found"] is True
    assert result["same_sample_deletion_context_indeterminate"] is False
