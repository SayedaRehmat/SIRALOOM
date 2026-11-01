from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest

from scripts.validation.run_giab_concordance import (
    ConcordanceError,
    parse_happy_summary,
    run_concordance,
    wilson_interval,
)


SUMMARY_HEADER = [
    "Type", "Filter", "TRUTH.TOTAL", "TRUTH.TP", "TRUTH.FN",
    "QUERY.TOTAL", "QUERY.TP", "QUERY.FP", "QUERY.UNK", "FP.gt",
    "METRIC.Recall", "METRIC.Precision", "METRIC.Frac_NA",
]


def _summary(path: Path) -> None:
    rows = [
        ["INDEL", "ALL", 10, 8, 2, 12, 7, 3, 2, 0, 0.8, 0.7, 0.1],
        ["INDEL", "PASS", 10, 7, 3, 10, 7, 1, 2, 0, 0.7, 0.875, 0.2],
        ["SNP", "ALL", 20, 18, 2, 22, 18, 2, 2, 0, 0.9, 0.9, 0.1],
        ["SNP", "PASS", 20, 17, 3, 20, 17, 1, 2, 0, 0.85, 0.9444, 0.1],
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
    vcf_header = (
        "##fileformat=VCFv4.2\n"
        "##contig=<ID=chr1,length=1000>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE_PRIVATE_ID\n"
        "chr1\t10\t.\tA\tC\t60\tPASS\t.\tGT\t0/1\n"
    )
    truth.write_text(vcf_header, encoding="utf-8")
    query.write_text(vcf_header, encoding="utf-8")
    reference.write_text(">chr1\n" + "A" * 1000 + "\n", encoding="utf-8")
    fai.write_text("chr1\t1000\t6\t1000\t1001\n", encoding="utf-8")
    confident.write_text("chr1\t0\t1000\n", encoding="utf-8")
    targets.write_text("chr1\t0\t1000\n", encoding="utf-8")
    return {
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
        " ['INDEL','ALL',10,8,2,12,2,2,0,0.8,0.8,0.1],\n"
        " ['INDEL','PASS',10,7,3,10,1,2,0,0.7,0.875,0.2],\n"
        " ['SNP','ALL',20,18,2,22,2,2,0,0.9,0.9,0.1],\n"
        " ['SNP','PASS',20,17,3,20,1,2,0,0.85,0.9444,0.1],\n"
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
    assert indel_all["false_negative"] == 2
    assert indel_all["false_positive"] == 2
    assert indel_all["recall"] == pytest.approx(0.8)
    assert indel_all["precision"] == pytest.approx(0.7)
    assert indel_all["f1"] == pytest.approx(2 * 0.7 * 0.8 / 1.5)
    assert indel_all["recall_wilson_95_ci"] is not None


def test_parse_happy_summary_rejects_incomplete_variant_type_coverage(tmp_path: Path) -> None:
    path = tmp_path / "result.summary.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(SUMMARY_HEADER)
        writer.writerow(["SNP", "ALL", 1, 1, 0, 1, 0, 0, 0, 1, 1, 0])

    with pytest.raises(ConcordanceError, match="SNP and INDEL"):
        parse_happy_summary(path)


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
    assert len(report["metrics"]) == 4
    assert report["sample_identifiers_recorded"] is False
    serialized = json.dumps(report)
    assert "SAMPLE_PRIVATE_ID" not in serialized
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
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
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
