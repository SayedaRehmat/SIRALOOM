from pathlib import Path
import subprocess

import pytest

from backend.app.domain.vcf_tools import VCFToolError, classify_records, normalize_vcf_with_bcftools


def make_reference(tmp_path: Path) -> Path:
    fasta = tmp_path / "GRCh38.fa"
    # Small synthetic reference used only to qualify the bcftools invocation.
    sequence = "CAAAAAC"
    fasta.write_text(f">1\n{sequence}\n", encoding="utf-8")
    # FASTA geometry: header is 3 bytes; sequence line is 7 bases + newline.
    (tmp_path / "GRCh38.fa.fai").write_text(
        f"1\t{len(sequence)}\t3\t{len(sequence)}\t{len(sequence) + 1}\n",
        encoding="utf-8",
    )
    return fasta


def test_bcftools_reference_aware_normalization_splits_and_left_aligns(tmp_path: Path):
    if subprocess.run(["which", "bcftools"], capture_output=True).returncode != 0:
        pytest.skip("bcftools is not installed outside CI")
    fasta = make_reference(tmp_path)
    input_vcf = tmp_path / "input.vcf"
    output_vcf = tmp_path / "normalized.vcf.gz"
    input_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=7>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t4\t.\tAA\tA,C\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    result = normalize_vcf_with_bcftools(
        input_vcf,
        output_vcf,
        reference_fasta=fasta,
        expected_bcftools_version="1.19",
    )

    assert result["tool"] == "bcftools"
    assert result["tool_version"] == "bcftools 1.19"
    assert result["expected_tool_version"] == "1.19"
    assert result["reference_check"] == "error"
    assert result["multiallelic_mode"] == "SPLIT_WITH_BCFTOOLS"
    import gzip
    assert Path(str(output_vcf) + ".csi").is_file()
    with gzip.open(output_vcf, "rt", encoding="utf-8") as handle:
        lines = [
            line for line in handle.read().splitlines()
            if line and not line.startswith("#")
        ]
    assert len(lines) == 2
    assert lines[0].split("\t")[0:5] == ["1", "1", ".", "CA", "C"]
    assert lines[1].split("\t")[0:5] == ["1", "4", ".", "AA", "C"]


def test_bcftools_rejects_reference_allele_mismatch(tmp_path: Path):
    if subprocess.run(["which", "bcftools"], capture_output=True).returncode != 0:
        pytest.skip("bcftools is not installed outside CI")
    fasta = make_reference(tmp_path)
    input_vcf = tmp_path / "bad.vcf"
    output_vcf = tmp_path / "normalized.vcf.gz"
    input_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tC\tA\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    with pytest.raises(VCFToolError, match="reference-aware normalization failed"):
        normalize_vcf_with_bcftools(
            input_vcf,
            output_vcf,
            reference_fasta=fasta,
            expected_bcftools_version="1.19",
        )


def test_bcftools_version_pin_rejects_mismatch(tmp_path: Path):
    if subprocess.run(["which", "bcftools"], capture_output=True).returncode != 0:
        pytest.skip("bcftools is not installed outside CI")
    fasta = make_reference(tmp_path)
    input_vcf = tmp_path / "input.vcf"
    output_vcf = tmp_path / "normalized.vcf.gz"
    input_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=7>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t4\t.\tAA\tA\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    with pytest.raises(VCFToolError, match="version mismatch"):
        normalize_vcf_with_bcftools(
            input_vcf,
            output_vcf,
            reference_fasta=fasta,
            expected_bcftools_version="0.0.0",
        )



def test_failed_normalization_preserves_existing_vcf_and_index(tmp_path: Path):
    if subprocess.run(["which", "bcftools"], capture_output=True).returncode != 0:
        pytest.skip("bcftools is not installed outside CI")
    fasta = make_reference(tmp_path)
    input_vcf = tmp_path / "bad.vcf"
    output_vcf = tmp_path / "normalized.vcf.gz"
    index_path = Path(str(output_vcf) + ".csi")
    input_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tC\tA\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    output_vcf.write_bytes(b"previous-valid-vcf")
    index_path.write_bytes(b"previous-valid-index")

    with pytest.raises(VCFToolError, match="reference-aware normalization failed"):
        normalize_vcf_with_bcftools(
            input_vcf,
            output_vcf,
            reference_fasta=fasta,
            expected_bcftools_version="1.19",
        )

    assert output_vcf.read_bytes() == b"previous-valid-vcf"
    assert index_path.read_bytes() == b"previous-valid-index"


def test_index_failure_preserves_existing_vcf_and_index(monkeypatch, tmp_path: Path):
    import backend.app.domain.vcf_tools as vcf_tools

    fasta = make_reference(tmp_path)
    input_vcf = tmp_path / "input.vcf"
    output_vcf = tmp_path / "normalized.vcf.gz"
    index_path = Path(str(output_vcf) + ".csi")
    input_vcf.write_text("dummy input\n", encoding="utf-8")
    output_vcf.write_bytes(b"previous-valid-vcf")
    index_path.write_bytes(b"previous-valid-index")
    monkeypatch.setattr(vcf_tools, "bcftools_available", lambda: True)

    def fake_run(command, **kwargs):
        if command[1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="bcftools 1.19\n", stderr="")
        if command[1] in {"norm", "sort"}:
            target = Path(command[command.index("-o") + 1])
            target.write_bytes(b"staged-" + command[1].encode())
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[1] == "index":
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="injected index failure")
        raise AssertionError(f"Unexpected command: {command!r}")

    monkeypatch.setattr(vcf_tools.subprocess, "run", fake_run)
    with pytest.raises(VCFToolError, match="CSI indexing failed"):
        normalize_vcf_with_bcftools(
            input_vcf,
            output_vcf,
            reference_fasta=fasta,
            expected_bcftools_version="1.19",
        )

    assert output_vcf.read_bytes() == b"previous-valid-vcf"
    assert index_path.read_bytes() == b"previous-valid-index"
    assert not list(tmp_path.glob(".normalized.vcf.gz.siraloom-*"))


def test_classify_records_reports_multiallelic_symbolic_and_gvcf_markers(tmp_path: Path):
    path = tmp_path / "classes.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##ALT=<ID=NON_REF,Description=\"Represents any possible alternative allele at this location\">\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tC,G\t.\tPASS\t.\n"
        "1\t3\t.\tA\t<DEL>\t.\tPASS\t.\n"
        "1\t4\t.\tA\t<NON_REF>\t.\tPASS\tEND=10\n",
        encoding="utf-8",
    )

    profile = classify_records(path)

    assert profile == {
        "records": 3,
        "multiallelic_records": 1,
        "symbolic_records": 2,
        "gvcf_markers": 1,
    }


def test_bcftools_multiallelic_split_preserves_genotype_and_allele_cardinality(tmp_path: Path):
    if subprocess.run(["which", "bcftools"], capture_output=True).returncode != 0:
        pytest.skip("bcftools is not installed outside CI")
    fasta = make_reference(tmp_path)
    input_vcf = tmp_path / "multiallelic-genotypes.vcf"
    output_vcf = tmp_path / "normalized-genotypes.vcf.gz"
    input_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=7>\n"
        "##INFO=<ID=AF,Number=A,Type=Float,Description=\"Allele frequency\">\n"
        "##INFO=<ID=AC,Number=A,Type=Integer,Description=\"Allele count\">\n"
        "##INFO=<ID=AN,Number=1,Type=Integer,Description=\"Allele number\">\n"
        "##FORMAT=<ID=GT,Number=1,Type=String,Description=\"Genotype\">\n"
        "##FORMAT=<ID=AD,Number=R,Type=Integer,Description=\"Allelic depths\">\n"
        "##FORMAT=<ID=PL,Number=G,Type=Integer,Description=\"Phred likelihoods\">\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t4\trsMulti\tA\tC,G\t50\tPASS\tAF=0.2,0.3;AC=2,3;AN=10\tGT:AD:PL\t1/2:10,4,6:100,50,60,40,0,30\n",
        encoding="utf-8",
    )

    normalize_vcf_with_bcftools(
        input_vcf,
        output_vcf,
        reference_fasta=fasta,
        expected_bcftools_version="1.19",
    )

    import gzip

    with gzip.open(output_vcf, "rt", encoding="utf-8") as handle:
        records = [
            line.split("\t")
            for line in handle
            if line and not line.startswith("#")
        ]

    assert len(records) == 2
    assert [record[4] for record in records] == ["C", "G"]
    assert [record[2] for record in records] == ["rsMulti", "rsMulti"]

    # Number=A INFO fields must be reduced to the selected ALT for each split row.
    info = [dict(item.split("=", 1) for item in record[7].split(";") if "=" in item) for record in records]
    assert [row["AF"] for row in info] == ["0.2", "0.3"]
    assert [row["AC"] for row in info] == ["2", "3"]
    assert [row["AN"] for row in info] == ["10", "10"]

    # GT must refer to the retained ALT in each row. Number=R AD and Number=G PL
    # must have the biallelic cardinality after splitting.
    samples = [record[9].split(":") for record in records]
    assert [sample[0] for sample in samples] == ["1/0", "0/1"]
    assert all(len(sample[1].split(",")) == 2 for sample in samples)
    assert all(len(sample[2].split(",")) == 3 for sample in samples)
