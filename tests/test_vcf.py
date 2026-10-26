from pathlib import Path

from backend.app.domain.vcf import VCFValidationError, validate_and_extract


def test_valid_vcf(tmp_path: Path):
    path = tmp_path / "x.vcf"
    path.write_text("##fileformat=VCFv4.3\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n1\t100\t.\tA\tG\t.\tPASS\t.\n")
    variants = validate_and_extract(str(path), "GRCh38")
    assert len(variants) == 1
    assert variants[0].chromosome == "1"
    assert variants[0].position == 100


def test_variant_iterator_skips_reference_only_alt_dot_records(tmp_path: Path):
    path = tmp_path / "mixed-reference-variant.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t99\t.\tA\t.\t.\tPASS\t.\n"
        "1\t100\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    variants = validate_and_extract(str(path), "GRCh38")

    assert len(variants) == 1
    assert variants[0].alternate == "G"


def test_variant_iterator_excludes_valid_telomere_sentinel_from_small_variants(tmp_path: Path):
    path = tmp_path / "telomere-and-snv.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t0\ttelo\tA\tG\t.\tPASS\t.\n"
        "1\t100\trs1\tA\tC\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    variants = validate_and_extract(str(path), "GRCh38")

    assert [(variant.position, variant.alternate) for variant in variants] == [(100, "C")]

def test_malformed_vcf(tmp_path: Path):
    path = tmp_path / "bad.vcf"
    path.write_text("1\t100\t.\tA\tG\n")
    try:
        validate_and_extract(str(path), "GRCh38")
    except VCFValidationError:
        return
    raise AssertionError("Expected validation failure")
