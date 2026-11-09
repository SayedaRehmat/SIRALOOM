from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "giab-public-qualification.yml"


def test_public_giab_workflow_uses_acquisition_provenance_schema():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    # The acquisition report stores the downloaded truth VCF under assets and
    # the derived, indexed BGZF reference under reference_pair.fasta.
    assert '["assets"]["truth_vcf"]["path"]' in workflow
    assert '["reference_pair"]["fasta"]["path"]' in workflow
    assert '["assets"]["reference_fasta"]["path"]' not in workflow
    assert 'SIRALOOM_BENCHMARK_INCLUDE_VALIDATION_ERRORS: "1"' in workflow


def test_public_giab_workflow_publishes_compact_review_bundle():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "- name: Preserve compact qualification review bundle" in workflow
    assert "acquisition-failure.json" in workflow
    assert "evidence/scale/vcf-scale-benchmark.json" in workflow
    assert "evidence/scale/vcf-scale-benchmark.failure.json" in workflow
    assert "evidence/run-provenance.json" in workflow
