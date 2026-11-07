from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


def _write(
    path: Path, *, format_keys: str, sample: str, version: str = "VCFv4.5"
) -> None:
    path.write_text(
        f"##fileformat={version}\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        f"1\t10\t.\tA\tC,G\t.\tPASS\t.\t{format_keys}\t{sample}\n",
        encoding="utf-8",
    )


def test_vcf45_source_psl_pso_tandem_duplication_example_is_positionally_aligned(
    tmp_path: Path,
):
    # Source example: GT /0/0|1; the three PSL and PSO values align to the
    # three GT allele positions, including MISSING values for unphased alleles.
    path = tmp_path / "psl-pso-source-example.vcf"
    _write(
        path,
        format_keys="GT:PSL:PSO",
        sample="/0/0|1:.,.,chr1*10*3:.,.,3",
    )
    assert validate_vcf_strict(path)["records"] == 1


def test_vcf45_psq_has_one_entry_per_psl_gt_position_even_for_repeated_set_name(
    tmp_path: Path,
):
    path = tmp_path / "psl-psq-repeated-phase-set.vcf"
    _write(
        path,
        format_keys="GT:PSL:PSQ",
        sample="|0|1:chr1*10*1,chr1*10*1:20,20",
    )
    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize(
    ("format_keys", "sample"),
    [
        ("GT:PSL:PSO", "0/1|2:.,set,set:.,5,6"),
        ("GT:PSL:PSQ", "0/1|2:.,set,set:.,5,6"),
    ],
)
def test_vcf45_pso_and_psq_missing_values_align_with_missing_psl_positions(
    tmp_path: Path, format_keys: str, sample: str
):
    path = tmp_path / "psl-dependent-missing-alignment.vcf"
    _write(path, format_keys=format_keys, sample=sample)
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_PHASE_SET_INVALID"


def test_vcf45_local_gt_uses_global_alt_indexes_and_matches_local_projection(
    tmp_path: Path,
):
    path = tmp_path / "local-gt-global-alt-indexes.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=LAA,Number=.,Type=Integer,Description="Local ALT indexes">\n'
        '##FORMAT=<ID=LAD,Number=LR,Type=Integer,Description="Local allele depths">\n'
        '##FORMAT=<ID=LPL,Number=LG,Type=Integer,Description="Local genotype likelihoods">\n'
        '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allele depths">\n'
        '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Genotype likelihoods">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\t.\tG\tA,C,T,<*>\t.\tPASS\t.\tGT:LAA:LAD:LPL:AD:PL\t"
        "2/2:2,4:20,30,10:90,80,0,100,110,120:20,.,30,.,10:"
        "90,.,.,80,.,0,.,.,.,.,100,.,110,.,120\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1

def test_vcf45_pso_is_required_on_every_occurrence_of_phase_set_with_sv_allele(
    tmp_path: Path,
):
    path = tmp_path / "pso-required-across-phase-set.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tdel1\tA\t<DEL>\t.\tPASS\tEND=8\tGT:PSL:PSO\t0|1:set,set:3,3\n"
        "1\t9\tsnv1\tA\tC\t.\tPASS\t.\tGT:PSL:PSO\t0|1:set,set:.,.\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_PHASE_SET_PSO_REQUIRED"


def test_vcf45_pso_is_accepted_when_defined_across_entire_sv_phase_set(
    tmp_path: Path,
):
    path = tmp_path / "pso-defined-across-phase-set.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tdel1\tA\t<DEL>\t.\tPASS\tEND=8\tGT:PSL:PSO\t0|1:set,set:3,3\n"
        "1\t9\tsnv1\tA\tC\t.\tPASS\t.\tGT:PSL:PSO\t0|1:set,set:4,4\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 2


def test_vcf45_breakend_mates_require_identical_sample_psl_and_pso(
    tmp_path: Path,
):
    path = tmp_path / "breakend-phase-mismatch.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tSVTYPE=BND;MATEID=bnd2\tGT:PSL:PSO\t0|1:set,set:3,3\n"
        "2\t10\tbnd2\tA\tA]1:5]\t.\tPASS\tSVTYPE=BND;MATEID=bnd1\tGT:PSL:PSO\t0|1:set,set:3,4\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_BREAKEND_PHASE_SET_MISMATCH"


def test_vcf45_breakend_mates_accept_identical_sample_psl_and_pso(
    tmp_path: Path,
):
    path = tmp_path / "breakend-phase-matched.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tSVTYPE=BND;MATEID=bnd2\tGT:PSL:PSO\t0|1:set,set:2,3\n"
        "2\t10\tbnd2\tA\tA]1:5]\t.\tPASS\tSVTYPE=BND;MATEID=bnd1\tGT:PSL:PSO\t0|1:set,set:2,3\n",
        encoding="utf-8",
    )
    result = validate_vcf_strict(path)
    assert result["records"] == 2
    traversal = next(
        item for item in result["phase_set_traversal_orders"]
        if item["sample"] == "SAMPLE1" and item["phase_set"] == "set"
    )
    assert [event["ordinal"] for event in traversal["ordered_events"]] == [2, 3]
    assert [event["event_kind"] for event in traversal["ordered_events"]] == [
        "RECIPROCAL_BREAKEND_EVENT",
        "RECIPROCAL_BREAKEND_EVENT",
    ]
    assert [len(event["occurrences"]) for event in traversal["ordered_events"]] == [2, 2]


def test_vcf45_local_gt_2_4_remains_global_alt_indexes_not_local_indexes(
    tmp_path: Path,
):
    # This preserves the literal source-row GT while independently checking
    # that LAA=2,4 projects local likelihood vectors using global ALT indexes.
    # The source example's PL/LPL most-likely genotype discrepancy is retained
    # as a source ambiguity; the validator must not rewrite GT or equate GT to argmin(PL).
    path = tmp_path / "local-gt-source-row-global-indexes.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=LAA,Number=.,Type=Integer,Description="Local ALT indexes">\n'
        '##FORMAT=<ID=LAD,Number=LR,Type=Integer,Description="Local allele depths">\n'
        '##FORMAT=<ID=LPL,Number=LG,Type=Integer,Description="Local genotype likelihoods">\n'
        '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allele depths">\n'
        '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Genotype likelihoods">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\t.\tG\tA,C,T,<*>\t.\tPASS\t.\tGT:LAA:LAD:LPL:AD:PL\t"
        "2/4:2,4:20,30,10:90,80,0,100,110,120:20,.,30,.,10:"
        "90,.,.,80,.,0,.,.,.,.,100,.,110,.,120\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1

def test_vcf45_psq_repeated_phase_set_positions_may_have_distinct_values(
    tmp_path: Path,
):
    path = tmp_path / "psq-repeated-set-distinct-position-values.vcf"
    _write(
        path,
        format_keys="GT:PSL:PSQ",
        sample="|0|1:shared,shared:12,37",
    )
    assert validate_vcf_strict(path)["records"] == 1


def test_vcf45_pso_tracking_is_sample_and_phase_set_scoped(
    tmp_path: Path,
):
    path = tmp_path / "pso-sample-phase-set-scope.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\tSAMPLE2\n"
        "1\t5\tdel1\tA\t<DEL>\t.\tPASS\tEND=8\tGT:PSL:PSO\t0|1:alpha,alpha:3,4\t0|1:beta,beta:.,4\n"
        "1\t9\tsnv1\tA\tC\t.\tPASS\t.\tGT:PSL:PSO\t0|1:alpha,alpha:5,6\t0|1:beta,beta:7,8\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_PHASE_SET_PSO_REQUIRED"


def test_vcf45_pso_does_not_leak_between_samples_or_distinct_phase_sets(
    tmp_path: Path,
):
    path = tmp_path / "pso-sample-phase-set-isolation.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\tSAMPLE2\n"
        "1\t5\tdel1\tA\t<DEL>\t.\tPASS\tEND=8\tGT:PSL:PSO\t0|1:alpha,alpha:3,4\t0|1:beta,beta:5,6\n"
        "1\t9\tsnv1\tA\tC\t.\tPASS\t.\tGT:PSL:PSO\t0|1:alpha,alpha:5,6\t0|1:beta,beta:7,8\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 2


def test_vcf45_reciprocal_breakend_phase_check_is_per_sample(
    tmp_path: Path,
):
    path = tmp_path / "breakend-phase-mismatch-second-sample.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\tSAMPLE2\n"
        "1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tSVTYPE=BND;MATEID=bnd2\tGT:PSL:PSO\t0|1:a,a:3,3\t0|1:b,b:4,4\n"
        "2\t10\tbnd2\tA\tA]1:5]\t.\tPASS\tSVTYPE=BND;MATEID=bnd1\tGT:PSL:PSO\t0|1:a,a:3,3\t0|1:b,b:4,5\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_BREAKEND_PHASE_SET_MISMATCH"

def test_vcf45_multi_alt_breakend_mates_check_each_reciprocal_phase_vector(
    tmp_path: Path,
):
    path = tmp_path / "multi-alt-breakend-phase-vectors.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tbnd1a;bnd1b\tA\tA]2:10],A]3:20]\t.\tPASS\tSVTYPE=BND;MATEID=bnd2a,bnd3a\tGT:PSL:PSO\t0|1:set,set:3,4\n"
        "2\t10\tbnd2a\tA\tA]1:5]\t.\tPASS\tSVTYPE=BND;MATEID=bnd1a\tGT:PSL:PSO\t0|1:set,set:3,4\n"
        "3\t20\tbnd3a\tA\tA]1:5]\t.\tPASS\tSVTYPE=BND;MATEID=bnd1b\tGT:PSL:PSO\t0|1:set,set:3,5\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_BREAKEND_PHASE_SET_MISMATCH"

def test_vcf45_single_breakend_with_pso_is_accepted_and_counted(
    tmp_path: Path,
):
    path = tmp_path / "single-breakend-pso-present.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tbnd_single\tA\t.A\t.\tPASS\t.\tGT:PSL:PSO\t0|1:set,set:3,4\n",
        encoding="utf-8",
    )
    result = validate_vcf_strict(path)
    assert result["records"] == 1
    assert result["breakend_records"] == 1

@pytest.mark.parametrize("single_breakend_alt", [".A", "A.", ".TGCA", "TCC."])
def test_vcf45_single_breakend_requires_pso_for_its_phase_set(
    tmp_path: Path, single_breakend_alt: str
):
    path = tmp_path / "single-breakend-pso-required.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        f"1\t5\tbnd_single\tA\t{single_breakend_alt}\t.\tPASS\t.\tGT:PSL:PSO\t0|1:set,set:3,.\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_PHASE_SET_PSO_REQUIRED"

def test_vcf45_pso_obligations_are_tracked_for_multiple_sets_in_one_sample(
    tmp_path: Path,
):
    path = tmp_path / "pso-multiple-sets-one-sample.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tdel1\tA\t<DEL>,<DUP>\t.\tPASS\tEND=8\tGT:PSL:PSO\t1|2|0:alpha,beta,gamma:3,4,5\n"
        "1\t9\tsnv1\tA\tC\t.\tPASS\t.\tGT:PSL:PSO\t1|0|0:alpha,beta,gamma:6,.,8\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_PHASE_SET_PSO_REQUIRED"


def test_vcf45_psq_distinct_phase_set_identifiers_remain_positionally_aligned(
    tmp_path: Path,
):
    path = tmp_path / "psq-distinct-phase-set-identifiers.vcf"
    _write(
        path,
        format_keys="GT:PSL:PSQ",
        sample="|0|1:phaseA,phaseB:11,29",
    )
    assert validate_vcf_strict(path)["records"] == 1


def test_vcf45_reciprocal_breakends_allow_remote_positions_within_cipos_intervals(
    tmp_path: Path,
):
    path = tmp_path / "breakend-microhomology-cipos.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t321681\tbndV\tT\tT]2:123462]\t6\tPASS\tSVTYPE=BND;MATEID=bndU;CIPOS=0,6\n"
        "2\t123456\tbndU\tC\tC]1:321687]\t6\tPASS\tSVTYPE=BND;MATEID=bndV;CIPOS=0,6\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 2


def test_vcf45_missing_breakend_cipos_is_reported_as_unresolved_evidence(
    tmp_path: Path,
):
    path = tmp_path / "breakend-missing-cipos.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t321681\tbndV\tT\tT]2:123462]\t6\tPASS\tSVTYPE=BND;MATEID=bndU;CIPOS=.,.\n"
        "2\t123456\tbndU\tC\tC]1:321687]\t6\tPASS\tSVTYPE=BND;MATEID=bndV;CIPOS=.,.\n",
        encoding="utf-8",
    )
    result = validate_vcf_strict(path)
    assert result["unresolved_breakend_coordinate_count"] == 2
    assert "VCF_BREAKEND_COORDINATE_UNCERTAINTY_UNRESOLVED" in result["warning_codes"]

@pytest.mark.parametrize("version", ["VCFv4.4", "VCFv4.5"])
def test_vcf44_and_vcf45_telomeric_breakend_remote_position_zero_is_valid(tmp_path: Path, version: str):
    path = tmp_path / f"breakend-telomere-zero-{version}.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t0\tbndX\tN\t.[13:123457[\t6\tPASS\tMATEID=bndV\n"
        "13\t123457\tbndV\tA\t]1:0]A\t6\tPASS\tMATEID=bndX\n",
        encoding="utf-8",
    )
    result = validate_vcf_strict(path)
    assert result["records"] == 2
    assert result["breakend_records"] == 2


def test_vcf45_precise_breakend_without_cipos_uses_implicit_zero_interval(
    tmp_path: Path,
):
    path = tmp_path / "breakend-precise-implicit-zero-cipos.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t321681\tbndV\tT\tT]2:123462]\t6\tPASS\tSVTYPE=BND;MATEID=bndU\n"
        "2\t123456\tbndU\tC\tC]1:321687]\t6\tPASS\tSVTYPE=BND;MATEID=bndV\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_BREAKEND_MATE_COORDINATE_MISMATCH"


def test_vcf45_cipos_interval_must_span_zero(
    tmp_path: Path,
):
    path = tmp_path / "breakend-invalid-cipos-range.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t321681\tbndV\tT\tT]2:123456]\t6\tPASS\tSVTYPE=BND;MATEID=bndU;CIPOS=1,5\n"
        "2\t123456\tbndU\tC\tC]1:321681]\t6\tPASS\tSVTYPE=BND;MATEID=bndV;CIPOS=0,0\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_BREAKEND_CIPOS_INVALID"

def test_vcf45_reciprocal_breakend_remote_position_outside_cipos_is_rejected(
    tmp_path: Path,
):
    path = tmp_path / "breakend-outside-cipos.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t321681\tbndV\tT\tT]2:123463]\t6\tPASS\tSVTYPE=BND;MATEID=bndU;CIPOS=0,6\n"
        "2\t123456\tbndU\tC\tC]1:321687]\t6\tPASS\tSVTYPE=BND;MATEID=bndV;CIPOS=0,6\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_BREAKEND_MATE_COORDINATE_MISMATCH"


def test_vcf45_reciprocal_breakend_phase_vectors_preserve_haplotype_order(
    tmp_path: Path,
):
    path = tmp_path / "breakend-phase-haplotype-order.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tSVTYPE=BND;MATEID=bnd2\tGT:PSL:PSO\t1|1|1:alpha,beta,gamma:1,2,3\n"
        "2\t10\tbnd2\tA\tA]1:5]\t.\tPASS\tSVTYPE=BND;MATEID=bnd1\tGT:PSL:PSO\t1|1|1:beta,alpha,gamma:2,1,3\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_BREAKEND_PHASE_SET_MISMATCH"

def test_vcf45_multiallelic_breakend_mate_ids_preserve_alt_order(
    tmp_path: Path,
):
    path = tmp_path / "breakend-mateid-alt-order.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tbndU\tA\tA]2:10],A]3:20]\t.\tPASS\tSVTYPE=BND;MATEID=bndZ,bndV\tGT:PSL:PSO\t1|2:alpha,beta:3,4\n"
        "2\t10\tbndV\tA\tA]1:5]\t.\tPASS\tSVTYPE=BND;MATEID=bndU\tGT:PSL:PSO\t0|1:.,alpha:.,3\n"
        "3\t20\tbndZ\tA\tA]1:5]\t.\tPASS\tSVTYPE=BND;MATEID=bndU\tGT:PSL:PSO\t0|1:.,beta:.,4\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_BREAKEND_MATE_COORDINATE_MISMATCH"


def test_vcf45_multiallelic_breakend_mates_compare_only_corresponding_alt_phase_values(
    tmp_path: Path,
):
    path = tmp_path / "breakend-per-alt-phase-vectors.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tbndU\tA\tA]2:10],A]3:20]\t.\tPASS\tSVTYPE=BND;MATEID=bndV,bndZ\tGT:PSL:PSO\t1|2:alpha,beta:3,4\n"
        "2\t10\tbndV\tA\tA]1:5]\t.\tPASS\tSVTYPE=BND;MATEID=bndU\tGT:PSL:PSO\t0|1:.,alpha:.,3\n"
        "3\t20\tbndZ\tA\tA]1:5]\t.\tPASS\tSVTYPE=BND;MATEID=bndU\tGT:PSL:PSO\t0|1:.,beta:.,4\n",
        encoding="utf-8",
    )
    result = validate_vcf_strict(path)
    assert result["records"] == 3
    assert len(result["breakend_adjacencies"]) == 2
    assert {
        item["source"]["alt_index"] for item in result["breakend_adjacencies"]
    } == {1, 2}
    assert all(
        item["source"]["orientation"]["remote_piece_direction"] == "LEFT"
        for item in result["breakend_adjacencies"]
    )


def test_vcf45_reciprocal_multicopy_bnd_phase_pairs_follow_psl_pso_identity(
    tmp_path: Path,
):
    path = tmp_path / "breakend-multicopy-phase-copy-order.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tMATEID=bnd2\tGT:PSL:PSO\t1|1:alpha,beta:3,4\n"
        "2\t10\tbnd2\tA\tA]1:5]\t.\tPASS\tMATEID=bnd1\tGT:PSL:PSO\t1|1:beta,alpha:4,3\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)
    assert result["records"] == 2
    assert {
        item["status"]
        for item in result["breakend_adjacencies"][0]["sample_phase_correspondence"].values()
    } == {"MATCHED"}
    for phase_set, ordinal in (("alpha", 3), ("beta", 4)):
        traversal = next(
            item for item in result["derivative_chromosome_traversals"]
            if item["sample"] == "SAMPLE1" and item["phase_set"] == phase_set
        )
        assert traversal["event_order_status"] == "RECONSTRUCTED"
        assert traversal["ordered_events"][0]["ordinal"] == ordinal


def test_vcf45_duplicate_bnd_phase_copy_identifiers_remain_unresolved(
    tmp_path: Path,
):
    path = tmp_path / "breakend-duplicate-phase-copy-identifiers.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tMATEID=bnd2\tGT:PSL:PSO\t1|1:alpha,alpha:3,3\n"
        "2\t10\tbnd2\tA\tA]1:5]\t.\tPASS\tMATEID=bnd1\tGT:PSL:PSO\t1|1:alpha,alpha:3,3\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)
    adjacency = result["breakend_adjacencies"][0]
    assert adjacency["sample_phase_correspondence"]["SAMPLE1"]["status"] == (
        "UNRESOLVED_DUPLICATE_PHASE_COPY_IDENTIFIERS"
    )
    traversal = next(
        item for item in result["derivative_chromosome_traversals"]
        if item["sample"] == "SAMPLE1" and item["phase_set"] == "alpha"
    )
    assert traversal["event_order_status"] == "UNRESOLVED"
    assert "VCF_PHASE_SET_PSO_ORDINAL_TIE_UNRESOLVED" in traversal["unresolved_reason_codes"]


def test_vcf45_reference_phase_positions_are_not_misclassified_as_bnd_alt_pairs(
    tmp_path: Path,
):
    path = tmp_path / "breakend-reference-and-alt-phase-positions.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tMATEID=bnd2\tGT:PSL:PSO\t0|1:refset,altset:9,3\n"
        "2\t10\tbnd2\tA\tA]1:5]\t.\tPASS\tMATEID=bnd1\tGT:PSL:PSO\t1|0:altset,refset:3,9\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)
    alt_traversal = next(
        item for item in result["derivative_chromosome_traversals"]
        if item["sample"] == "SAMPLE1" and item["phase_set"] == "altset"
    )
    ref_traversal = next(
        item for item in result["derivative_chromosome_traversals"]
        if item["sample"] == "SAMPLE1" and item["phase_set"] == "refset"
    )
    assert alt_traversal["ordered_events"][0]["event_kind"] == "RECIPROCAL_BREAKEND_EVENT"
    assert ref_traversal["ordered_events"][0]["event_kind"] == "ORDINAL_TIE_UNRESOLVED"
    assert ref_traversal["event_order_status"] == "UNRESOLVED"


def test_vcf45_pso_ordinal_tie_is_preserved_as_unresolved(
    tmp_path: Path,
):
    path = tmp_path / "pso-duplicate-ordinal-across-events.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\tsnv1\tA\tC\t.\tPASS\t.\tGT:PSL:PSO\t0|1:.,set:.,2\n"
        "1\t20\tsnv2\tG\tT\t.\tPASS\t.\tGT:PSL:PSO\t0|1:.,set:.,2\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)
    traversal = next(
        item for item in result["phase_set_traversal_orders"]
        if item["sample"] == "SAMPLE1" and item["phase_set"] == "set"
    )
    assert traversal["traversal_status"] == "UNRESOLVED_ORDINAL_TIES"
    assert traversal["unresolved_ordinal_tie_count"] == 1
    assert traversal["ordered_events"][0]["event_kind"] == "ORDINAL_TIE_UNRESOLVED"
    assert result["phase_set_traversal_unresolved_count"] == 1


def test_vcf45_pso_order_is_not_inferred_from_vcf_coordinate_order(
    tmp_path: Path,
):
    path = tmp_path / "pso-derivative-order-differs-from-coordinate-order.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\tsnv1\tA\tC\t.\tPASS\t.\tGT:PSL:PSO\t0|1:.,set:.,4\n"
        "1\t20\tsnv2\tG\tT\t.\tPASS\t.\tGT:PSL:PSO\t0|1:.,set:.,2\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)
    traversal = next(
        item for item in result["phase_set_traversal_orders"]
        if item["sample"] == "SAMPLE1" and item["phase_set"] == "set"
    )
    assert [event["ordinal"] for event in traversal["ordered_events"]] == [2, 4]
    assert [event["occurrences"][0]["pos"] for event in traversal["ordered_events"]] == [20, 10]




def test_vcf45_tandem_duplication_source_example_retains_reference_allele_pso(
    tmp_path: Path,
):
    path = tmp_path / "vcf45-tandem-duplication-pso-source-example.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##ALT=<ID=DUP,Description="Duplication">\n'
        '##INFO=<ID=SVCLAIM,Number=A,Type=String,Description="Structural variant claim">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "chr1\t10\tdup1\tT\t<DUP>\t.\tPASS\tEND=20;SVCLAIM=DJ\tGT:PSL:PSO\t/0/0|1:.,.,chr1*10*3:.,.,3\n"
        "chr1\t20\tsnv1\tA\tG\t.\tPASS\t.\tGT:PSL:PSO\t/0/0|0|1:.,.,chr1*10*1,chr1*10*3:.,.,4,1\n"
        "chr1\t30\tsnv2\tG\tT\t.\tPASS\t.\tGT:PSL:PSO\t/0/0|0|1:.,.,chr1*10*1,chr1*10*3:.,.,2,5\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)
    assert result["records"] == 3
    copy_one = next(
        item for item in result["phase_set_traversal_orders"]
        if item["sample"] == "SAMPLE1" and item["phase_set"] == "chr1*10*1"
    )
    copy_two = next(
        item for item in result["phase_set_traversal_orders"]
        if item["sample"] == "SAMPLE1" and item["phase_set"] == "chr1*10*3"
    )
    assert [event["ordinal"] for event in copy_one["ordered_events"]] == [2, 4]
    assert [event["ordinal"] for event in copy_two["ordered_events"]] == [1, 3, 5]
    assert any(
        occurrence["allele_index"] == 0
        for event in copy_one["ordered_events"]
        for occurrence in event["occurrences"]
    )
    traversal = next(
        item for item in result["derivative_chromosome_traversals"]
        if item["sample"] == "SAMPLE1" and item["phase_set"] == "chr1*10*1"
    )
    assert traversal["event_order_status"] == "RECONSTRUCTED"
    assert traversal["sequence_status"] == "UNRESOLVED_INSUFFICIENT_REFERENCE_SEGMENT_EVIDENCE"
    assert "VCF_DERIVATIVE_SEQUENCE_REQUIRES_REFERENCE_SEGMENT_AND_COPY_NUMBER_RECONSTRUCTION" in traversal["unresolved_reason_codes"]


def test_vcf45_psl_phase_set_is_global_across_chromosomes_for_pso_obligations(
    tmp_path: Path,
):
    path = tmp_path / "psl-global-across-chromosomes.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tdel1\tA\t<DEL>\t.\tPASS\tEND=8\tGT:PSL:PSO\t0|1:.,shared:.,3\n"
        "2\t10\tsnv1\tA\tC\t.\tPASS\t.\tGT:PSL:PSO\t0|1:.,shared:.,4\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)
    traversal = next(
        item for item in result["phase_set_traversal_orders"]
        if item["sample"] == "SAMPLE1" and item["phase_set"] == "shared"
    )
    assert [event["ordinal"] for event in traversal["ordered_events"]] == [3, 4]
    assert [event["occurrences"][0]["chrom"] for event in traversal["ordered_events"]] == ["1", "2"]


def test_vcf45_psl_phase_set_pso_obligation_crosses_chromosomes(
    tmp_path: Path,
):
    path = tmp_path / "psl-global-pso-required-across-chromosomes.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tdel1\tA\t<DEL>\t.\tPASS\tEND=8\tGT:PSL:PSO\t0|1:.,shared:.,3\n"
        "2\t10\tsnv1\tA\tC\t.\tPASS\t.\tGT:PSL:PSO\t0|1:.,shared:.,.\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_PHASE_SET_PSO_REQUIRED"


def test_vcf45_reciprocal_breakend_phase_values_match_across_different_gt_copy_positions(
    tmp_path: Path,
):
    path = tmp_path / "breakend-phase-different-gt-copy.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tSVTYPE=BND;MATEID=bnd2\tGT:PSL:PSO\t0|1:.,shared:.,3\n"
        "2\t10\tbnd2\tA\tA]1:5]\t.\tPASS\tSVTYPE=BND;MATEID=bnd1\tGT:PSL:PSO\t1|0:shared,.:3,.\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)
    traversal = next(
        item for item in result["phase_set_traversal_orders"]
        if item["sample"] == "SAMPLE1" and item["phase_set"] == "shared"
    )
    assert traversal["ordered_events"][0]["event_kind"] == "RECIPROCAL_BREAKEND_EVENT"
