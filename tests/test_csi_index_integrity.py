from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from backend.app.domain.vcf_tools import VCFToolError, validate_vcf_index_concordance


def _require_bcftools() -> None:
    if shutil.which("bcftools") is None:
        pytest.skip("Pinned BCFtools is required for CSI integration tests")


def _compress_and_index(source: Path, bgzf: Path) -> None:
    compressed = subprocess.run(
        ["bcftools", "view", "--no-version", "-Oz", "-o", str(bgzf), str(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compressed.returncode == 0, compressed.stderr
    indexed = subprocess.run(
        ["bcftools", "index", "--csi", str(bgzf)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert indexed.returncode == 0, indexed.stderr


def test_csi_corruption_is_rejected_during_index_concordance(tmp_path: Path):
    _require_bcftools()
    source = tmp_path / "valid.vcf"
    bgzf = tmp_path / "valid.vcf.gz"
    source.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=100>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t10\t.\tA\tC\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    _compress_and_index(source, bgzf)
    csi = Path(str(bgzf) + ".csi")
    original = csi.read_bytes()
    assert original.startswith(b"CSI\\x01")
    csi.write_bytes(b"NOT-A-CSI" + original[9:])

    with pytest.raises(VCFToolError, match="index record-count validation failed"):
        validate_vcf_index_concordance(bgzf, expected_bcftools_version="1.24")


def test_stale_csi_offsets_are_rejected_when_bgzf_header_shifts_record_blocks(
    tmp_path: Path,
):
    _require_bcftools()
    original_source = tmp_path / "original.vcf"
    shifted_source = tmp_path / "shifted.vcf"
    bgzf = tmp_path / "sample.vcf.gz"
    shifted_bgzf = tmp_path / "shifted.vcf.gz"

    header = (
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=100000>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    )
    record = "1\t10\t.\tA\tC\t.\tPASS\t.\n"
    original_source.write_text(header + record, encoding="utf-8")
    _compress_and_index(original_source, bgzf)
    original_csi = Path(str(bgzf) + ".csi").read_bytes()

    # Push the record beyond the original CSI virtual offset by adding enough
    # uncompressed header material to require additional BGZF blocks.
    padding = "".join(
        f'##SIRALOOM_PADDING_{index}=x' + ("y" * 180) + "\n"
        for index in range(1200)
    )
    shifted_source.write_text(header + padding + record, encoding="utf-8")
    _compress_and_index(shifted_source, shifted_bgzf)
    shutil.copyfile(shifted_bgzf, bgzf)
    Path(str(bgzf) + ".csi").write_bytes(original_csi)

    with pytest.raises(VCFToolError):
        validate_vcf_index_concordance(bgzf, expected_bcftools_version="1.24")


def test_csi_supports_coordinates_beyond_tbi_512_mbp_boundary(tmp_path: Path):
    _require_bcftools()
    source = tmp_path / "long-contig.vcf"
    bgzf = tmp_path / "long-contig.vcf.gz"
    positions = [1, (1 << 14) - 1, 1 << 14, (1 << 14) + 1,
                 (1 << 29) - 1, 1 << 29, (1 << 29) + 1]
    source.write_text(
        "##fileformat=VCFv4.3\n"
        f"##contig=<ID=1,length={(1 << 29) + 100}>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        + "".join(
            f"1\t{position}\t.\tA\tG\t.\tPASS\t.\n"
            for position in positions
        ),
        encoding="utf-8",
    )
    _compress_and_index(source, bgzf)

    result = validate_vcf_index_concordance(
        bgzf,
        expected_bcftools_version="1.24",
    )

    assert result["status"] == "VALIDATED"
    assert result["index_type"] == "CSI"
    assert result["concordance"]["records"] == len(positions)
    assert result["concordance"]["indexed_query_records_verified"] == len(positions)
