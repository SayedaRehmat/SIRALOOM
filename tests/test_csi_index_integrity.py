from __future__ import annotations

import gzip
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
    # HTSlib writes CSI as BGZF-compressed data; corrupt the BGZF signature
    # rather than incorrectly expecting the decompressed CSI magic at byte zero.
    assert original.startswith(b"\x1f\x8b\x08\x04")
    csi.write_bytes(b"NOT-A-CSI" + original[9:])

    with pytest.raises(VCFToolError, match="index record-count validation failed"):
        validate_vcf_index_concordance(bgzf, expected_bcftools_version="1.25")


def test_stale_csi_offsets_are_rejected_when_bgzf_header_shifts_record_blocks(
    tmp_path: Path,
):
    _require_bcftools()
    original_source = tmp_path / "original.vcf"
    shifted_source = tmp_path / "shifted.vcf"
    bgzf = tmp_path / "sample.vcf.gz"
    shifted_bgzf = tmp_path / "shifted.vcf.gz"

    metadata_header = (
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=100000>\n"
    )
    column_header = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    record = "1\t10\t.\tA\tC\t.\tPASS\t.\n"
    original_source.write_text(metadata_header + column_header + record, encoding="utf-8")
    _compress_and_index(original_source, bgzf)
    original_csi = Path(str(bgzf) + ".csi").read_bytes()

    # Valid metadata lines before #CHROM shift the record into later BGZF
    # blocks without turning the padding into malformed VCF records.
    padding = "".join(
        f"##SIRALOOM_PADDING_{index}=" + ("y" * 180) + "\n"
        for index in range(1200)
    )
    shifted_source.write_text(
        metadata_header + padding + column_header + record,
        encoding="utf-8",
    )
    _compress_and_index(shifted_source, shifted_bgzf)
    shutil.copyfile(shifted_bgzf, bgzf)
    Path(str(bgzf) + ".csi").write_bytes(original_csi)

    with pytest.raises(VCFToolError):
        validate_vcf_index_concordance(bgzf, expected_bcftools_version="1.25")


def test_csi_supports_coordinates_beyond_tbi_512_mbp_boundary(tmp_path: Path):
    _require_bcftools()
    source = tmp_path / "long-contig.vcf"
    bgzf = tmp_path / "long-contig.vcf.gz"
    positions = [
        1,
        (1 << 14) - 1,
        1 << 14,
        (1 << 14) + 1,
        (1 << 29) - 1,
        1 << 29,
        (1 << 29) + 1,
    ]
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
        expected_bcftools_version="1.25",
    )

    assert result["status"] == "VALIDATED"
    assert result["compression"]["format"] == "BGZF"
    assert result["compression"]["eof_marker_present"] is True
    assert result["compression"]["random_access_capable"] is True
    assert result["index_type"] == "CSI"
    assert result["concordance"]["records"] == len(positions)
    assert result["concordance"]["indexed_query_records_verified"] == len(positions)


def test_valid_ordinary_gzip_without_index_is_classified_as_sequential_only(
    tmp_path: Path,
):
    path = tmp_path / "sequential-only.vcf.gz"
    path.write_bytes(
        gzip.compress(
            b"##fileformat=VCFv4.3\n"
            b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
            b"1\t10\t.\tA\tC\t.\tPASS\t.\n"
        )
    )

    with pytest.raises(VCFToolError, match="valid ordinary gzip stream, not BGZF"):
        validate_vcf_index_concordance(path)


def test_valid_bgzf_without_index_is_distinguished_from_corrupt_bgzf(
    tmp_path: Path,
):
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
    Path(str(bgzf) + ".csi").unlink()

    with pytest.raises(VCFToolError, match="passed block and EOF integrity checks but has no adjacent"):
        validate_vcf_index_concordance(bgzf, expected_bcftools_version="1.25")


def test_bgzf_missing_terminal_eof_marker_is_rejected(tmp_path: Path):
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
    compressed = bgzf.read_bytes()
    assert compressed.endswith(bytes.fromhex(
        "1f8b08040000000000ff0600424302001b0003000000000000000000"
    ))
    bgzf.write_bytes(compressed[:-28])

    with pytest.raises(VCFToolError, match="BGZF EOF marker is missing"):
        validate_vcf_index_concordance(bgzf, expected_bcftools_version="1.25")


def test_bgzf_truncated_block_size_is_rejected_before_index_queries(tmp_path: Path):
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
    damaged = bytearray(bgzf.read_bytes())
    assert damaged[12:14] == b"BC"
    damaged[16:18] = (65535 - 1).to_bytes(2, "little")
    bgzf.write_bytes(damaged)

    with pytest.raises(VCFToolError, match="BGZF block is truncated"):
        validate_vcf_index_concordance(bgzf, expected_bcftools_version="1.25")


def test_bgzf_crc_corruption_is_rejected_before_index_queries(tmp_path: Path):
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
    damaged = bytearray(bgzf.read_bytes())
    damaged[-28 - 8] ^= 0x01
    bgzf.write_bytes(damaged)

    with pytest.raises(VCFToolError, match="decompression or CRC validation failed"):
        validate_vcf_index_concordance(bgzf, expected_bcftools_version="1.25")
