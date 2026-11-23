import gzip
from io import BytesIO

import pytest

from scripts.validation import run_real_caller_vcf_smoke as smoke


def test_download_rejects_truncated_gzip_without_leaving_artifact(tmp_path, monkeypatch):
    complete = gzip.compress(b">chr20\nACGT\n")
    truncated = complete[:-4]

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, size):
            nonlocal truncated
            chunk, truncated = truncated[:size], truncated[size:]
            return chunk

    monkeypatch.setattr(smoke.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    destination = tmp_path / "reference.fa.gz"

    with pytest.raises(RuntimeError, match="integrity checks"):
        smoke.download("https://example.invalid/reference.fa.gz", destination)

    assert not destination.exists()
    assert not destination.with_name(destination.name + ".part").exists()


def test_reference_builder_checks_refseq_accession_and_length(tmp_path, monkeypatch):
    payload = b">NC_000020.11 Homo sapiens chromosome 20, GRCh38\nACGTN\n"

    class Response(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    monkeypatch.setattr(smoke, "REFERENCE_LENGTH", 5)
    monkeypatch.setattr(smoke.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(payload))

    reference, length = smoke.build_chr20_reference(tmp_path)

    assert length == 5
    assert reference.read_text() == ">chr20\nACGTN\n"
    assert (tmp_path / "NC_000020.11.fa").read_bytes() == payload


def test_resume_reuses_result_only_when_input_reference_tool_and_artifacts_match(tmp_path):
    output = tmp_path / "normalized.vcf.gz"
    output.write_bytes(b"normalized")
    (tmp_path / "normalized.vcf.gz.csi").write_bytes(b"index")
    callset = {"caller": "GATK_HAPLOTYPECALLER", "sha256": "input-digest"}
    tool = ["bcftools 1.25", "Using htslib 1.25"]
    result = {
        "caller": "GATK_HAPLOTYPECALLER",
        "source_sha256": "input-digest",
        "whole_file_parser_validation": {"status": "PASS"},
        "chr20_projection": {"strict_validation": "PASS"},
        "reference_validation": {"result": "PASS"},
        "reference_sha256": "reference-digest",
        "bcftools": tool,
        "normalization": {
            "status": "PASS",
            "index_exists": True,
            "output": str(output),
            "output_sha256": smoke.digest(output),
        },
    }

    assert smoke.reusable_caller_result(result, callset, "reference-digest", tool)
    assert not smoke.reusable_caller_result(result, callset, "different-reference", tool)
    assert not smoke.reusable_caller_result(result, {**callset, "sha256": "changed-input"}, "reference-digest", tool)

    output.write_bytes(b"tampered")
    assert not smoke.reusable_caller_result(result, callset, "reference-digest", tool)


def test_whole_vcf_stats_summary_is_required_and_parsed(tmp_path, monkeypatch):
    source = tmp_path / "input.vcf.gz"
    source.touch()
    monkeypatch.setattr(
        smoke,
        "run",
        lambda command: "SN\t0\tnumber of samples:\t1\nSN\t0\tnumber of records:\t42\nSN\t0\tnumber of SNPs:\t40\n",
    )

    summary = smoke.validate_whole_vcf_with_bcftools(source)

    assert summary["method"] == "BCFTOOLS_STATS_HTSLIB_FULL_FILE_PARSE"
    assert summary["records"] == 42
    assert summary["sample_count"] == 1
    assert summary["summary"]["number of SNPs"] == 40

    monkeypatch.setattr(smoke, "run", lambda _command: "SN\t0\tnumber of samples:\t1\n")
    with pytest.raises(RuntimeError, match="did not return"):
        smoke.validate_whole_vcf_with_bcftools(source)
