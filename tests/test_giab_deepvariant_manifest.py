from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]


def test_hg001_illumina_30x_manifest_pins_public_bam_and_index() -> None:
    manifest = json.loads(
        (ROOT / "benchmarks/giab/hg001_illumina30x_grch37.v1.json").read_text(encoding="utf-8")
    )

    assert manifest["schema_version"] == "1"
    assert manifest["sample"] == "HG001"
    assert manifest["sample_alias"] == "NA12878"
    assert manifest["technology"] == "Illumina HiSeq paired-end WGS"
    assert manifest["nominal_coverage"] == "30x"
    assert manifest["alignment_reference"] == "GRCh37 hs37d5"

    bam = manifest["assets"]["bam"]
    bai = manifest["assets"]["bai"]
    assert urlparse(bam["url"]).hostname == "ftp.ncbi.nlm.nih.gov"
    assert urlparse(bai["url"]).hostname == "ftp.ncbi.nlm.nih.gov"
    assert bam["url"].endswith("/RMNISTHS_30xdownsample.bam")
    assert bai["url"] == bam["url"] + ".bai"
    assert bam["official_md5"] == "0be437ac376966c73605f791eb50515e"
    assert bai["official_md5"] == "867383e9343eaef3983e335e923fd4fd"
    assert len(bam["official_md5"]) == 32
    assert len(bai["official_md5"]) == 32


def test_hg001_caller_manifest_pins_deepvariant_and_matching_truth_build() -> None:
    manifest = json.loads(
        (ROOT / "benchmarks/giab/hg001_illumina30x_grch37.v1.json").read_text(encoding="utf-8")
    )

    assert manifest["caller"] == {
        "name": "Google DeepVariant",
        "version": "1.10.0",
        "docker_image": "google/deepvariant:1.10.0",
        "model_type": "WGS",
    }
    assert manifest["truth_set"]["manifest"] == "benchmarks/giab/public_assets.v1.json"
    assert manifest["truth_set"]["reference_build"] == "GRCh37"
    assert manifest["truth_set"]["release"] == "NISTv4.2.1"


def test_caller_workflow_requires_declared_bam_sample_and_exact_reference_identity() -> None:
    workflow = (
        ROOT / ".github/workflows/giab-hg001-deepvariant.yml"
    ).read_text(encoding="utf-8")

    assert 'expected_samples = {manifest["sample"], manifest["sample_alias"]}' in workflow
    assert "BAM read-group sample must be one declared HG001 alias" in workflow
    assert "Verify BAM reference sequence MD5 values against the exact caller FASTA" in workflow
    assert 'fields.get("M5")' in workflow
    assert "BAM/reference sequence identity mismatch" in workflow
