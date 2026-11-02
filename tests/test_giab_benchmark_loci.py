from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validation" / "diagnose_giab_benchmark_loci.py"
SPEC = importlib.util.spec_from_file_location("diagnose_giab_benchmark_loci", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_bed_membership_uses_zero_based_half_open_and_full_ref_span(tmp_path):
    bed = tmp_path / "regions.bed"
    bed.write_text("3\t99\t108\n3\t200\t300\n", encoding="utf-8")
    full = MODULE.bed_membership(bed, "3", 100, 6)
    assert full["status"] == "FULLY_CONTAINED"
    assert full["bed_query_0based_half_open"] == [99, 105]

    partial = MODULE.bed_membership(bed, "3", 105, 6)
    assert partial["status"] == "PARTIAL_OVERLAP"

    outside = MODULE.bed_membership(bed, "3", 150, 6)
    assert outside["status"] == "OUTSIDE"
