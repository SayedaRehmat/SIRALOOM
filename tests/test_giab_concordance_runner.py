from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest

from scripts.validation.run_giab_concordance import (
    ConcordanceError,
    load_sample_mapping,
    parse_happy_summary,
    run_concordance,
    validate_bed_file,
    validate_single_sample_vcf,
    wilson_interval,
)


SUMMARY_HEADER = [
    "Type", "Filter", "TRUTH.TOTAL", "TRUTH.TP", "TRUTH.FN",
    "QUERY.TOTAL", "QUERY.TP", "QUERY.FP", "QUERY.UNK", "FP.gt", "FP.al",
    "METRIC.Recall", "METRIC.Precision", "METRIC.Frac_NA",
]


def _summary(path: Path) -> None:
    rows = [
        ["INDEL", "ALL", 10, 8, 2, 12, 7, 3, 2, 0, 0, 0.8, 0.7, 0.1],
        ["INDEL", "PASS", 10, 7, 3, 10, 7, 1, 2, 0, 0, 0.7, 0.875, 0.2],
        ["SNP", "ALL", 20, 18, 2, 22, 18, 2, 2, 0, 0, 0.9, 0.9, 0.1],
        ["SNP", "PASS", 20, 17, 3, 20, 17, 1, 2, 0, 0, 0.85, 0.9444, 0.1],
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(SUMMARY_HEADER)
        writer.writerows(rows)


def _inputs(tmp_path: Path) -> dict[str, Path]:
    truth = tmp_path / "truth.vcf"
    query = tmp_path / "query.vcf"
    reference = tmp_path / "reference.fa"
    fai = tmp_path / "reference.fa.fai"
    confident = tmp_path / "confident.bed"
    targets = tmp_path / "targets.bed"
    sample_mapping = tmp_path / "sample-mapping.json"
    vcf_header = (
        "##fileformat=VCFv4.2\n"
        "##contig=<ID=chr1,length=1000>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE_PRIVATE_ID\n"
        "chr1\t10\t.\tA\tC\t60\tPASS\t.\tGT\t0/1\n"
    )
    truth.write_text(vcf_header.replace("SAMPLE_PRIVATE_ID", "HG002"), encoding="utf-8")
    query.write_text(vcf_header.replace("SAMPLE_PRIVATE_ID", "CASE_SAMPLE_001"), encoding="utf-8")
    reference.write_text(">chr1\n" + "A" * 1000 + "\n", encoding="utf-8")
    fai.write_text("chr1\t1000\t6\t1000\t1001\n", encoding="utf-8")
    confident.write_text("chr1\t0\t1000\n", encoding="utf-8")
    targets.write_text("chr1\t0\t1000\n", encoding="utf-8")
    sample_mapping.write_text(
        json.dumps({"schema_version": "1.0", "truth_sample_name": "HG002", "query_sample_name": "CASE_SAMPLE_001"}),
        encoding="utf-8",
    )
    sample_mapping.chmod(0o600)
    return {
        "sample_mapping": sample_mapping,
        "truth_vcf": truth,
        "query_vcf": query,
        "reference_fasta": reference,
        "confident_bed": confident,
        "target_regions": targets,
    }


def _fake_happy(tmp_path: Path) -> Path:
    executable = tmp_path / "hap.py"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import csv, pathlib, sys\n"
        "if '--version' in sys.argv:\n"
        " print('hap.py 0.3.15')\n"
        " raise SystemExit(0)\n"
        "prefix = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])\n"
        "with prefix.with_suffix('.summary.csv').open('w', newline='') as handle:\n"
        " writer = csv.writer(handle)\n"
        f" writer.writerow({SUMMARY_HEADER!r})\n"
        " pathlib.Path(str(prefix) + '.runinfo.json').write_text('{}', encoding='utf-8')\n"
        " if '--stratification' in sys.argv:\n"
        "  pathlib.Path(str(prefix) + '.extended.csv').write_text('Type,Subtype,Subset', encoding='utf-8')\n"
        " writer.writerows([\n"
        " ['INDEL','ALL',10,8,2,12,7,3,2,0,0,0.8,0.7,0.1],\n"
        " ['INDEL','PASS',10,7,3,10,7,1,2,0,0,0.7,0.875,0.2],\n"
        " ['SNP','ALL',20,18,2,22,18,2,2,0,0,0.9,0.9,0.1],\n"
        " ['SNP','PASS',20,17,3,20,17,1,2,0,0,0.85,0.9444,0.1],\n"
        " ])\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    return executable


def test_wilson_interval_is_bounded_and_handles_empty_denominator() -> None:
    interval = wilson_interval(8, 10)
    assert interval is not None
    assert 0 <= interval[0] < 0.8 < interval[1] <= 1
    assert wilson_interval(0, 0) is None


def test_parse_happy_summary_recomputes_precision_recall_and_f1(tmp_path: Path) -> None:
    path = tmp_path / "result.summary.csv"
    _summary(path)

    metrics = parse_happy_summary(path)
    indel_all = next(
        item for item in metrics
        if item["variant_type"] == "INDEL" and item["filter"] == "ALL"
    )
    assert indel_all["truth_true_positive"] == 8
    assert indel_all["query_true_positive"] == 7
    assert indel_all["genotype_mismatches"] == 0
    assert indel_all["allele_mismatches"] == 0
    assert indel_all["fraction_not_assessed"] == pytest.approx(2 / 12, abs=1e-6)
    assert indel_all["false_negative"] == 2
    assert indel_all["false_positive"] == 3
    assert indel_all["recall"] == pytest.approx(0.8)
    assert indel_all["precision"] == pytest.approx(0.7)
    assert indel_all["f1"] == pytest.approx(2 * 0.7 * 0.8 / 1.5)
    assert indel_all["recall_wilson_95_ci"] is not None


def test_parse_happy_summary_rejects_non_reconciling_query_counts(tmp_path: Path) -> None:
    path = tmp_path / "query-count-mismatch.summary.csv"
    _summary(path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    rows[1][5] = "999"
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)

    with pytest.raises(ConcordanceError, match="query counts do not reconcile"):
        parse_happy_summary(path)


def test_parse_happy_summary_rejects_mismatch_subcounts_above_false_positives(tmp_path: Path) -> None:
    path = tmp_path / "mismatch-subcounts.csv"
    _summary(path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    rows[1][9] = "4"
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)

    with pytest.raises(ConcordanceError, match="mismatch subcounts exceed QUERY.FP"):
        parse_happy_summary(path)


def test_sample_mapping_sidecar_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "sample-mapping.json"
    path.write_text(
        json.dumps({
            "schema_version": "2.0",
            "truth_sample_name": "HG002",
            "query_sample_name": "CASE_SAMPLE_001",
        }),
        encoding="utf-8",
    )
    path.chmod(0o600)

    with pytest.raises(ConcordanceError, match="schema_version must be 1.0"):
        load_sample_mapping(path)


def test_sample_mapping_sidecar_must_match_both_vcf_columns(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    inputs["sample_mapping"].write_text(
        json.dumps({"schema_version": "1.0", "truth_sample_name": "WRONG_TRUTH", "query_sample_name": "CASE_SAMPLE_001"}),
        encoding="utf-8",
    )
    inputs["sample_mapping"].chmod(0o600)

    with pytest.raises(ConcordanceError, match="explicitly declared specimen mapping") as exc:
        run_concordance(
            truth_vcf=inputs["truth_vcf"],
            query_vcf=inputs["query_vcf"],
            confident_bed=inputs["confident_bed"],
            reference_fasta=inputs["reference_fasta"],
            reference_build="GRCh38",
            assay="WGS",
            caller="approved-caller",
            caller_version="1.0",
            sample_mapping_file=inputs["sample_mapping"],
            truth_set_id="GIAB-HG002-GRCh38",
            truth_set_version="4.2.1",
            acceptance_policy_id="LAB-POLICY-001",
            output_dir=tmp_path / "wrong-sample",
            hap_py=str(_fake_happy(tmp_path)),
        )
    assert "WRONG_TRUTH" not in str(exc.value)
    assert "HG002" not in str(exc.value)
    assert not (tmp_path / "wrong-sample").exists()


def test_sample_mapping_file_must_be_private(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    inputs["sample_mapping"].chmod(0o644)

    with pytest.raises(ConcordanceError, match="permissions must deny group and other access"):
        run_concordance(
            truth_vcf=inputs["truth_vcf"],
            query_vcf=inputs["query_vcf"],
            confident_bed=inputs["confident_bed"],
            reference_fasta=inputs["reference_fasta"],
            reference_build="GRCh38",
            assay="WGS",
            caller="approved-caller",
            caller_version="1.0",
            sample_mapping_file=inputs["sample_mapping"],
            truth_set_id="GIAB-HG002-GRCh38",
            truth_set_version="4.2.1",
            acceptance_policy_id="LAB-POLICY-001",
            output_dir=tmp_path / "out",
            hap_py=str(_fake_happy(tmp_path)),
        )


def test_truth_and_query_sample_columns_must_match_explicit_mapping(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    with pytest.raises(ConcordanceError, match="explicitly declared specimen mapping") as exc:
        validate_single_sample_vcf(inputs["truth_vcf"], "Truth VCF", "WRONG_SAMPLE")
    assert "HG002" not in str(exc.value)
    assert "WRONG_SAMPLE" not in str(exc.value)


@pytest.mark.parametrize(
    ("vcf_text", "error"),
    [
        (
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tCASE_SAMPLE_001\n",
            "fileformat declaration",
        ),
        (
            "##fileformat=VCFv4.2\n"
            "#CHROM\tPOS\tID\tALT\tREF\tQUAL\tFILTER\tINFO\tFORMAT\tCASE_SAMPLE_001\n",
            "nine fixed VCF columns",
        ),
        (
            "##fileformat=VCFv4.2\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tCASE_SAMPLE_001\n"
            "chr1\t10\t.\tA\tC\t60\tPASS\t.\tGT\t0/1\textra\n",
            "malformed variant record",
        ),
    ],
)
def test_single_sample_vcf_requires_specification_header_and_record_cardinality(
    tmp_path: Path, vcf_text: str, error: str
) -> None:
    path = tmp_path / "malformed-query.vcf"
    path.write_text(vcf_text, encoding="utf-8")

    with pytest.raises(ConcordanceError, match=error):
        validate_single_sample_vcf(path, "Query VCF", "CASE_SAMPLE_001")


@pytest.mark.parametrize(
    "bed_line",
    [
        "chr2\t0\t10\n",
        "chr1\t0\t1001\n",
        "chr1\t10\t10\n",
        "track name=confident\n",
        "track\tname=confident\n",
        "chr1\tzero\t10\n",
    ],
)
def test_bed_regions_must_match_reference_contigs_and_bounds(tmp_path: Path, bed_line: str) -> None:
    path = tmp_path / "invalid.bed"
    path.write_text(bed_line, encoding="utf-8")

    with pytest.raises(ConcordanceError):
        validate_bed_file(path, contig_lengths={"chr1": 1000}, label="Test BED")


def test_bed_regions_report_validated_interval_counts_and_hash(tmp_path: Path) -> None:
    path = tmp_path / "valid.bed"
    path.write_text("chr1\t0\t10\nchr1\t20\t30\n", encoding="utf-8")

    result = validate_bed_file(path, contig_lengths={"chr1": 1000}, label="Test BED")

    assert result["record_count"] == 2
    assert result["contig_count"] == 1
    assert result["sha256"]


def test_parse_happy_summary_rejects_incomplete_variant_type_coverage(tmp_path: Path) -> None:
    path = tmp_path / "result.summary.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(SUMMARY_HEADER)
        writer.writerow(["SNP", "ALL", 1, 1, 0, 1, 0, 0, 0, 1, 1, 0])

    with pytest.raises(ConcordanceError, match="SNP and INDEL"):
        parse_happy_summary(path)


def test_reference_fai_must_match_fasta_geometry(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    Path(str(inputs["reference_fasta"]) + ".fai").write_text(
        "chr1\t999\t6\t999\t1000\n", encoding="utf-8"
    )

    with pytest.raises(ConcordanceError, match="FASTA and FAI geometry are inconsistent"):
        run_concordance(
            truth_vcf=inputs["truth_vcf"],
            query_vcf=inputs["query_vcf"],
            confident_bed=inputs["confident_bed"],
            reference_fasta=inputs["reference_fasta"],
            reference_build="GRCh38",
            assay="WGS",
            caller="approved-caller",
            caller_version="1.0",
            sample_mapping_file=inputs["sample_mapping"],
            truth_set_id="GIAB-HG002-GRCh38",
            truth_set_version="4.2.1",
            acceptance_policy_id="LAB-POLICY-001",
            output_dir=tmp_path / "invalid-reference",
            hap_py=str(_fake_happy(tmp_path)),
        )


def test_wes_run_requires_assay_target_bed(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    with pytest.raises(ConcordanceError, match="target BED"):
        run_concordance(
            truth_vcf=inputs["truth_vcf"],
            query_vcf=inputs["query_vcf"],
            confident_bed=inputs["confident_bed"],
            reference_fasta=inputs["reference_fasta"],
            reference_build="GRCh38",
            assay="WES",
            caller="approved-caller",
            caller_version="1.0",
            sample_mapping_file=inputs["sample_mapping"],
            truth_set_id="GIAB-HG002-GRCh38",
            truth_set_version="4.2.1",
            acceptance_policy_id="LAB-POLICY-001",
            output_dir=tmp_path / "out",
        )


def test_controlled_giab_run_records_hashes_and_review_boundary(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    fake_happy = _fake_happy(tmp_path)
    output = tmp_path / "evidence"
    report = run_concordance(
        truth_vcf=inputs["truth_vcf"],
        query_vcf=inputs["query_vcf"],
        confident_bed=inputs["confident_bed"],
        reference_fasta=inputs["reference_fasta"],
        reference_build="GRCh38",
        assay="WES",
        caller="approved-caller",
        caller_version="1.2.3",
        sample_mapping_file=inputs["sample_mapping"],
        truth_set_id="GIAB-HG002-GRCh38",
        truth_set_version="4.2.1",
        acceptance_policy_id="LAB-POLICY-001",
        output_dir=output,
        hap_py=str(fake_happy),
        target_regions=inputs["target_regions"],
        pass_only=False,
    )

    assert report["status"] == "CONCORDANCE_RUN_COMPLETE_REVIEW_REQUIRED"
    assert report["environment"]["hap_py_version"] == "0.3.15"
    assert report["intended_use_cell"]["assay"] == "WES"
    assert report["intended_use_cell"]["truth_set_version"] == "4.2.1"
    assert report["intended_use_cell"]["acceptance_policy_id"] == "LAB-POLICY-001"
    assert report["inputs"]["truth_vcf"]["sha256"]
    assert report["reference_identity"]["declared_build"] == "GRCh38"
    assert report["reference_identity"]["fai_sha256"]
    assert report["reference_identity"]["contig_manifest_sha256"]
    assert report["region_validation"]["confident_bed"]["record_count"] == 1
    assert report["region_validation"]["target_regions"]["record_count"] == 1
    assert len(report["metrics"]) == 4
    assert report["sample_mapping_schema_version"] == "1.0"
    assert report["sample_identifiers_recorded"] is False
    assert report["sample_identity"]["truth_sample_column_verified"] is True
    assert report["sample_identity"]["query_sample_column_verified"] is True
    serialized = json.dumps(report)
    assert "SAMPLE_PRIVATE_ID" not in serialized
    assert "CASE_SAMPLE_001" not in serialized
    assert report["inputs"]["sample_mapping"]["sha256"]
    assert (output / "giab-concordance.json").is_file()
    assert (output / "hap.py.log").is_file()
    assert os.stat(output).st_mode & 0o777 == 0o700


def test_query_must_have_exactly_one_sample(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    inputs["query_vcf"].write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\tS2\n",
        encoding="utf-8",
    )
    with pytest.raises(ConcordanceError, match="exactly one"):
        run_concordance(
            truth_vcf=inputs["truth_vcf"],
            query_vcf=inputs["query_vcf"],
            confident_bed=inputs["confident_bed"],
            reference_fasta=inputs["reference_fasta"],
            reference_build="GRCh38",
            assay="WGS",
            caller="approved-caller",
            caller_version="1.0",
            sample_mapping_file=inputs["sample_mapping"],
            truth_set_id="GIAB-HG002-GRCh38",
            truth_set_version="4.2.1",
            acceptance_policy_id="LAB-POLICY-001",
            output_dir=tmp_path / "out",
            hap_py=str(_fake_happy(tmp_path)),
        )


def test_symbolic_small_variant_input_is_rejected(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    inputs["query_vcf"].write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tCASE_SAMPLE_001\n"
        "chr1\t10\t.\tA\t<DEL>\t60\tPASS\t.\tGT\t0/1\n",
        encoding="utf-8",
    )
    with pytest.raises(ConcordanceError, match="symbolic"):
        run_concordance(
            truth_vcf=inputs["truth_vcf"],
            query_vcf=inputs["query_vcf"],
            confident_bed=inputs["confident_bed"],
            reference_fasta=inputs["reference_fasta"],
            reference_build="GRCh38",
            assay="WGS",
            caller="approved-caller",
            caller_version="1.0",
            sample_mapping_file=inputs["sample_mapping"],
            truth_set_id="GIAB-HG002-GRCh38",
            truth_set_version="4.2.1",
            acceptance_policy_id="LAB-POLICY-001",
            output_dir=tmp_path / "out",
            hap_py=str(_fake_happy(tmp_path)),
        )


def test_existing_evidence_directory_is_not_modified_by_failed_cli_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    output = tmp_path / "existing-evidence"
    output.mkdir()
    sentinel = output / "reviewed-result.json"
    sentinel.write_text('{"reviewed": true}\n', encoding="utf-8")
    inputs = _inputs(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_giab_concordance.py",
            "--truth-vcf", str(inputs["truth_vcf"]),
            "--query-vcf", str(inputs["query_vcf"]),
            "--confident-bed", str(inputs["confident_bed"]),
            "--reference-fasta", str(inputs["reference_fasta"]),
            "--reference-build", "GRCh38",
            "--assay", "WGS",
            "--caller", "approved-caller",
            "--caller-version", "1.0",
            "--sample-mapping-file", str(inputs["sample_mapping"]),
            "--truth-set-id", "GIAB-HG002-GRCh38",
            "--truth-set-version", "4.2.1",
            "--acceptance-policy-id", "LAB-POLICY-001",
            "--output-dir", str(output),
        ],
    )

    from scripts.validation import run_giab_concordance

    assert run_giab_concordance.main() == 2
    assert sentinel.read_text(encoding="utf-8") == '{"reviewed": true}\n'
    assert sorted(path.name for path in output.iterdir()) == ["reviewed-result.json"]


def test_stratification_extended_output_is_required_and_hashed(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    stratification = tmp_path / "stratification.tsv"
    stratification.write_text("coding\tcoding.bed\n", encoding="utf-8")
    (tmp_path / "coding.bed").write_text("chr1\t0\t1000\n", encoding="utf-8")
    report = run_concordance(
        truth_vcf=inputs["truth_vcf"],
        query_vcf=inputs["query_vcf"],
        confident_bed=inputs["confident_bed"],
        reference_fasta=inputs["reference_fasta"],
        reference_build="GRCh38",
        assay="WGS",
        caller="approved-caller",
        caller_version="1.0",
        sample_mapping_file=inputs["sample_mapping"],
        truth_set_id="GIAB-HG002-GRCh38",
        truth_set_version="4.2.1",
        acceptance_policy_id="LAB-POLICY-001",
        output_dir=tmp_path / "stratified-output",
        hap_py=str(_fake_happy(tmp_path)),
        stratification_tsv=stratification,
    )
    assert report["source_artifacts"]["hap_py_extended"] == "comparison.extended.csv"
    assert report["source_artifacts"]["hap_py_extended_sha256"]
    assert report["inputs"]["stratification_tsv"]["sha256"]
    assert report["stratification_regions"][0]["name"] == "coding"
    assert report["stratification_regions"][0]["sha256"]
