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

def test_malformed_vcf(tmp_path: Path):
    path = tmp_path / "bad.vcf"
    path.write_text("1\t100\t.\tA\tG\n")
    try:
        validate_and_extract(str(path), "GRCh38")
    except VCFValidationError:
        return
    raise AssertionError("Expected validation failure")
