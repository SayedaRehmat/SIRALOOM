import gzip
import shutil
from pathlib import Path

import pytest

from backend.app.domain.normalization import iter_normalized_vcf
from backend.app.domain.vcf import parse_vcf
from backend.app.domain.vcf_tools import (
    MNV_POLICY,
    MULTIALLELIC_OVERLAP_POLICY,
    MULTIALLELIC_POLICY,
    VCFToolError,
    normalize_vcf_with_bcftools,
)
from backend.app.domain.vcf_validation import validate_vcf_strict

pytestmark = pytest.mark.skipif(shutil.which("bcftools") is None, reason="bcftools is required for production normalization golden tests")


def make_reference(tmp_path: Path) -> Path:
    fasta = tmp_path / "ref.fa"
    sequence = "CAAAAAC"
    fasta.write_text(f">1\n{sequence}\n", encoding="utf-8")
    # One sequence line: header is 3 bytes, sequence starts at offset 3.
    (tmp_path / "ref.fa.fai").write_text(
        f"1\t{len(sequence)}\t3\t{len(sequence)}\t{len(sequence)+1}\n",
        encoding="utf-8",
    )
    return fasta


def write_vcf(path: Path, records: str) -> None:
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=7>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        + records,
        encoding="utf-8",
    )


def records(path: Path):
    return [
        (r.chrom, r.pos, r.ref, r.alt)
        for r in parse_vcf(str(path))
    ]


def normalize(tmp_path: Path, records_text: str):
    reference = make_reference(tmp_path)
    source = tmp_path / "input.vcf"
    output = tmp_path / "normalized.vcf.gz"
    write_vcf(source, records_text)
    stats = normalize_vcf_with_bcftools(source, output, reference_fasta=reference)
    assert output.is_file()
    assert stats["tool"] == "bcftools"
    assert stats["operation"] == "reference_aware_normalization_sort_index"
    assert stats["compression"] == "BGZF"
    assert stats["index"] == "CSI"
    assert Path(str(output) + ".csi").is_file()
    assert stats["multiallelic_mode"] == MULTIALLELIC_POLICY
    assert stats["multiallelic_overlap_policy"] == MULTIALLELIC_OVERLAP_POLICY
    assert stats["mnv_policy"] == MNV_POLICY
    assert stats["source_record_mapping_tag"] == "SIRALOOM_ORIG"
    assert stats["source_record_mapping_policy"] == "BCFTOOLS_OLD_REC_TAG_SOURCE_ALT_INDEX"
    return records(output), reference, source, output


def test_golden_snv_is_reference_checked_and_preserved(tmp_path: Path):
    normalized, _reference, _source, output = normalize(
        tmp_path, "1\t2\t.\tA\tG\t.\tPASS\t.\n"
    )
    assert normalized == [("1", 2, "A", "G")]
    mapped = list(iter_normalized_vcf(output, "GRCh38"))
    assert [
        (variant.original_chromosome, variant.original_position,
         variant.original_reference, variant.original_alternate,
         variant.original_alt_index)
        for variant in mapped
    ] == [("1", 2, "A", "G", 1)]


def test_golden_repeat_deletion_is_left_normalized(tmp_path: Path):
    normalized, _reference, _source, output = normalize(
        tmp_path, "1\t4\t.\tAA\tA\t.\tPASS\t.\n"
    )
    assert normalized == [("1", 1, "CA", "C")]
    mapped = list(iter_normalized_vcf(output, "GRCh38"))
    assert [(variant.original_position, variant.original_reference,
             variant.original_alternate, variant.original_alt_index)
            for variant in mapped] == [(4, "AA", "A", 1)]


def test_golden_repeat_insertion_is_left_normalized(tmp_path: Path):
    normalized, *_ = normalize(tmp_path, "1\t4\t.\tA\tAA\t.\tPASS\t.\n")
    assert normalized == [("1", 1, "C", "CA")]


def test_golden_multiallelic_is_split_without_losing_alleles(tmp_path: Path):
    normalized, *_ = normalize(tmp_path, "1\t2\t.\tA\tC,G\t.\tPASS\t.\n")
    assert normalized == [("1", 2, "A", "C"), ("1", 2, "A", "G")]


def test_golden_multiallelic_remaps_allele_indexed_fields_and_preserves_phase(tmp_path: Path):
    reference = make_reference(tmp_path)
    source = tmp_path / "multiallelic.vcf"
    output = tmp_path / "multiallelic.normalized.vcf.gz"
    source.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=7>\n"
        '##INFO=<ID=AC,Number=A,Type=Integer,Description="Allele counts">\n'
        '##INFO=<ID=AF,Number=A,Type=Float,Description="Allele frequencies">\n'
        '##INFO=<ID=AR,Number=R,Type=Integer,Description="Reference and alternate values">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths">\n'
        '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Genotype likelihoods">\n'
        '##FORMAT=<ID=PS,Number=1,Type=Integer,Description="Phase set">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tP\tQ\n"
        "1\t2\t.\tA\tC,G\t50\tPASS\tAC=3,2;AF=0.3,0.2;AR=20,5,7\t"
        "GT:AD:PL:PS\t1|2:10,5,7:100,50,60,40,0,30:2\t"
        "2/2:6,3,9:90,80,70,60,50,0:.\n",
        encoding="utf-8",
    )

    stats = normalize_vcf_with_bcftools(source, output, reference_fasta=reference)

    assert stats["multiallelic_overlap_policy"] == MULTIALLELIC_OVERLAP_POLICY
    assert "--multi-overlaps 0" in stats["command"]
    assert "--old-rec-tag SIRALOOM_ORIG" in stats["command"]
    validation = validate_vcf_strict(output)
    assert validation["records"] == 2
    with gzip.open(output, "rt", encoding="utf-8") as handle:
        split_records = [line.rstrip("\n").split("\t") for line in handle if not line.startswith("#")]
    assert [row[4] for row in split_records] == ["C", "G"]
    assert [row[7] for row in split_records] == [
        "AC=3;AF=0.3;AR=20,5;SIRALOOM_ORIG=1|2|A|C,G|1",
        "AC=2;AF=0.2;AR=20,7;SIRALOOM_ORIG=1|2|A|C,G|2",
    ]
    assert [row[9:] for row in split_records] == [
        ["1|0:10,5:100,50,60:2", "0/0:6,3:90,80,70:."],
        ["0|1:10,7:100,40,30:2", "1/1:6,9:90,60,0:."],
    ]
    assert [row[7].split("SIRALOOM_ORIG=", 1)[1] for row in split_records] == [
        "1|2|A|C,G|1",
        "1|2|A|C,G|2",
    ]
    mapped = list(iter_normalized_vcf(output, "GRCh38"))
    assert [
        (row.original_chromosome, row.original_position, row.original_reference,
         row.original_alternate, row.original_alt_index)
        for row in mapped
    ] == [("1", 2, "A", "C,G", 1), ("1", 2, "A", "C,G", 2)]


def test_reserved_source_mapping_info_tag_collision_fails_closed(tmp_path: Path):
    reference = make_reference(tmp_path)
    source = tmp_path / "collision.vcf"
    output = tmp_path / "collision.normalized.vcf.gz"
    source.write_text(
        "##fileformat=VCFv4.3\n"
        '##INFO=<ID=SIRALOOM_ORIG,Number=1,Type=String,Description="Caller field">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tG\t.\tPASS\tSIRALOOM_ORIG=x\n",
        encoding="utf-8",
    )
    with pytest.raises(VCFToolError, match="reserved INFO tag SIRALOOM_ORIG"):
        normalize_vcf_with_bcftools(source, output, reference_fasta=reference)
    assert not output.exists()


def test_golden_mnv_is_not_atomized(tmp_path: Path):
    normalized, *_ = normalize(tmp_path, "1\t2\t.\tAA\tTT\t.\tPASS\t.\n")
    assert normalized == [("1", 2, "AA", "TT")]


def test_golden_ref_mismatch_fails_closed(tmp_path: Path):
    reference = make_reference(tmp_path)
    source = tmp_path / "bad.vcf"
    output = tmp_path / "normalized.vcf.gz"
    write_vcf(source, "1\t2\t.\tC\tG\t.\tPASS\t.\n")
    with pytest.raises(VCFToolError, match="reference-aware normalization failed"):
        normalize_vcf_with_bcftools(source, output, reference_fasta=reference, expected_bcftools_version="1.24")


def test_golden_unknown_contig_fails_bcftools(tmp_path: Path):
    reference = make_reference(tmp_path)
    source = tmp_path / "bad.vcf"
    output = tmp_path / "normalized.vcf.gz"
    write_vcf(source, "2\t2\t.\tA\tG\t.\tPASS\t.\n")
    with pytest.raises(VCFToolError):
        normalize_vcf_with_bcftools(source, output, reference_fasta=reference)


def test_golden_normalization_is_idempotent_at_variant_representation_level(tmp_path: Path):
    reference = make_reference(tmp_path)
    source = tmp_path / "input.vcf"
    first = tmp_path / "first.vcf.gz"
    second = tmp_path / "second.vcf.gz"
    write_vcf(source, "1\t4\t.\tAA\tA\t.\tPASS\t.\n")
    normalize_vcf_with_bcftools(source, first, reference_fasta=reference)
    normalize_vcf_with_bcftools(
        first,
        second,
        reference_fasta=reference,
        preserve_existing_source_mapping=True,
    )
    assert records(first) == records(second)


def test_pinned_bcftools_trims_unseen_gvcf_wildcard_without_changing_called_genotype(tmp_path: Path):
    from backend.app.domain.vcf_tools import route_vcf_records

    reference = make_reference(tmp_path)
    source = tmp_path / "sample.g.vcf"
    source.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=7>\n"
        '##ALT=<ID=NON_REF,Description="Any possible alternate allele">\n'
        '##INFO=<ID=AF,Number=A,Type=Float,Description="Allele frequency">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths">\n'
        '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Phred likelihoods">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
        "1\t1\t.\tC\t<NON_REF>\t.\tPASS\t.\tGT:AD:PL\t0/0:20,0:0,40,400\n"
        "1\t2\trsG\tA\tG,<NON_REF>\t50\tPASS\tAF=0.2,0\tGT:AD:PL\t0/1:15,9,0:100,50,60,40,0,30\n",
        encoding="utf-8",
    )
    routed = route_vcf_records(source, tmp_path / "routed-gvcf")
    assert routed["gvcf_reference_blocks"] == 1
    assert routed["sequence_records"] == 1

    output = tmp_path / "called-variants.normalized.vcf.gz"
    stats = normalize_vcf_with_bcftools(
        routed["sequence_path"], output, reference_fasta=reference,
        expected_bcftools_version="1.24",
    )

    assert stats["tool_version"].split()[1] == "1.24"
    assert stats["gvcf_wildcard_command"] == "bcftools view -A"
    assert records(output) == [("1", 2, "A", "G")]
    with gzip.open(output, "rt", encoding="utf-8") as handle:
        output_lines = list(handle)
    assert not any(
        line.startswith("##bcftools_") and "Command=" in line
        for line in output_lines
    )
    variant = next(line for line in output_lines if not line.startswith("#"))
    fields = variant.rstrip("\n").split("\t")
    assert fields[4] == "G"
    assert fields[7] == "AF=0.2;SIRALOOM_ORIG=1|2|A|G|1"
    assert fields[8] == "GT:AD:PL"
    # Removing allele 2 retains PL entries for 0/0, 0/1, and 1/1; the
    # removed 0/2 and 1/2 likelihoods must not be reassigned to 1/1.
    assert fields[9] == "0/1:15,9:100,50,60"
