#!/usr/bin/env python3
"""Record-level reference provenance diagnostics for public HG002 caller VCFs.

This module is diagnostic only. It does not alter, bypass, or replace SIRALOOM's
VCF validator, reference binding, routing, or normalization implementation.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

TARGET_CONTIGS = {"hs38d1", "chrEBV"}
EXPECTED_SOURCE_FILES = {
    "GATK_HAPLOTYPECALLER": "HG002_GATK_BWA_SNV.vcf.gz",
    "DEEPVARIANT": "HG002_DV_BWA_SNV.vcf.gz",
    "DRAGEN": "HG002_35x.hard-filtered.vcf.gz",
}
ZENODO_RECORDS = {
    "GATK_HAPLOTYPECALLER": "https://zenodo.org/records/10428664",
    "DEEPVARIANT": "https://zenodo.org/records/10428664",
    "DRAGEN": "https://zenodo.org/records/8350256",
}
REFERENCE_PROVENANCE = {
    "GATK_HAPLOTYPECALLER": {
        "source": "Published BWA-MEM workflow; read-group platform-unit contains HG002_38_nodecoy",
        "source_publication_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC12022141/",
        "reference_label": "GRCh38 / nodecoy (publication metadata)",
        "reference_fasta_path_reported": None,
        "package_manifest_url": None,
        "sequence_dictionary_url": None,
        "publisher_sequence_checksum": None,
        "status": "PARTIAL_METADATA_ONLY",
        "limitation": "The publication does not publish the exact FASTA bytes, checksum, or sequence dictionary for this selected callset.",
    },
    "DEEPVARIANT": {
        "source": "Published BWA-MEM workflow; command reports --ref=/mnt/reference/hg38.fa",
        "source_publication_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC12022141/",
        "reference_label": "hg38.fa (publication command)",
        "reference_fasta_path_reported": "/mnt/reference/hg38.fa",
        "package_manifest_url": None,
        "sequence_dictionary_url": None,
        "publisher_sequence_checksum": None,
        "status": "PARTIAL_METADATA_ONLY",
        "limitation": "The command identifies a filename/path but does not publish its source URL, bytes, checksum, or sequence dictionary.",
    },
    "DRAGEN": {
        "source": "DRAGEN 4.2 reference directory reported by the study; study describes multigenome mapping with GRCh38 plus 64 haplotypes and a specialized HLA caller",
        "source_publication_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC12022141/",
        "reference_label": "hg38-alt_masked.graph.cnv.hla.rna_v3",
        "reference_fasta_path_reported": None,
        "package_manifest_url": "https://support.illumina.com/downloads/dragen-reference-genomes-hg38.html",
        "sequence_dictionary_url": "https://support.illumina.com/sequencing/sequencing_software/dragen-bio-it-platform/product_files.html",
        "publisher_package": {
            "name": "Illumina DRAGEN Multigenome Graph Reference hg38 (alt-masked_graph+cnv+hla+rna_v3)",
            "dragen_version": "4.2",
            "posted": "2023-07-11",
            "published_size": "8.6 GB",
            "resource_type": "prebuilt multigenome graph reference/hash-table bundle",
        },
        "publisher_sequence_checksum": None,
        "status": "PACKAGE_IDENTIFIED_SEQUENCE_MANIFEST_UNAVAILABLE",
        "limitation": "The public page identifies the DRAGEN bundle, but the accessible page does not expose its complete sequence dictionary or per-contig FASTA checksums. The hash-table bundle is not itself a FASTA sequence dictionary.",
    },
}

def run(command: list[str]) -> str:
    p = subprocess.run(command, check=False, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(command)}\n{p.stderr[-4000:]}")
    return p.stdout

def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)

def parse_attrs(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', value):
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        result[key.strip()] = val.strip().strip('"')
    return result

def load_fai(fasta: Path) -> dict[str, dict[str, int]]:
    fai = Path(str(fasta) + ".fai")
    if not fai.exists():
        run(["samtools", "faidx", str(fasta)])
    entries = {}
    for line in fai.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) < 5:
            raise RuntimeError(f"Malformed FAI row: {line!r}")
        entries[fields[0]] = {
            "length": int(fields[1]), "offset": int(fields[2]),
            "line_bases": int(fields[3]), "line_width": int(fields[4]),
        }
    return entries

def fasta_digests(fasta: Path, entry: dict[str, int]) -> dict[str, str]:
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    remaining = entry["length"]
    with fasta.open("rb") as handle:
        handle.seek(entry["offset"])
        while remaining:
            size = min(entry["line_bases"], remaining)
            sequence = handle.read(size).upper()
            if len(sequence) != size:
                raise RuntimeError("Unexpected EOF while hashing reference contig")
            md5.update(sequence)
            sha256.update(sequence)
            remaining -= size
            if remaining:
                handle.seek(entry["line_width"] - size, 1)
    return {"md5": md5.hexdigest(), "sha256": sha256.hexdigest()}

def contig_header(header: str) -> dict[str, dict[str, Any]]:
    result = {}
    for line in header.splitlines():
        if not line.startswith("##contig=<") or not line.endswith(">"):
            continue
        attrs = parse_attrs(line[len("##contig=<"):-1])
        name = attrs.get("ID")
        if name:
            length = attrs.get("length") or attrs.get("Length")
            result[name] = {
                "declaration": line,
                "length": int(length) if length and length.isdigit() else None,
                "md5": attrs.get("md5") or attrs.get("MD5"),
            }
    return result

def classify_variant(ref: str, alt: str) -> str:
    alts = alt.split(",")
    sequence = re.compile(r"^[ACGTNacgtn]+$")
    if not sequence.fullmatch(ref) or not all(sequence.fullmatch(a) for a in alts):
        return "symbolic_breakend_or_non_sequence"
    if all(len(a) == len(ref) == 1 for a in alts):
        return "snv"
    if all(len(a) != len(ref) for a in alts):
        return "indel"
    if all(len(a) == len(ref) for a in alts):
        return "mnp_or_complex_substitution"
    return "mixed_multiallelic"

def scan_variant_counts(vcf: Path) -> dict[str, dict[str, int]]:
    process = subprocess.Popen(
        ["bcftools", "query", "-f", "%CHROM\\t%REF\\t%ALT\\n", str(vcf)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert process.stdout is not None
    counts: dict[str, dict[str, int]] = {}
    for line in process.stdout:
        fields = line.rstrip("\n").split("\t")
        if len(fields) != 3:
            continue
        chrom, ref, alt = fields
        bucket = counts.setdefault(chrom, {})
        kind = classify_variant(ref, alt)
        bucket[kind] = bucket.get(kind, 0) + 1
        bucket["total"] = bucket.get("total", 0) + 1
    stderr = process.stderr.read() if process.stderr else ""
    code = process.wait()
    if code:
        raise RuntimeError(f"bcftools query failed for {vcf}: {stderr[-3000:]}")
    return counts

def representative_records(vcf: Path, contig: str, limit: int = 5) -> list[str]:
    process = subprocess.Popen(
        ["bcftools", "view", "-H", "-i", f'CHROM="{contig}"', str(vcf)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert process.stdout is not None
    rows = []
    for line in process.stdout:
        rows.append(line.rstrip("\n"))
        if len(rows) >= limit:
            process.terminate()
            break
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    return rows

def inspect_callsets(
    callsets: list[dict[str, Any]], fasta: Path, output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    reference_entries = load_fai(fasta)
    reference_cache: dict[str, dict[str, str]] = {}
    result: dict[str, Any] = {
        "schema_version": 1,
        "purpose": "source VCF and reference provenance diagnostics; no validator relaxation",
        "canonical_comparator": {
            "label": "pinned UCSC GRCh38 FASTA used by PR #333",
            "fasta_filename": fasta.name,
            "contig_count": len(reference_entries),
            "sequence_hash_algorithm": "SHA-256 over uppercase sequence bases without FASTA line breaks",
            "note": "This is a comparator. It is not asserted to be the original FASTA used by any caller.",
        },
        "callers": {},
        "overall_reference_conclusion": "UNRESOLVED_UNTIL_ORIGINAL_REFERENCE_SEQUENCE_MANIFESTS_ARE_AVAILABLE",
    }
    for callset in callsets:
        caller = callset["caller"]
        if callset.get("filename") != EXPECTED_SOURCE_FILES.get(caller):
            raise RuntimeError(
                f"Unexpected source file for {caller}: {callset.get('filename')!r}; "
                f"expected {EXPECTED_SOURCE_FILES.get(caller)!r}"
            )
        vcf = Path(callset["local_path"])
        header = run(["bcftools", "view", "-h", str(vcf)])
        header_path = output_dir / f"{caller.lower()}.header.vcf.txt"
        header_path.write_text(header, encoding="utf-8")
        declarations = contig_header(header)
        run(["bcftools", "index", "-f", str(vcf)])
        index_rows = run(["bcftools", "index", "-s", str(vcf)]).splitlines()
        index_counts = {}
        for row in index_rows:
            fields = row.split("\t")
            if len(fields) >= 3:
                index_counts[fields[0]] = {
                    "reference_length_in_index": int(fields[1]),
                    "record_count": int(fields[2]),
                }
        type_counts = scan_variant_counts(vcf)
        all_contigs = sorted(set(declarations) | set(index_counts) | set(type_counts))
        contig_reports = {}
        for contig in all_contigs:
            declared = declarations.get(contig, {})
            canonical = reference_entries.get(contig)
            canonical_hashes = None
            if canonical:
                if contig not in reference_cache:
                    reference_cache[contig] = fasta_digests(fasta, canonical)
                canonical_hashes = reference_cache[contig]
            declared_length = declared.get("length")
            canonical_length = canonical["length"] if canonical else None
            declared_md5 = declared.get("md5")
            length_match = (
                declared_length == canonical_length
                if declared_length is not None and canonical_length is not None else None
            )
            md5_match = (
                declared_md5.lower() == canonical_hashes["md5"].lower()
                if declared_md5 and canonical_hashes else None
            )
            contig_reports[contig] = {
                "header_declaration": declared.get("declaration"),
                "vcf_header_length": declared_length,
                "vcf_header_md5": declared_md5,
                "record_count": index_counts.get(contig, {}).get("record_count", type_counts.get(contig, {}).get("total", 0)),
                "variant_class_counts": type_counts.get(contig, {}),
                "present_in_canonical_fasta": canonical is not None,
                "canonical_fasta_length": canonical_length,
                "canonical_sequence_md5": canonical_hashes["md5"] if canonical_hashes else None,
                "canonical_sequence_sha256": canonical_hashes["sha256"] if canonical_hashes else None,
                "declared_length_matches_canonical": length_match,
                "declared_md5_matches_canonical": md5_match,
                "source_sequence_sha256": None,
                "source_sequence_identity_status": (
                    "UNRESOLVED_SOURCE_SEQUENCE_NOT_PUBLISHED"
                    if canonical and not declared_md5 else
                    "MATCHED_MD5_AND_LENGTH_TO_CANONICAL_COMPARATOR"
                    if canonical and md5_match is True and length_match is True else
                    "MISMATCH_TO_CANONICAL_COMPARATOR"
                    if canonical and (md5_match is False or length_match is False) else
                    "NOT_COMPARABLE_CONTIG_ABSENT_FROM_CANONICAL_COMPARATOR"
                ),
            }
        targeted = sorted(
            c for c in all_contigs
            if c in TARGET_CONTIGS or c.startswith("HLA-")
        )
        raw_records = {}
        for contig in targeted:
            raw_records[contig] = representative_records(vcf, contig)
        raw_path = output_dir / f"{caller.lower()}.target-contig-representative-records.json"
        atomic_json(raw_path, raw_records)
        header_contig_path = output_dir / f"{caller.lower()}.contig-declarations.json"
        atomic_json(header_contig_path, declarations)
        contig_counts_path = output_dir / f"{caller.lower()}.per-contig-counts.json"
        atomic_json(contig_counts_path, contig_reports)
        canonical_contigs = [c for c in all_contigs if c in reference_entries]
        auxiliary_contigs = [c for c in all_contigs if c not in reference_entries]
        eligible_primary = sum(
            type_counts.get(c, {}).get("snv", 0) + type_counts.get(c, {}).get("indel", 0)
            for c in canonical_contigs
        )
        auxiliary_records = sum(type_counts.get(c, {}).get("total", 0) for c in auxiliary_contigs)
        # REF validation is run only over records on canonical comparator contigs;
        # all original records and auxiliary-contig evidence remain preserved.
        ref_status = "NOT_RUN"
        ref_error = None
        try:
            bed = output_dir / f"{caller.lower()}.canonical-contigs.bed"
            bed.write_text(
                "".join(f"{c}\t0\t{reference_entries[c]['length']}\n" for c in canonical_contigs),
                encoding="utf-8",
            )
            if canonical_contigs:
                run(["bcftools", "view", "-R", str(bed), "-Oz", "-o", str(output_dir / f"{caller.lower()}.canonical-projection.vcf.gz"), str(vcf)])
                projection = output_dir / f"{caller.lower()}.canonical-projection.vcf.gz"
                run(["bcftools", "index", "-f", str(projection)])
                run(["bcftools", "norm", "-f", str(fasta), "-c", "e", "-N", "-Ou", "-o", "/dev/null", str(projection)])
                ref_status = "PASS_ON_CANONICAL_CONTIG_PROJECTION"
            else:
                ref_status = "NOT_EVALUABLE_NO_SHARED_CANONICAL_CONTIGS"
        except Exception as exc:
            ref_status = "FAIL_ON_CANONICAL_CONTIG_PROJECTION"
            ref_error = f"{type(exc).__name__}: {exc}"
        header_md5_available = all(
            declarations.get(c, {}).get("md5") for c in canonical_contigs
        ) if canonical_contigs else False
        header_length_available = all(
            declarations.get(c, {}).get("length") is not None for c in canonical_contigs
        ) if canonical_contigs else False
        length_mismatches = [
            c for c in canonical_contigs
            if contig_reports[c]["declared_length_matches_canonical"] is False
        ]
        md5_mismatches = [
            c for c in canonical_contigs
            if contig_reports[c]["declared_md5_matches_canonical"] is False
        ]
        if length_mismatches or md5_mismatches:
            reference_identity = "INCOMPATIBLE_WITH_CANONICAL_COMPARATOR"
        elif header_md5_available and header_length_available and canonical_contigs:
            reference_identity = "SHARED_CONTIGS_MATCH_CANONICAL_COMPARATOR"
        else:
            reference_identity = "UNRESOLVED_SOURCE_REFERENCE_IDENTITY"
        contig_compatibility = (
            "ALL_VCF_CONTIGS_PRESENT_IN_CANONICAL_COMPARATOR"
            if not auxiliary_contigs else "PARTIAL_EXTRA_CONTIGS_REQUIRE_SEPARATE_RECONCILIATION"
        )
        variant_scope = (
            "PRIMARY_CONTIG_SNVS_INDELS_IDENTIFIED_AUXILIARY_RECORDS_PRESERVED"
            if eligible_primary and auxiliary_records else
            "PRIMARY_CONTIG_SNVS_INDELS_IDENTIFIED"
            if eligible_primary else "NO_PRIMARY_CONTIG_SNVS_INDELS_IDENTIFIED"
        )
        result["callers"][caller] = {
            "source": {
                "record_url": ZENODO_RECORDS[caller],
                "filename": callset["filename"],
                "download_url": callset["download_url"],
                "bytes": callset["bytes"],
                "zenodo_checksum": callset["zenodo_checksum"],
                "verified_source_checksum": callset["verified_source_checksum"],
                "source_md5": callset["source_md5"],
                "source_sha256": callset["sha256"],
                "vcf_version": next((x.split("=", 1)[1] for x in header.splitlines() if x.startswith("##fileformat=")), None),
                "sample_names": run(["bcftools", "query", "-l", str(vcf)]).splitlines(),
            },
            "original_reference_provenance": REFERENCE_PROVENANCE[caller],
            "vcf_header_path": str(header_path),
            "contig_declarations_path": str(header_contig_path),
            "per_contig_counts_path": str(contig_counts_path),
            "representative_records_path": str(raw_path),
            "contig_count": len(all_contigs),
            "contigs_with_records": len(index_counts),
            "contigs": contig_reports,
            "target_contigs_inspected": targeted,
            "reference_identity_status": reference_identity,
            "contig_compatibility_status": contig_compatibility,
            "variant_scope_eligibility_status": variant_scope,
            "primary_canonical_contig_snv_indel_records": eligible_primary,
            "auxiliary_or_noncanonical_contig_records": auxiliary_records,
            "ref_validation_status": ref_status,
            "ref_validation_error": ref_error,
            "status_limitations": [
                "The canonical UCSC FASTA is a comparator, not proven to be the original caller FASTA.",
                "A source sequence SHA-256 cannot be calculated without the original source FASTA or a publisher-provided per-contig SHA-256 manifest.",
                "VCF contig MD5 declarations, when present, are compared to the canonical comparator; absent MD5 declarations remain unresolved.",
                "REF validation applies only to the canonical-contig projection; original auxiliary records remain preserved and are not silently discarded from source evidence.",
            ],
        }
    atomic_json(output_dir / "caller-reference-provenance-report.json", result)
    return result
