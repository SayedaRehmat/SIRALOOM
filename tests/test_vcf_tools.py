import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.app.domain.vcf_tools import (
    MULTIALLELIC_OVERLAP_POLICY,
    VCFToolError,
    classify_records,
    normalize_vcf_with_bcftools,
)


def require_bcftools() -> None:
    if shutil.which("bcftools") is None:
        pytest.skip("bcftools is required for production normalization tests")


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
    require_bcftools()
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
        expected_bcftools_version="1.24",
    )

    assert result["tool"] == "bcftools"
    assert result["tool_version"] == "bcftools 1.24"
    assert result["expected_tool_version"] == "1.24"
    assert result["reference_check"] == "error"
    reference_identity = result["reference_identity"]
    assert reference_identity["method"] == "SHA256_REFERENCE_FASTA_AND_INDEX_ARTIFACTS"
    assert reference_identity["artifacts"]["fasta"]["sha256"] == hashlib.sha256(
        fasta.read_bytes()
    ).hexdigest()
    fai_path = Path(str(fasta) + ".fai")
    assert reference_identity["artifacts"]["fai"]["sha256"] == hashlib.sha256(
        fai_path.read_bytes()
    ).hexdigest()
    assert reference_identity["artifacts"]["fasta"]["size_bytes"] == fasta.stat().st_size
    assert result["multiallelic_mode"] == "SPLIT_WITH_BCFTOOLS"
    assert result["multiallelic_overlap_policy"] == MULTIALLELIC_OVERLAP_POLICY
    assert "--multi-overlaps 0" in result["command"]
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


def test_router_source_identity_reconciles_normalized_multiallelic_children(tmp_path: Path):
    require_bcftools()
    from backend.app.domain.vcf_tools import route_vcf_records

    fasta = make_reference(tmp_path)
    source = tmp_path / "source.vcf"
    routed_dir = tmp_path / "routed"
    output_vcf = tmp_path / "normalized.vcf.gz"
    source.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=7>\n"
        '##ALT=<ID=NON_REF,Description="Any possible alternate allele">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
        "1\t2\t.\tA\tC,<NON_REF>,G\t.\tPASS\t.\tGT\t0/1\n"
        "1\t4\t.\tAA\tA,C\t.\tPASS\t.\tGT\t0/1\n",
        encoding="utf-8",
    )

    routed = route_vcf_records(source, routed_dir)
    result = normalize_vcf_with_bcftools(
        routed["sequence_path"],
        output_vcf,
        reference_fasta=fasta,
        expected_bcftools_version="1.24",
    )

    assert result["source_child_reconciliation"] == {
        "status": "VALIDATED",
        "method": "IMMUTABLE_SOURCE_PAYLOAD_VS_BCFTOOLS_OLD_RECORD_ALT_MAPPING",
        "source_records": 2,
        "expected_child_records": 4,
        "normalized_child_records": 4,
        "source_alt_mappings": 4,
        "balanced": True,
    }


def test_reference_artifact_mutation_aborts_publication_and_preserves_previous_outputs(
    monkeypatch, tmp_path: Path
):
    import gzip
    import backend.app.domain.vcf_tools as vcf_tools

    fasta = make_reference(tmp_path)
    input_vcf = tmp_path / "input.vcf"
    output_vcf = tmp_path / "normalized.vcf.gz"
    index_path = Path(str(output_vcf) + ".csi")
    input_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    output_vcf.write_bytes(b"previous-valid-vcf")
    index_path.write_bytes(b"previous-valid-index")
    monkeypatch.setattr(vcf_tools, "bcftools_available", lambda: True)

    def fake_run(command, **kwargs):
        if command[1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="bcftools 1.24\n", stderr="")
        if command[1] in {"view", "norm", "sort"}:
            target = Path(command[command.index("-o") + 1])
            if command[1] == "sort":
                # Same FASTA geometry, different sequence bytes: size checks alone
                # would miss this change, while SHA-256 attestation must detect it.
                fasta.write_text(">1\nGAAAAAC\n", encoding="utf-8")
            with gzip.open(target, "wt", encoding="utf-8") as handle:
                handle.write(
                    "##fileformat=VCFv4.3\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
                    "1\t2\t.\tA\tG\t.\tPASS\t.\n"
                )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[1] == "index":
            raise AssertionError("Indexing must not run after reference identity changes.")
        raise AssertionError(f"Unexpected command: {command!r}")

    monkeypatch.setattr(vcf_tools.subprocess, "run", fake_run)
    with pytest.raises(VCFToolError, match="Reference FASTA or index artifacts changed"):
        normalize_vcf_with_bcftools(
            input_vcf,
            output_vcf,
            reference_fasta=fasta,
            expected_bcftools_version="1.24",
        )

    assert output_vcf.read_bytes() == b"previous-valid-vcf"
    assert index_path.read_bytes() == b"previous-valid-index"


def test_bcftools_rejects_reference_allele_mismatch(tmp_path: Path):
    require_bcftools()
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
            expected_bcftools_version="1.24",
        )


def test_bcftools_version_pin_rejects_mismatch(tmp_path: Path):
    require_bcftools()
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
    require_bcftools()
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
            expected_bcftools_version="1.24",
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
            return subprocess.CompletedProcess(command, 0, stdout="bcftools 1.24\n", stderr="")
        if command[1] in {"view", "norm", "sort"}:
            target = Path(command[command.index("-o") + 1])
            if command[1] == "view":
                import gzip

                with gzip.open(target, "wt", encoding="utf-8") as handle:
                    handle.write(
                        "##fileformat=VCFv4.3\n"
                        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
                        "1\t1\t.\tA\tG\t.\tPASS\t.\n"
                    )
            else:
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
            expected_bcftools_version="1.24",
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


def test_router_rejects_reserved_source_tag_collision_in_record(tmp_path: Path):
    from backend.app.domain.vcf_tools import route_vcf_records

    source = tmp_path / "reserved-source-tag.vcf"
    source.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t1\t.\tA\tC\t.\tPASS\tSIRALOOM_SOURCE=foreign\n",
        encoding="utf-8",
    )

    with pytest.raises(VCFToolError, match="reserved INFO tag SIRALOOM_SOURCE"):
        route_vcf_records(source, tmp_path / "routed-reserved-tag")


def test_router_preserves_telomere_records_outside_small_variant_stream(tmp_path: Path):
    from backend.app.domain.vcf_tools import route_vcf_records

    source = tmp_path / "telomere.vcf"
    source.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t0\ttelo\tA\tG\t.\tPASS\t.\n"
        "1\t1\trs1\tA\tC\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    routed = route_vcf_records(source, tmp_path / "routed")

    assert routed["records_total"] == 2
    assert routed["telomere_records"] == 1
    assert routed["telomere_after_contig_records"] == 0
    assert routed["sequence_records"] == 1
    assert "1\t0\ttelo" in Path(routed["telomere_path"]).read_text(encoding="utf-8")
    assert "1\t0\ttelo" not in Path(routed["sequence_path"]).read_text(encoding="utf-8")


@pytest.mark.parametrize("reference_lengths", [None, {"1": 100}])
def test_router_preserves_n_plus_one_telomere_records(tmp_path: Path, reference_lengths):
    from backend.app.domain.vcf_tools import route_vcf_records

    source = tmp_path / "telomere-after-contig.vcf"
    header_contig = "##contig=<ID=1,length=100>\n" if reference_lengths is None else ""
    source.write_text(
        "##fileformat=VCFv4.3\n"
        + header_contig
        + "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        + "1\t101\ttelo-after\tA\tG\t.\tPASS\t.\n"
        + "1\t100\trs1\tA\tC\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    routed = route_vcf_records(
        source,
        tmp_path / ("routed-declared" if reference_lengths is None else "routed-reference"),
        reference_contig_lengths=reference_lengths,
    )

    assert routed["records_total"] == 2
    assert routed["telomere_after_contig_records"] == 1
    assert routed["sequence_records"] == 1
    assert "1\t101\ttelo-after" in Path(routed["telomere_after_contig_path"]).read_text(encoding="utf-8")
    assert "1\t101\ttelo-after" not in Path(routed["sequence_path"]).read_text(encoding="utf-8")


def test_gvcf_router_preserves_blocks_and_routes_only_provably_called_variants(tmp_path: Path):
    from backend.app.domain.vcf_tools import route_vcf_records

    source = tmp_path / "mixed.g.vcf"
    source.write_text(
        "##fileformat=VCFv4.3\n"
        '##ALT=<ID=NON_REF,Description="Any possible allele">\n'
        '##INFO=<ID=DP,Number=1,Type=Integer,Description="Depth">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
        "1\t1\t.\tA\t<NON_REF>\t.\tPASS\tEND=10;DP=30\tGT:AD\t0/0:30,0\n"
        "1\t2\t.\tA\t.\t.\tPASS\t.\tGT\t0/0\n"
        "1\t11\trs1\tA\tC,<NON_REF>\t50\tPASS\tDP=24\tGT:AD\t0/1:15,9,0\n"
        "1\t12\trs2\tA\tG,<NON_REF>\t50\tPASS\tDP=21\tGT:AD\t0/2:10,0,11\n",
        encoding="utf-8",
    )

    routed = route_vcf_records(source, tmp_path / "routed")

    assert routed["records_total"] == 4
    assert routed["source_record_count"] == 4
    assert routed["excluded_source_record_count"] == 3
    assert routed["record_reconciliation"] == {
        "method": "SOURCE_RECORD_INDEX_VS_EXCLUSIVE_ROUTING_DISPOSITIONS",
        "source_records": 4,
        "routed_records": 4,
        "delta": 0,
        "balanced": True,
        "disposition_counts": {
            "sequence": 1,
            "gvcf_reference_blocks": 1,
            "gvcf_unresolved_variants": 1,
            "structural_variants": 0,
            "spanning_deletions": 0,
            "telomere_coordinates": 0,
            "after_contig_coordinates": 0,
            "reference_only": 1,
        },
    }
    assert routed["reference_only_records"] == 1
    assert routed["sequence_records"] == 1
    assert routed["gvcf_reference_blocks"] == 1
    assert routed["gvcf_unresolved_variant_records"] == 1
    assert routed["structural_variant_records"] == 0
    assert routed["telomere_records"] == 0
    assert routed["telomere_after_contig_records"] == 0
    assert "0/1:15,9,0" in Path(routed["sequence_path"]).read_text(encoding="utf-8")
    assert "0/0:30,0" in Path(routed["gvcf_blocks_path"]).read_text(encoding="utf-8")
    assert "0/2:10,0,11" in Path(routed["gvcf_unresolved_path"]).read_text(encoding="utf-8")

    exclusions = [
        json.loads(line)
        for line in Path(routed["exclusion_manifest_path"]).read_text(encoding="utf-8").splitlines()
    ]
    assert routed["exclusion_manifest_records"] == 3
    assert [item["source_record_index"] for item in exclusions] == [1, 2, 4]
    assert [item["reason_code"] for item in exclusions] == [
        "GVCF_REFERENCE_CONFIDENCE_ANALYSIS_UNSUPPORTED",
        "NO_ALTERNATE_ALLELE",
        "GVCF_VARIANT_ALLELE_UNRESOLVED",
    ]
    source_records = [line for line in source.read_text(encoding="utf-8").splitlines() if not line.startswith("#")]
    for item in exclusions:
        original = source_records[item["source_record_index"] - 1]
        assert item["source_record_sha256"] == hashlib.sha256(original.encode("utf-8")).hexdigest()
        assert item["chrom"] == original.split("\t")[0]
        assert item["pos"] == original.split("\t")[1]


def test_router_exclusion_manifest_is_absent_when_no_source_records_are_excluded(tmp_path: Path):
    from backend.app.domain.vcf_tools import route_vcf_records

    source = tmp_path / "sequence-only.vcf"
    source.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t1\trs1\tA\tC\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    routed = route_vcf_records(source, tmp_path / "routed-sequence-only")
    assert routed["exclusion_manifest_path"] is None
    assert routed["exclusion_manifest_records"] == 0
    assert routed["source_record_count"] == 1
    assert routed["records_total"] == 1
    assert routed["excluded_source_record_count"] == 0
    assert routed["record_reconciliation"]["balanced"] is True
    assert routed["record_reconciliation"]["delta"] == 0


def test_router_manifests_each_unobserved_source_alt_from_complete_genotypes(tmp_path: Path):
    from backend.app.domain.vcf_tools import route_vcf_records

    source = tmp_path / "reference-genotype-candidates.vcf"
    source.write_text(
        "##fileformat=VCFv4.3\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
        "1\t10\tmulti\tA\tC,G\t.\tPASS\t.\tGT\t0/1\n"
        "1\t11\tref\tA\tT\t.\tPASS\t.\tGT\t0/0\n"
        "1\t12\tpartial\tA\tG\t.\tPASS\t.\tGT\t0/.\n",
        encoding="utf-8",
    )
    routed = route_vcf_records(source, tmp_path / "routed-reference-genotypes")
    entries = [
        json.loads(line)
        for line in Path(routed["exclusion_manifest_path"]).read_text(encoding="utf-8").splitlines()
    ]
    assert routed["sequence_records"] == 3
    assert routed["reference_only_genotype_alleles"] == 2
    # These are per-ALT evidence entries, not whole-record exclusions.
    assert routed["exclusion_manifest_records"] == 2
    assert routed["excluded_source_record_count"] == 0
    assert routed["record_reconciliation"]["balanced"] is True
    assert [
        (entry["source_record_index"], entry.get("source_alt_index"), entry["reason_code"])
        for entry in entries
    ] == [
        (1, 2, "REFERENCE_ONLY_GENOTYPE"),
        (2, 1, "REFERENCE_ONLY_GENOTYPE"),
    ]


def test_bcftools_multiallelic_split_preserves_genotype_and_allele_cardinality(tmp_path: Path):
    require_bcftools()
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
        expected_bcftools_version="1.24",
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


def test_bcftools_multiallelic_split_preserves_phasing_and_sample_order(tmp_path: Path):
    require_bcftools()
    fasta = make_reference(tmp_path)
    input_vcf = tmp_path / "phased-multiallelic.vcf"
    output_vcf = tmp_path / "normalized-phased.vcf.gz"
    input_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=7>\n"
        "##INFO=<ID=AC,Number=A,Type=Integer,Description=\"Allele count\">\n"
        "##FORMAT=<ID=GT,Number=1,Type=String,Description=\"Genotype\">\n"
        "##FORMAT=<ID=PS,Number=1,Type=Integer,Description=\"Phase set\">\n"
        "##FORMAT=<ID=AD,Number=R,Type=Integer,Description=\"Allelic depths\">\n"
        "##FORMAT=<ID=PL,Number=G,Type=Integer,Description=\"Genotype likelihoods\">\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE_A\tSAMPLE_B\tSAMPLE_MISSING\n"
        "1\t4\trsPhased\tA\tC,G\t50\tPASS\tAC=2,3\tGT:PS:AD:PL\t"
        "1|2:10:10,4,6:100,50,60,40,0,30\t2|0:20:8,3,5:50,40,30,20,10,0\t"
        "./.:.:.,.,.:.,.,.,.,.,.\n",
        encoding="utf-8",
    )

    normalize_vcf_with_bcftools(
        input_vcf,
        output_vcf,
        reference_fasta=fasta,
        expected_bcftools_version="1.24",
    )

    import gzip

    with gzip.open(output_vcf, "rt", encoding="utf-8") as handle:
        header = None
        lines = []
        for line in handle:
            if line.startswith("#CHROM"):
                header = line.rstrip("\n").split("\t")
            elif line and not line.startswith("#"):
                lines.append(line)
    records = [line.rstrip("\n").split("\t") for line in lines]

    assert header is not None
    assert header[9:12] == ["SAMPLE_A", "SAMPLE_B", "SAMPLE_MISSING"]
    assert [record[4] for record in records] == ["C", "G"]
    assert [record[9].split(":")[0] for record in records] == ["1|0", "0|1"]
    assert [record[10].split(":")[0] for record in records] == ["0|0", "1|0"]
    assert [record[9].split(":")[1] for record in records] == ["10", "10"]
    assert [record[10].split(":")[1] for record in records] == ["20", "20"]
    assert [record[11].split(":")[0] for record in records] == ["./.", "./."]
    for record in records:
        assert len(record[9].split(":")[2].split(",")) == 2
        assert len(record[10].split(":")[2].split(",")) == 2
        assert len(record[9].split(":")[3].split(",")) == 3
        assert len(record[10].split(":")[3].split(",")) == 3


def test_csi_index_record_counts_match_sequential_bgzf_scan(monkeypatch, tmp_path: Path):
    import gzip
    import backend.app.domain.vcf_tools as vcf_tools

    staged_vcf = tmp_path / "staged.vcf.gz"
    with gzip.open(staged_vcf, "wt", encoding="utf-8") as handle:
        handle.write(
            "##fileformat=VCFv4.3\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
            "1\t1\t.\tA\tG\t.\tPASS\t.\n"
            "1\t2\t.\tC\tT\t.\tPASS\t.\n"
            "2\t4\t.\tG\tA\t.\tPASS\t.\n"
        )

    def fake_run(command, **kwargs):
        assert command[1:3] == ["index", "--stats"]
        return subprocess.CompletedProcess(
            command, 0, stdout="1\t7\t2\n2\t5\t1\n", stderr=""
        )

    monkeypatch.setattr(vcf_tools.subprocess, "run", fake_run)
    result = vcf_tools._validate_csi_index_record_counts(
        staged_vcf, bcftools_executable="bcftools", timeout_seconds=30
    )

    assert result == {
        "method": "CSI_PER_CONTIG_COUNTS_VS_SEQUENTIAL_BGZF_SCAN",
        "records": 3,
        "contigs": 2,
    }


def test_csi_index_record_counts_reject_mismatch_with_sequential_bgzf_scan(
    monkeypatch, tmp_path: Path
):
    import gzip
    import backend.app.domain.vcf_tools as vcf_tools

    staged_vcf = tmp_path / "staged.vcf.gz"
    with gzip.open(staged_vcf, "wt", encoding="utf-8") as handle:
        handle.write(
            "##fileformat=VCFv4.3\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
            "1\t1\t.\tA\tG\t.\tPASS\t.\n"
            "1\t2\t.\tC\tT\t.\tPASS\t.\n"
        )

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 0, stdout="1\t7\t1\n", stderr=""
        )

    monkeypatch.setattr(vcf_tools.subprocess, "run", fake_run)
    with pytest.raises(VCFToolError, match="record counts disagree by contig"):
        vcf_tools._validate_csi_index_record_counts(
            staged_vcf, bcftools_executable="bcftools", timeout_seconds=30
        )
