#!/usr/bin/env python3
"""Full GRCh38 qualification and HG002 GIAB benchmarking for three caller VCFs.

This is an analytical benchmarking harness, not a clinical assay validation.
All large datasets and derived files stay under --work-dir (normally /tmp).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path
from typing import Any

UCSC_BASE = "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/latest"
UCSC_FASTA = f"{UCSC_BASE}/hg38.fa.gz"
UCSC_MD5 = f"{UCSC_BASE}/md5sum.txt"
UCSC_EXPECTED_MD5 = "efb4edf237dd3594e94610ed803c8a44"
UCSC_CHR20 = "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/chromosomes/chr20.fa.gz"
GIAB_BASE = (
    "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/ftp/release/"
    "AshkenazimTrio/HG002_NA24385_son/NISTv4.2.1/GRCh38"
)
GIAB_VCF = f"{GIAB_BASE}/HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz"
GIAB_BED = f"{GIAB_BASE}/HG002_GRCh38_1_22_v4.2.1_benchmark_noinconsistent.bed"
GIAB_TBI = f"{GIAB_VCF}.tbi"
STRAT_URL = (
    "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/ftp/release/"
    "genome-stratifications/v3.6/genome-stratifications-GRCh38@all.tar.gz"
)
STRAT_MD5_URL = f"{STRAT_URL}.md5"
EXPECTED_CALLERS = {
    "GATK_HAPLOTYPECALLER": "gatk_haplotypecaller",
    "DEEPVARIANT": "deepvariant_germline",
    "DRAGEN": "dragen_snv_germline",
}


def load_smoke_module():
    path = Path(__file__).with_name("run_real_caller_vcf_smoke.py")
    spec = importlib.util.spec_from_file_location("siraloom_real_caller_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load existing real-caller harness: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def request_bytes(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "SIRALOOM-GRCh38-GIAB-qualification/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)
    if destination.stat().st_size == 0:
        raise RuntimeError(f"Downloaded empty resource: {url}")


def request_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "SIRALOOM-GRCh38-GIAB-qualification/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(command: list[str], *, timeout: int = 7200) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if completed.returncode:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout[-3000:]}\nstderr:\n{completed.stderr[-6000:]}"
        )
    return completed.stdout + completed.stderr


def executable_version(command: list[str]) -> str:
    return run(command, timeout=60).strip()


def build_fai(fasta: Path) -> list[dict[str, Any]]:
    """Build a standard .fai while validating FASTA wrapping and sequence alphabet."""
    entries: list[dict[str, Any]] = []
    with fasta.open("rb") as handle:
        name = None
        length = 0
        seq_offset = 0
        line_bases = None
        line_width = None
        previous_line_bases = None
        while True:
            offset = handle.tell()
            line = handle.readline()
            if not line:
                if name is not None:
                    entries.append({
                        "name": name, "length": length, "offset": seq_offset,
                        "line_bases": line_bases, "line_width": line_width,
                    })
                break
            raw_line = line
            line_ending_bytes = len(raw_line) - len(raw_line.rstrip(b"\r\n"))
            line = raw_line.rstrip(b"\r\n")
            if not line:
                raise RuntimeError(f"Blank FASTA line near byte offset {offset}")
            if line.startswith(b">"):
                if name is not None:
                    entries.append({
                        "name": name, "length": length, "offset": seq_offset,
                        "line_bases": line_bases, "line_width": line_width,
                    })
                header = line[1:].decode("ascii").strip()
                if not header:
                    raise RuntimeError("Empty FASTA sequence identifier")
                name = header.split()[0]
                length = 0
                seq_offset = handle.tell()
                line_bases = None
                line_width = None
                previous_line_bases = None
                continue
            if name is None:
                raise RuntimeError("FASTA sequence encountered before first header")
            seq = line.upper()
            if set(seq) - set(b"ACGTRYSWKMBDHVN"):
                raise RuntimeError(f"Invalid IUPAC nucleotide in FASTA contig {name}")
            bases = len(line)
            width = len(line) + line_ending_bytes
            if line_bases is None:
                line_bases, line_width = bases, width
            elif previous_line_bases != line_bases:
                raise RuntimeError(f"Non-final FASTA line has inconsistent width on {name}")
            previous_line_bases = bases
            length += bases
    if not entries or len({e["name"] for e in entries}) != len(entries):
        raise RuntimeError("FASTA has no sequences or duplicate sequence identifiers")
    fai = Path(str(fasta) + ".fai")
    with fai.open("w", encoding="ascii", newline="\n") as out:
        for e in entries:
            out.write(
                f'{e["name"]}\t{e["length"]}\t{e["offset"]}\t'
                f'{e["line_bases"]}\t{e["line_width"]}\n'
            )
    return entries


def fasta_sequence(fasta: Path, wanted: str) -> str:
    chunks: list[str] = []
    active = False
    with fasta.open("rt", encoding="ascii") as handle:
        for line in handle:
            if line.startswith(">"):
                if active:
                    break
                active = line[1:].split()[0] == wanted
            elif active:
                chunks.append(line.strip().upper())
    if not chunks:
        raise RuntimeError(f"Contig {wanted} not found in {fasta}")
    return "".join(chunks)


def qualify_reference(root: Path, smoke):
    compressed = root / "hg38.fa.gz"
    fasta = root / "hg38.fa"
    if not compressed.exists():
        request_bytes(UCSC_FASTA, compressed)
    published = request_text(UCSC_MD5)
    match = re.search(rf"^([0-9a-fA-F]{{32}})\s+hg38\.fa\.gz$", published, re.MULTILINE)
    if not match:
        raise RuntimeError("UCSC md5sum.txt does not contain hg38.fa.gz")
    published_md5 = match.group(1).lower()
    if published_md5 != UCSC_EXPECTED_MD5:
        raise RuntimeError(
            f"UCSC reference checksum manifest changed: expected pinned {UCSC_EXPECTED_MD5}, "
            f"published {published_md5}; require explicit source requalification"
        )
    observed_md5 = md5(compressed)
    if observed_md5 != published_md5:
        raise RuntimeError(f"UCSC FASTA MD5 mismatch: expected {published_md5}, observed {observed_md5}")
    if not fasta.exists() or fasta.stat().st_size == 0:
        with gzip.open(compressed, "rb") as source, fasta.open("wb") as target:
            shutil.copyfileobj(source, target, length=4 * 1024 * 1024)
    entries = build_fai(fasta)
    lengths = {e["name"]: e["length"] for e in entries}
    if "chr20" not in lengths:
        raise RuntimeError("Pinned UCSC GRCh38 FASTA does not contain chr20")
    chr20_gz = root / "ucsc_chr20_fixture.fa.gz"
    if not chr20_gz.exists():
        request_bytes(UCSC_CHR20, chr20_gz)
    fixture_fa = root / "ucsc_chr20_fixture.fa"
    if not fixture_fa.exists():
        with gzip.open(chr20_gz, "rb") as source, fixture_fa.open("wb") as target:
            shutil.copyfileobj(source, target)
    fixture = fasta_sequence(fixture_fa, "chr20")
    whole = fasta_sequence(fasta, "chr20")
    if fixture != whole:
        raise RuntimeError(
            f"Full UCSC hg38.fa chr20 differs from the existing chr20 fixture "
            f"(fixture={len(fixture)}, full={len(whole)})"
        )
    fai_path = Path(str(fasta) + ".fai")
    return {
        "assembly_label": "GRCh38 / UCSC hg38",
        "source_url": UCSC_FASTA,
        "checksum_manifest_url": UCSC_MD5,
        "published_md5": published_md5,
        "observed_md5": observed_md5,
        "sha256": sha256(compressed),
        "compressed_bytes": compressed.stat().st_size,
        "uncompressed_bytes": fasta.stat().st_size,
        "fasta_sha256": sha256(fasta),
        "fai_sha256": sha256(fai_path),
        "contig_count": len(entries),
        "contigs": entries,
        "chr20_fixture": {
            "source_url": UCSC_CHR20,
            "length": len(fixture),
            "full_reference_length": len(whole),
            "sequence_sha256": hashlib.sha256(whole.encode("ascii")).hexdigest(),
            "exact_sequence_match": True,
        },
        "status": "PASS",
    }, fasta, lengths


def download_giab(root: Path, smoke):
    resources = [
        ("truth_vcf", GIAB_VCF),
        ("truth_vcf_tbi", GIAB_TBI),
        ("high_confidence_bed", GIAB_BED),
    ]
    result = {}
    for label, url in resources:
        target = root / Path(url).name
        if not target.exists():
            request_bytes(url, target)
        result[label] = {
            "url": url, "path": str(target), "bytes": target.stat().st_size,
            "sha256": sha256(target), "md5": md5(target),
        }
    if not result["truth_vcf"]["bytes"] or not result["high_confidence_bed"]["bytes"]:
        raise RuntimeError("GIAB truth VCF or high-confidence BED is empty")
    run(["gzip", "-t", result["truth_vcf"]["path"]])
    run(["bcftools", "index", "-n", result["truth_vcf"]["path"]])
    return result


def download_stratifications(root: Path):
    archive = root / "genome-stratifications-GRCh38@all.tar.gz"
    checksum_file = root / "genome-stratifications-GRCh38@all.tar.gz.md5"
    if not archive.exists():
        request_bytes(STRAT_URL, archive)
    try:
        if not checksum_file.exists():
            request_bytes(STRAT_MD5_URL, checksum_file)
        checksum_text = checksum_file.read_text(encoding="ascii")
        expected = re.search(r"\b([0-9a-fA-F]{32})\b", checksum_text)
        if not expected or md5(archive) != expected.group(1).lower():
            raise RuntimeError("GIAB stratification archive MD5 verification failed")
        checksum_status = "PASS"
    except Exception as error:
        raise RuntimeError(f"Could not verify GIAB stratification archive checksum: {error}") from error

    output = root / "stratifications"
    output.mkdir(parents=True, exist_ok=True)
    patterns = {
        "all_difficult": re.compile(r"GRCh38_alldifficultregions\.bed\.gz$", re.I),
        "low_mappability_segmental_duplication": re.compile(r"GRCh38_alllowmapandsegdupregions\.bed\.gz$", re.I),
        "homopolymers": re.compile(r"GRCh38_AllHomopolymers.*\.bed\.gz$", re.I),
        "tandem_repeats": re.compile(r"GRCh38_AllTandemRepeatsandHomopolymers.*\.bed\.gz$", re.I),
    }
    selected = {}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            for label, pattern in patterns.items():
                if label in selected or not pattern.search(member.name):
                    continue
                stream = tar.extractfile(member)
                if stream is None:
                    continue
                destination = output / f"{label}.bed.gz"
                with destination.open("wb") as target:
                    shutil.copyfileobj(stream, target)
                selected[label] = {
                    "path": str(destination), "archive_member": member.name,
                    "bytes": destination.stat().st_size, "sha256": sha256(destination),
                }
    if "all_difficult" not in selected:
        raise RuntimeError("GIAB v3.6 stratification archive lacks GRCh38_alldifficultregions.bed.gz")
    return {
        "version": "GIAB genome stratifications v3.6",
        "archive_url": STRAT_URL, "archive_md5": md5(archive),
        "archive_sha256": sha256(archive), "archive_checksum_status": checksum_status,
        "selected_beds": selected,
    }


def observed_contigs(vcf: Path) -> set[str]:
    proc = subprocess.Popen(
        ["bcftools", "query", "-f", "%CHROM\\n", str(vcf)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert proc.stdout is not None
    names = set()
    for line in proc.stdout:
        value = line.strip()
        if value:
            names.add(value)
    stderr = proc.stderr.read() if proc.stderr else ""
    code = proc.wait()
    if code:
        raise RuntimeError(f"bcftools query contigs failed for {vcf}: {stderr[-3000:]}")
    return names


def run_reference_pipeline(callset: dict[str, Any], fasta: Path, lengths: dict[str, int], root: Path, smoke):
    caller = callset["caller"]
    source = Path(callset["local_path"])
    if caller == "DRAGEN":
        attestation = smoke.dragen_gp_attestation(callset, source)
    else:
        attestation = None
    strict = smoke.validate_vcf_strict(source, caller_attestation=attestation)
    provenance = strict["caller_provenance"]
    expected_profile = EXPECTED_CALLERS[caller]
    if provenance.get("caller_profile_id") != expected_profile:
        raise RuntimeError(
            f"{caller} profile mismatch: expected {expected_profile}, "
            f"observed {provenance.get('caller_profile_id')}"
        )
    present_contigs = observed_contigs(source)
    unknown = sorted(present_contigs - set(lengths))
    if unknown:
        raise RuntimeError(f"{caller} has records on contigs absent from pinned UCSC reference: {unknown[:30]}")
    routed_dir = root / f"{caller.lower()}_full_reference_routed"
    routed = smoke.route_vcf_records(source, routed_dir, reference_contig_lengths=lengths)
    sequence_path = routed.get("sequence_path")
    if not sequence_path or int(routed.get("sequence_records", 0)) <= 0:
        raise RuntimeError(f"{caller}: no sequence-resolved SNV/indel records available for full-reference check")
    normalized = root / f"{caller.lower()}.grch38.normalized.vcf.gz"
    norm = smoke.normalize_vcf_with_bcftools(
        sequence_path, normalized, reference_fasta=fasta,
        expected_bcftools_version="1.25", timeout_seconds=7200,
    )
    normalized_attestation = smoke.dragen_gp_attestation(callset, normalized) if caller == "DRAGEN" else None
    normalized_strict = smoke.validate_vcf_strict(normalized, caller_attestation=normalized_attestation)
    if not Path(str(normalized) + ".csi").exists() and not Path(str(normalized) + ".tbi").exists():
        raise RuntimeError(f"{caller}: normalized full-reference output has no index")
    return {
        "caller": caller,
        "source": {
            "filename": callset["filename"], "bytes": callset["bytes"],
            "sha256": callset["sha256"], "zenodo_checksum": callset["zenodo_checksum"],
            "observed_records": strict["records"], "vcf_version": strict["fileformat"],
            "sample_count": strict["sample_count"],
        },
        "caller_provenance": provenance,
        "reference_contigs_observed_in_vcf": sorted(present_contigs),
        "unknown_record_contigs": [],
        "routing": routed,
        "full_reference_ref_check": {
            "status": "PASS",
            "method": "SIRALOOM sequence-resolved routing followed by BCFtools 1.25 normalization with full UCSC GRCh38 FASTA and REF check -c e",
            "normalized_records": normalized_strict["records"],
            "output_path": str(normalized), "output_bytes": normalized.stat().st_size,
            "output_sha256": sha256(normalized),
            "source_child_reconciliation": norm.get("source_child_reconciliation"),
            "tool_evidence": norm,
        },
        "normalized_vcf": str(normalized),
        "semantic_review_required": bool(strict.get("caller_semantic_compatibility_review_required")),
    }


def count_records(vcf: Path) -> int:
    output = run(["bcftools", "view", "-H", str(vcf)], timeout=7200)
    return sum(1 for line in output.splitlines() if line)


def split_variant_types(source: Path, root: Path, caller: str):
    result = {}
    for label, kind in (("snv", "snps"), ("indel", "indels")):
        path = root / f"{caller.lower()}.{label}.vcf.gz"
        run(["bcftools", "view", "-v", kind, "-Oz", "-o", str(path), str(source)])
        run(["bcftools", "index", "-f", str(path)])
        result[label] = path
    return result


def rtg_eval(rtg: str, template: Path, truth: Path, query: Path, regions: Path, outdir: Path):
    if outdir.exists():
        shutil.rmtree(outdir)
    command = [
        rtg, "vcfeval", "-b", str(truth), "-c", str(query), "-t", str(template),
        "-o", str(outdir), "--evaluation-regions", str(regions),
    ]
    log = run(command, timeout=7200)
    summary = outdir / "summary.txt"
    if not summary.exists():
        raise RuntimeError(f"RTG vcfeval did not produce summary.txt in {outdir}")
    counts = {}
    for label in ("tp", "fp", "fn"):
        candidate = outdir / f"{label}.vcf.gz"
        if candidate.exists():
            counts[label] = count_records(candidate)
        else:
            counts[label] = None
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    precision = tp / (tp + fp) if tp is not None and fp is not None and tp + fp else None
    recall = tp / (tp + fn) if tp is not None and fn is not None and tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall else None
    )
    return {
        "command": command, "command_log": log[-12000:],
        "summary_path": str(summary), "summary_text": summary.read_text(encoding="utf-8", errors="replace"),
        "output_directory": str(outdir),
        "output_files": sorted(p.name for p in outdir.iterdir() if p.is_file()),
        "variant_record_counts": counts,
        "precision_from_RTG_TP_FP_records": precision,
        "recall_from_RTG_TP_FN_records": recall,
        "f1_from_RTG_TP_FP_FN_records": f1,
        "metric_caveat": (
            "TP/FP/FN are counts of RTG emitted VCF records, not independently reconstructed "
            "allele counts. Retain RTG summary and raw outputs as authoritative comparison evidence."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, default=Path("/tmp/siraloom-grch38-giab"))
    parser.add_argument("--report", type=Path, default=Path("artifacts/grch38-giab-three-caller-report.json"))
    parser.add_argument("--rtg", default="rtg")
    args = parser.parse_args()
    root = args.work_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema_version": 1,
        "intended_scope": "HG002 germline SNV and small-indel caller VCF benchmarking on UCSC GRCh38",
        "clinical_status": "SOFTWARE_BENCHMARK_ONLY_NOT_CLINICAL_ASSAY_VALIDATION",
        "reference": {}, "giab": {}, "stratifications": {}, "callers": {},
        "tool_versions": {}, "failures": [],
    }
    try:
        smoke = load_smoke_module()
        report["tool_versions"]["bcftools"] = executable_version(["bcftools", "--version"]).splitlines()[:2]
        report["tool_versions"]["rtg"] = executable_version([args.rtg, "version"])
        report["reference"], fasta, lengths = qualify_reference(root, smoke)
        report["tool_versions"]["reference_indexer"] = "SIRALOOM streaming FASTA index builder (FAI format)"
        report["giab"] = download_giab(root, smoke)
        report["stratifications"] = download_stratifications(root)
        sdf = root / "ucsc_hg38.sdf"
        if not sdf.exists():
            run([args.rtg, "format", "-o", str(sdf), str(fasta)], timeout=7200)
        report["reference"]["rtg_sdf_path"] = str(sdf)
        report["reference"]["rtg_sdf_status"] = "PASS"
        callsets = smoke.download_callsets(root / "caller_vcfs")
        for callset in callsets:
            caller = callset["caller"]
            try:
                result = run_reference_pipeline(callset, fasta, lengths, root, smoke)
                normalized = Path(result["normalized_vcf"])
                by_type = split_variant_types(normalized, root, caller)
                evaluations = {}
                regions = {"giab_high_confidence": Path(report["giab"]["high_confidence_bed"]["path"])}
                for label, meta in report["stratifications"]["selected_beds"].items():
                    regions[label] = Path(meta["path"])
                for variant_type, query in by_type.items():
                    evaluations[variant_type] = {}
                    for region_name, region_bed in regions.items():
                        outdir = root / "rtg" / caller.lower() / variant_type / region_name
                        evaluations[variant_type][region_name] = rtg_eval(
                            args.rtg, sdf, Path(report["giab"]["truth_vcf"]["path"]),
                            query, region_bed, outdir,
                        )
                result["benchmark"] = {
                    "truth_set": report["giab"],
                    "evaluations": evaluations,
                    "genotype_concordance": {
                        "status": "RAW_RTG_SUMMARY_AND_MATCHED_TP_VCFS_RETAINED",
                        "method": "RTG vcfeval genotype-aware haplotype comparison",
                        "interpretation": (
                            "Genotype-aware matches and discordances are retained in RTG summary "
                            "and TP/FP/FN VCF outputs. No independent site-by-site genotype metric "
                            "is asserted unless explicitly present in the RTG summary."
                        ),
                    },
                }
                report["callers"][caller] = result
            except Exception as error:
                report["callers"][caller] = {
                    "status": "FAIL", "error_type": type(error).__name__, "error": str(error),
                }
                report["failures"].append(f"{caller}: {type(error).__name__}: {error}")
        for caller, result in report["callers"].items():
            if result.get("full_reference_ref_check", {}).get("status") != "PASS":
                report["failures"].append(f"{caller}: full-reference REF validation not PASS")
            if result.get("semantic_review_required"):
                report["failures"].append(f"{caller}: caller semantic deviation remains review-required")
            if not result.get("benchmark", {}).get("evaluations"):
                report["failures"].append(f"{caller}: no GIAB benchmark outputs")
        report["overall"] = "PASS" if not report["failures"] else "FAIL"
    except Exception as error:
        report["overall"] = "FAIL"
        report["failures"].append(f"Qualification harness: {type(error).__name__}: {error}")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if report.get("reference"):
        (args.report.parent / "reference-manifest.json").write_text(
            json.dumps(report["reference"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    dataset_manifest = {
        "giab": report.get("giab", {}),
        "stratifications": report.get("stratifications", {}),
        "callsets": [
            {"caller": name, **value.get("source", {})}
            for name, value in report.get("callers", {}).items()
        ],
        "tool_versions": report.get("tool_versions", {}),
    }
    (args.report.parent / "dataset-manifest.json").write_text(
        json.dumps(dataset_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
