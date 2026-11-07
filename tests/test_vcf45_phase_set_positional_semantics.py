from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


def _write(path: Path, *, format_keys: str, sample: str) -> None:
    path.write_text(
        "##fileformat=VCFv4.5\n"
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
