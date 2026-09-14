from pathlib import Path
import gzip

from backend.app.domain.ingestion import classify_filename, validate_index, validate_vcf

VALID_VCF = """##fileformat=VCFv4.3
##reference=GRCh38
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO
chr1\t100\t.\tA\tG\t.\tPASS\t.
"""


def test_supported_filename_classification():
    assert classify_filename("sample.vcf") == "VCF"
    assert classify_filename("sample.vcf.gz") == "VCF"
    assert classify_filename("sample.vcf.bgz") == "VCF"
    assert classify_filename("sample.vcf.gz.tbi") == "TBI"
    assert classify_filename("sample.vcf.bgz.csi") == "CSI"
    assert classify_filename("sample.bam") == "UNSUPPORTED"


def test_vcf_validation_reads_real_content(tmp_path: Path):
    path = tmp_path / "sample.vcf"
    path.write_text(VALID_VCF)
    result = validate_vcf(path)
    assert result.status == "VALID"
    assert result.record_count == 1
    assert result.detected_build == "GRCh38"


def test_vcfgz_validation_reads_real_content(tmp_path: Path):
    path = tmp_path / "sample.vcf.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(VALID_VCF)
    result = validate_vcf(path)
    assert result.status == "VALID"
    assert result.record_count == 1


def test_invalid_vcf_header_is_rejected(tmp_path: Path):
    path = tmp_path / "bad.vcf"
    path.write_text("#CHROM\tPOS\tID\tREF\tALT\nchr1\t1\t.\tA\tG\n")
    result = validate_vcf(path)
    assert result.status == "INVALID"
    assert result.errors


def test_index_filename_and_magic_validation(tmp_path: Path):
    primary = "sample.vcf.gz"
    tbi = tmp_path / "sample.vcf.gz.tbi"
    import gzip
    with gzip.open(tbi, "wb") as fh:
        fh.write(b"TBI\x01dummy")
    assert validate_index(tbi, primary).status == "VALID"

    wrong = tmp_path / "other.vcf.gz.tbi"
    with gzip.open(wrong, "wb") as fh:
        fh.write(b"TBI\x01dummy")
    assert validate_index(wrong, primary).status == "INVALID"


def test_csi_magic_validation(tmp_path: Path):
    csi = tmp_path / "sample.vcf.bgz.csi"
    csi.write_bytes(b"CSI\x01dummy")
    assert validate_index(csi, "sample.vcf.bgz").status == "VALID"


def test_index_alone_is_not_primary_input():
    assert classify_filename("sample.vcf.gz.tbi") == "TBI"


def test_malformed_tbi_is_rejected(tmp_path: Path):
    tbi = tmp_path / "sample.vcf.gz.tbi"
    tbi.write_bytes(b"\x1f\x8b\x08\x04not-a-valid-gzip")
    assert validate_index(tbi, "sample.vcf.gz").status == "INVALID"
