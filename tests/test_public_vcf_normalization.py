"""Real GIAB HG002 VCF and GRCh38 reference normalization qualification.

The source is the NIST/GIAB HG002 v4.2.1 GRCh38 benchmark VCF. CI downloads
the official BGZF VCF and TBI, extracts a bounded chromosome-1 interval with
the pinned BCFtools toolchain, and normalizes it against the Ensembl GRCh38
chromosome-1 reference. All downloaded data stays in runner temporary storage;
only checksums, execution metadata and the small normalized result are retained.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.app.domain.vcf_tools import normalize_vcf_with_bcftools, route_vcf_records
from backend.app.domain.vcf_validation import (
    read_vcf_fileformat,
    validate_vcf_reference_alleles,
    validate_vcf_strict,
)


GIAB_VCF_SOURCE = (
    "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/"
    "AshkenazimTrio/HG002_NA24385_son/NISTv4.2.1/GRCh38/"
    "HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz"
)
ENSEMBL_REFERENCE_SOURCE = (
    "https://ftp.ensembl.org/pub/release-115/fasta/homo_sapiens/dna/"
    "Homo_sapiens.GRCh38.dna.chromosome.1.fa.gz"
)
EXPECTED_REFERENCE_ARCHIVE_SHA256 = (
    "05d4d42ed292962055afb9774a1a29a691d7b285fd85dbf9069c050a273e0d3c"
)
EXPECTED_GIAB_VCF_SHA256 = "adb4d4a50048aa13353a06b84fcfcbca09a5d17525efaa4cea44f8822e81175c"
EXPECTED_GIAB_INDEX_SHA256 = "23162712553413b10f88916c28bd1238deb703a7237be2910440773beea71894"
EXPECTED_GIAB_SLICE_SHA256 = "cddf1c35ad301947a73b9e38c416ef6a056fc3ab6533ff4b288b3c61c2c4c776"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reference_with_contig_name(reference: Path, contig: str, data_dir: Path) -> Path:
    """Alias the single reference contig to the VCF header without changing bases."""
    with reference.open("rb") as source:
        header = source.readline()
        original_name = header[1:].split(None, 1)[0].decode("ascii")
        if original_name == contig:
            return reference
        aliased = data_dir / f"GRCh38.reference-for-{contig}.fa"
        with aliased.open("wb") as destination:
            destination.write(f">{contig}\n".encode("ascii"))
            shutil.copyfileobj(source, destination)
    return aliased


def _build_single_contig_fai(fasta_path: Path) -> Path:
    """Build a standards-compatible FAI for a one-contig, line-wrapped FASTA."""
    with fasta_path.open("rb") as handle:
        header = handle.readline()
        if not header.startswith(b">"):
            raise AssertionError("Downloaded reference FASTA has no header.")
        name = header[1:].split(None, 1)[0].decode("ascii")
        sequence_offset = handle.tell()
        first_sequence_line = handle.readline()
        if not first_sequence_line or first_sequence_line.startswith(b">"):
            raise AssertionError("Downloaded reference FASTA has no sequence.")
        line_bases = len(first_sequence_line.rstrip(b"\r\n"))
        line_width = len(first_sequence_line)
        if line_bases <= 0:
            raise AssertionError("Downloaded reference FASTA has an empty sequence line.")
        sequence_length = line_bases
        previous_line_bases = line_bases
        while True:
            line = handle.readline()
            if not line:
                break
            if line.startswith(b">"):
                raise AssertionError("Expected exactly one chromosome in the reference FASTA.")
            bases = len(line.rstrip(b"\r\n"))
            if bases <= 0:
                raise AssertionError("Downloaded reference FASTA contains an empty sequence line.")
            if previous_line_bases != line_bases:
                raise AssertionError("Only the final FASTA sequence line may be shorter.")
            if bases > line_bases:
                raise AssertionError("FASTA sequence line exceeds the indexed line width.")
            sequence_length += bases
            previous_line_bases = bases
    fai_path = Path(f"{fasta_path}.fai")
    fai_path.write_text(
        f"{name}\t{sequence_length}\t{sequence_offset}\t{line_bases}\t{line_width}\n",
        encoding="ascii",
    )
    return fai_path


def _restrict_header_to_single_contig(
    source_bgzf: Path,
    destination_vcf: Path,
    contig: str,
) -> Path:
    """Keep source records unchanged while limiting the test header to its used contig."""
    with gzip.open(source_bgzf, "rt", encoding="utf-8") as source, destination_vcf.open(
        "w", encoding="utf-8", newline="\n"
    ) as destination:
        for line in source:
            if line.startswith("##contig=<ID="):
                declared_contig = line.split("##contig=<ID=", 1)[1].split(",", 1)[0].split(">", 1)[0]
                if declared_contig != contig:
                    continue
            destination.write(line)
    return destination_vcf


def test_bcftools_release_parses_valid_vcf_versions_and_v45_features(tmp_path: Path):
    """Exercise the actual selected BCFtools binary against VCFv4.1-v4.5 files."""
    executable = os.getenv("SIRALOOM_PUBLIC_BCFTOOLS_EXECUTABLE", "bcftools")
    manifest_path = Path("backend/app/domain/vcf_conformance_cases.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    fixture_ids = {
        "VCFv4.0": ("legacy_minimal_snp_parser_smoke",),
        "VCFv4.1": ("minimal_snp_valid", "multiallelic_genotype_valid"),
        "VCFv4.2": ("minimal_snp_valid", "multiallelic_genotype_valid"),
        "VCFv4.3": ("minimal_snp_valid", "multiallelic_genotype_valid"),
        "VCFv4.4": ("minimal_snp_valid", "multiallelic_genotype_valid"),
        "VCFv4.5": (
            "minimal_snp_valid",
            "multiallelic_genotype_valid",
            "local_allele_encoding_valid",
            "base_modification_fraction_valid",
            "unspecified_allele_len_reference_block_valid",
        ),
    }

    for version, case_ids in fixture_ids.items():
        cases = {case["id"]: case for case in manifest["versions"][version]}
        for case_id in case_ids:
            case = cases[case_id]
            assert case["expected"] == "PASS"
            source = tmp_path / f"{version}-{case_id}.vcf"
            output = tmp_path / f"{version}-{case_id}.roundtrip.vcf"
            source.write_text("\n".join(case["lines"]) + "\n", encoding="utf-8")
            result = subprocess.run(
                [
                    executable,
                    "view",
                    "--no-version",
                    "--output-type",
                    "v",
                    "--output",
                    str(output),
                    str(source),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, (
                f"{version} fixture {case_id} was rejected by {executable}: "
                f"{result.stderr}"
            )
            assert output.is_file() and output.stat().st_size > 0
            assert read_vcf_fileformat(output) == version


def test_downloaded_giab_vcf_validates_and_normalizes_against_grch38(tmp_path: Path):
    source_value = os.getenv("SIRALOOM_PUBLIC_VCF_SLICE_PATH")
    archive_value = os.getenv("SIRALOOM_PUBLIC_VCF_ARCHIVE_PATH")
    index_value = os.getenv("SIRALOOM_PUBLIC_VCF_INDEX_PATH")
    reference_archive_value = os.getenv("SIRALOOM_PUBLIC_REFERENCE_ARCHIVE_PATH")
    reference_value = os.getenv("SIRALOOM_PUBLIC_REFERENCE_PATH")
    contig = os.getenv("SIRALOOM_PUBLIC_REFERENCE_CONTIG")
    data_dir_value = os.getenv("SIRALOOM_PUBLIC_DATA_DIR")
    if not all((
        source_value, archive_value, index_value, reference_archive_value,
        reference_value, contig, data_dir_value,
    )):
        pytest.skip("Pinned GIAB/GRCh38 public-data acquisition is enabled in GitHub Actions only.")

    source = Path(source_value)
    archive = Path(archive_value)
    source_index = Path(index_value)
    reference_archive = Path(reference_archive_value)
    reference = Path(reference_value)
    data_dir = Path(data_dir_value)
    assert source.is_file() and archive.is_file() and source_index.is_file()
    assert reference.is_file() and reference_archive.is_file()
    assert _sha256_file(reference_archive) == EXPECTED_REFERENCE_ARCHIVE_SHA256
    assert _sha256_file(archive) == EXPECTED_GIAB_VCF_SHA256
    assert _sha256_file(source_index) == EXPECTED_GIAB_INDEX_SHA256
    assert _sha256_file(source) == EXPECTED_GIAB_SLICE_SHA256
    assert os.getenv("SIRALOOM_PUBLIC_REFERENCE_SHA256_VERIFIED") == "1"

    assert read_vcf_fileformat(archive) == "VCFv4.2"
    assert read_vcf_fileformat(source) == "VCFv4.2"
    reference_for_vcf = _reference_with_contig_name(reference, contig, data_dir)
    _build_single_contig_fai(reference_for_vcf)

    source_for_validation = _restrict_header_to_single_contig(
        source,
        data_dir / "giab-hg002-grch38-chr1-1-5000000.vcf",
        contig,
    )
    source_validation = validate_vcf_strict(
        source_for_validation,
        reference_contigs={contig},
    )
    assert source_validation["fileformat"] == "VCFv4.2"
    assert source_validation["records"] > 0
    assert source_validation["sample_count"] == 1

    reference_validation = validate_vcf_reference_alleles(
        source_for_validation,
        reference_for_vcf,
    )
    assert reference_validation["checked_record_count"] == source_validation["records"]

    routing = route_vcf_records(source_for_validation, data_dir / "routed")
    assert routing["record_reconciliation"]["balanced"] is True
    assert routing["sequence_records"] == source_validation["records"]
    assert routing["cnv_variant_records"] == 0
    assert routing["repeat_expansion_records"] == 0
    assert routing["structural_variant_records"] == 0

    output = data_dir / "giab-hg002-grch38-chr1.normalized.vcf.gz"
    bcftools_executable = os.getenv("SIRALOOM_PUBLIC_BCFTOOLS_EXECUTABLE", "bcftools")
    expected_bcftools_version = os.getenv("SIRALOOM_PUBLIC_BCFTOOLS_VERSION", "1.25")
    execution = normalize_vcf_with_bcftools(
        routing["sequence_path"],
        output,
        reference_fasta=reference_for_vcf,
        expected_bcftools_version=expected_bcftools_version,
        bcftools_executable=bcftools_executable,
    )
    output_validation = validate_vcf_strict(output, reference_contigs={contig})
    assert output_validation["fileformat"] == "VCFv4.2"
    assert output_validation["records"] > 0
    reconciliation = execution["source_child_reconciliation"]
    assert reconciliation["status"] == "VALIDATED"
    assert reconciliation["balanced"] is True
    assert reconciliation["source_records"] == source_validation["records"]
    assert reconciliation["normalized_child_records"] == output_validation["records"]
    assert execution["tool_version"] == f"bcftools {expected_bcftools_version}"
    assert execution["reference_check"] == "error"
    assert execution["compression"] == "BGZF"
    assert execution["index"] == "CSI"
    assert Path(execution["index_path"]).is_file()
    assert execution["executable_integrity_status"] == "MEASURED_UNPINNED"
    assert len(execution["executable_sha256"]) == 64
    reference_artifacts = execution["reference_identity"]["artifacts"]
    assert reference_artifacts["fasta"]["sha256"] == _sha256_file(reference_for_vcf)
    assert reference_artifacts["fai"]["sha256"] == _sha256_file(
        Path(f"{reference_for_vcf}.fai")
    )

    report = {
        "suite": "siraloom-giab-public-vcf-normalization-qualification-v1",
        "vcf_source": GIAB_VCF_SOURCE,
        "vcf_archive_sha256": _sha256_file(archive),
        "vcf_index_sha256": _sha256_file(source_index),
        "vcf_slice_sha256": _sha256_file(source),
        "vcf_fileformat": source_validation["fileformat"],
        "source_record_count": source_validation["records"],
        "source_sample_count": source_validation["sample_count"],
        "reference_validation": reference_validation,
        "routing_summary": routing,
        "source_child_reconciliation": reconciliation,
        "reference_source": ENSEMBL_REFERENCE_SOURCE,
        "reference_archive_sha256": _sha256_file(reference_archive),
        "reference_contig": contig,
        "reference_fasta_sha256": _sha256_file(reference_for_vcf),
        "reference_index_sha256": _sha256_file(Path(f"{reference_for_vcf}.fai")),
        "normalized_vcf_sha256": _sha256_file(output),
        "normalized_index_sha256": _sha256_file(Path(execution["index_path"])),
        "normalized_validation": output_validation,
        "normalization_execution": execution,
        "expected_bcftools_version": expected_bcftools_version,
    }
    (data_dir / "qualification-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
