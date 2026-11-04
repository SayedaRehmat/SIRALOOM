import hashlib
import json
import os
import shutil
from pathlib import Path

from backend.app.domain.ingestion import validate_vcf
from backend.app.domain.vcf_tools import (
    normalize_vcf_with_bcftools,
    route_vcf_records,
    validate_vcf_index_concordance,
)
from backend.app.domain.vcf_validation import validate_vcf_strict

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

executable = shutil.which("bcftools")
if not executable:
    raise SystemExit("Production container has no BCFtools executable")
executable_sha256 = sha256(Path(executable))
output_dir = Path("/qualification/output")
output_dir.mkdir(parents=True, exist_ok=True)
cases = [
    (
        "GRCh38",
        Path("/qualification/grch38/giab-hg002-grch38-chr1.vcf.gz"),
        Path("/qualification/grch38") / os.environ["GRCH38_REFERENCE_FILENAME"],
        "chr1",
    ),
    (
        "GRCh37",
        Path("/qualification/grch37/giab-hg002-grch37-chr1.vcf.gz"),
        Path("/qualification/grch37") / os.environ["GRCH37_REFERENCE_FILENAME"],
        "1",
    ),
]
reports = []
for build, source, reference, contig in cases:
    if not source.is_file() or not reference.is_file() or not Path(f"{reference}.fai").is_file():
        raise SystemExit(f"{build} input or reference/FAI is missing inside the container")
    intake = validate_vcf(source)
    if intake.status != "VALID":
        raise SystemExit(f"{build} production-container VCF intake failed: {intake.errors}")
    source_index = validate_vcf_index_concordance(
        source,
        expected_bcftools_version="1.25",
    )
    routing = route_vcf_records(
        source,
        output_dir / f"{build.lower()}-routing",
    )
    if routing["record_reconciliation"]["balanced"] is not True:
        raise SystemExit(f"{build} source-record routing reconciliation failed")
    sequence_input = Path(routing["sequence_path"])
    output = output_dir / f"normalized-{build.lower()}.vcf.gz"
    result = normalize_vcf_with_bcftools(
        sequence_input,
        output,
        reference_fasta=reference,
        expected_bcftools_version="1.25",
        expected_bcftools_sha256=executable_sha256,
    )
    normalized = validate_vcf_strict(output, reference_contigs={contig})
    index = validate_vcf_index_concordance(
        output,
        expected_bcftools_version="1.25",
    )
    if result["source_child_reconciliation"]["balanced"] is not True:
        raise SystemExit(f"{build} source-to-child reconciliation failed")
    if index["status"] != "VALIDATED":
        raise SystemExit(f"{build} normalized CSI validation failed")
    reports.append({
        "genome_build": build,
        "input_vcf_sha256": sha256(source),
        "reference_fasta_sha256": sha256(reference),
        "reference_fai_sha256": sha256(Path(f"{reference}.fai")),
        "input_validation": {
            "status": intake.status,
            "record_count": intake.record_count,
            "fileformat": intake.fileformat,
            "bcftools_version": intake.metadata["bcftools_version"],
            "htslib_version": intake.metadata["htslib_version"],
        },
        "input_index_validation": source_index,
        "record_routing": {
            "record_reconciliation": routing["record_reconciliation"],
            "sequence_records": routing["sequence_records"],
            "structural_variant_records": routing["structural_variant_records"],
            "cnv_variant_records": routing["cnv_variant_records"],
            "repeat_expansion_records": routing["repeat_expansion_records"],
        },
        "normalization": {
            "tool_version": result["tool_version"],
            "executable_sha256": result["executable_sha256"],
            "normalized_record_count": normalized["records"],
            "normalized_vcf_sha256": sha256(output),
            "normalized_csi_sha256": sha256(Path(f"{output}.csi")),
            "source_child_reconciliation": result["source_child_reconciliation"],
            "index_validation": index,
        },
    })
report = {
    "qualification_status": "PASSED",
    "execution_environment": "siraloom-backend:ci",
    "container_user": os.getuid(),
    "bcftools_executable": executable,
    "bcftools_executable_sha256": executable_sha256,
    "bcftools_version": "1.25",
    "htslib_version": "1.25",
    "assemblies": reports,
}
(output_dir / "container-qualification-report.json").write_text(
    json.dumps(report, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(json.dumps(report, indent=2, sort_keys=True))
