#!/usr/bin/env python3
"""Execute a pinned BCFtools normalization smoke test against the acquired reference.

This is a reference-backed tool execution gate, not a substitute for normalizing
or validating clinical callsets. It deliberately exercises SNV, deletion and
insertion records against the exact FASTA that is subsequently registered.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Sequence


class QualificationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: Sequence[str], *, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(command), check=False, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode:
        raise QualificationError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout: {result.stdout[-4000:]}\nstderr: {result.stderr[-4000:]}"
        )
    return result


def fasta_sequence(samtools: str, fasta: Path, contig: str) -> str:
    result = run([samtools, "faidx", str(fasta), f"{contig}:101-401"])
    lines = result.stdout.splitlines()
    if not lines or not lines[0].startswith(">"):
        raise QualificationError("samtools faidx returned no FASTA sequence")
    sequence = "".join(lines[1:]).upper()
    if len(sequence) != 301 or set(sequence) - set("ACGTN"):
        raise QualificationError("reference slice is incomplete or contains unsupported bases")
    if "N" in sequence:
        raise QualificationError("selected reference slice contains ambiguous N bases")
    return sequence


def build_fixture(contig: str, sequence: str, destination: Path) -> dict:
    # Coordinates are separated to avoid overlap. The REF alleles are copied
    # directly from the selected FASTA slice; only ALT is synthesized.
    snv_pos, deletion_pos, insertion_pos = 120, 220, 320

    def base_at(position: int) -> str:
        return sequence[position - 101]

    snv_ref = base_at(snv_pos)
    snv_alt = next(base for base in "ACGT" if base != snv_ref)
    deletion_ref = sequence[deletion_pos - 101 : deletion_pos - 99]
    insertion_ref = base_at(insertion_pos)
    insertion_alt = insertion_ref + next(base for base in "ACGT" if base != insertion_ref)

    records = [
        (snv_pos, snv_ref, snv_alt, "SNV"),
        (deletion_pos, deletion_ref, deletion_ref[0], "DELETION"),
        (insertion_pos, insertion_ref, insertion_alt, "INSERTION"),
    ]
    destination.write_text(
        "##fileformat=VCFv4.3\n"
        f"##contig=<ID={contig}>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        + "".join(
            f"{contig}\t{position}\t.\t{ref}\t{alt}\t.\tPASS\t.\n"
            for position, ref, alt, _kind in records
        ),
        encoding="ascii",
    )
    return {
        "expected_record_count": len(records),
        "record_types": [kind for _pos, _ref, _alt, kind in records],
        "source_records": [
            {"contig": contig, "position": pos, "ref": ref, "alt": alt, "type": kind}
            for pos, ref, alt, kind in records
        ],
    }


def qualify(manifest_path: Path, report_path: Path, *, bcftools: str, samtools: str) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fasta = Path(manifest["fasta_path"])
    fai = Path(manifest["fai_path"])
    if not fasta.is_file() or not fai.is_file():
        raise QualificationError("manifest FASTA/FAI paths are not available")

    candidates = [item for item in manifest["contigs"] if int(item["length"]) >= 500]
    if not candidates:
        raise QualificationError("reference package has no contig long enough for normalization fixture")
    contig = str(candidates[0]["name"])
    sequence = fasta_sequence(samtools, fasta, contig)

    work_dir = report_path.parent
    work_dir.mkdir(parents=True, exist_ok=True)
    source_vcf = work_dir / "reference-backed-normalization.input.vcf"
    normalized_vcf = work_dir / "reference-backed-normalization.normalized.vcf.gz"
    fixture = build_fixture(contig, sequence, source_vcf)

    version = run([bcftools, "--version"]).stdout.splitlines()[0]
    norm_command = [
        bcftools, "norm", "--fasta-ref", str(fasta), "--check-ref", "e",
        "--multiallelics", "-any", "--output-type", "z",
        "--output", str(normalized_vcf), str(source_vcf),
    ]
    norm_result = run(norm_command, timeout=1800)
    index_command = [bcftools, "index", "--csi", "--force", str(normalized_vcf)]
    index_result = run(index_command)
    query_command = [bcftools, "query", "--format", "%CHROM\\t%POS\\t%REF\\t%ALT\\n", str(normalized_vcf)]
    query_result = run(query_command)
    rows = [line.split("\t") for line in query_result.stdout.splitlines() if line]
    if len(rows) != fixture["expected_record_count"]:
        raise QualificationError(
            f"normalized record count mismatch: expected {fixture['expected_record_count']}, observed {len(rows)}"
        )
    if any(len(row) != 4 for row in rows):
        raise QualificationError("normalized VCF query returned malformed records")
    observed_types = {
        "SNV": any(len(row[2]) == 1 and len(row[3]) == 1 for row in rows),
        "INDEL": any(len(row[2]) != len(row[3]) for row in rows),
    }
    if not all(observed_types.values()):
        raise QualificationError(f"normalized output lacks expected variant classes: {observed_types}")

    index_count = run([bcftools, "index", "--nrecords", str(normalized_vcf)])
    try:
        indexed_records = int(index_count.stdout.strip())
    except ValueError as exc:
        raise QualificationError(f"BCFtools returned an invalid CSI record count: {index_count.stdout!r}") from exc
    if indexed_records != len(rows):
        raise QualificationError(
            f"CSI record count mismatch: queried {len(rows)}, indexed {indexed_records}"
        )
    csi_path = Path(str(normalized_vcf) + ".csi")
    if not csi_path.is_file():
        raise QualificationError("BCFtools reported success but did not create a CSI index")

    report = {
        "schema_version": 1,
        "status": "PASS",
        "scope": "REFERENCE_BACKED_SYNTHETIC_SNV_INDEL_NORMALIZATION_ONLY",
        "reference": {
            "assembly_accession": manifest["assembly_accession"],
            "package_version": manifest["package_version"],
            "package_checksum": manifest["package_checksum"],
            "fasta_sha256": sha256_file(fasta),
            "fai_sha256": sha256_file(fai),
            "contig": contig,
        },
        "tool": {"name": "bcftools", "version": version, "samtools_version": run([samtools, "--version"]).stdout.splitlines()[0]},
        "execution": {
            "command": norm_command,
            "exit_code": norm_result.returncode,
            "stdout": norm_result.stdout,
            "stderr": norm_result.stderr,
            "index_command": index_command,
            "index_exit_code": index_result.returncode,
            "query_command": query_command,
            "query_exit_code": query_result.returncode,
        },
        "fixture": fixture,
        "result": {
            "input_sha256": sha256_file(source_vcf),
            "normalized_vcf_sha256": sha256_file(normalized_vcf),
            "csi_sha256": sha256_file(csi_path),
            "normalized_records": len(rows),
            "indexed_records": indexed_records,
            "observed_variant_classes": observed_types,
            "normalized_rows": rows,
        },
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest["reference_normalization_execution"] = {
        "status": "PASS",
        "report_file": report_path.name,
        "report_sha256": sha256_file(report_path),
        "tool": report["tool"],
        "scope": report["scope"],
        "normalized_records": len(rows),
        "csi_indexed_records": indexed_records,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--bcftools", default="bcftools")
    parser.add_argument("--samtools", default="samtools")
    args = parser.parse_args()
    report = qualify(args.manifest, args.report, bcftools=args.bcftools, samtools=args.samtools)
    print(json.dumps({
        "status": report["status"],
        "scope": report["scope"],
        "bcftools": report["tool"]["version"],
        "contig": report["reference"]["contig"],
        "normalized_records": report["result"]["normalized_records"],
        "csi_indexed_records": report["result"]["indexed_records"],
        "report": str(args.report),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
