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
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

UCSC_BASE = "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/latest"
UCSC_FASTA = f"{UCSC_BASE}/hg38.fa.gz"
UCSC_MD5 = f"{UCSC_BASE}/md5sum.txt"
UCSC_EXPECTED_MD5 = "efb4edf237dd3594e94610ed803c8a44"
UCSC_CHR20 = "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/chromosomes/chr20.fa.gz"
GIAB_BASE = (
    "https://ftp-trace.ncbi.nlm.nih.gov/giab/ftp/release/"
    "AshkenazimTrio/HG002_NA24385_son/NISTv4.2.1/GRCh38"
)
GIAB_VCF = f"{GIAB_BASE}/HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz"
GIAB_BED = f"{GIAB_BASE}/HG002_GRCh38_1_22_v4.2.1_benchmark_noinconsistent.bed"
GIAB_TBI = f"{GIAB_VCF}.tbi"
STRAT_URL = (
    "https://ftp-trace.ncbi.nlm.nih.gov/giab/ftp/release/"
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


def http_error_context(url: str, destination: Path | None, status: int, reason: str) -> str:
    target = f"; destination={destination}" if destination is not None else ""
    return f"HTTP request failed: status={status}, reason={reason!r}, url={url!r}{target}"


def request_bytes(url: str, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "SIRALOOM-GRCh38-GIAB-qualification/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
            transfer = {
                "http_status": response.status,
                "final_url": response.geturl(),
                "content_length_header": response.headers.get("Content-Length"),
            }
    except urllib.error.HTTPError as error:
        raise RuntimeError(http_error_context(url, destination, error.code, error.reason)) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"URL request failed: url={url!r}, reason={error.reason!r}, destination={destination}") from error
    if destination.stat().st_size == 0:
        raise RuntimeError(f"Downloaded empty resource: url={url!r}, destination={destination}")
    transfer["downloaded_bytes"] = destination.stat().st_size
    return transfer


def request_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "SIRALOOM-GRCh38-GIAB-qualification/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raise RuntimeError(http_error_context(url, None, error.code, error.reason)) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"URL request failed: url={url!r}, reason={error.reason!r}") from error


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
        print(f"[GIAB_RESOURCE_VERIFY] resource={label} url={url}", flush=True)
        if target.exists() and target.stat().st_size:
            transfer = {
                "verification": "CACHED_LOCAL_FILE",
                "downloaded_bytes": target.stat().st_size,
            }
        else:
            transfer = request_bytes(url, target)
            transfer["verification"] = "HTTP_DOWNLOAD_VERIFIED"
        result[label] = {
            "url": url, "path": str(target), "bytes": target.stat().st_size,
            "sha256": sha256(target), "md5": md5(target),
            "url_verification": transfer,
        }
        print(
            f"[GIAB_RESOURCE_VERIFIED] resource={label} "
            f"verification={transfer['verification']} bytes={target.stat().st_size}",
            flush=True,
        )
    if not result["truth_vcf"]["bytes"] or not result["high_confidence_bed"]["bytes"]:
        raise RuntimeError("GIAB truth VCF or high-confidence BED is empty")
    run(["gzip", "-t", result["truth_vcf"]["path"]])
    run(["bcftools", "index", "-n", result["truth_vcf"]["path"]])
    result["truth_vcf"]["sample_names"] = run(["bcftools", "query", "-l", result["truth_vcf"]["path"]]).splitlines()
    if len(result["truth_vcf"]["sample_names"]) != 1:
        raise RuntimeError("HG002 GIAB benchmark VCF must contain exactly one sample")
    return result


def download_stratifications(root: Path):
    archive = root / "genome-stratifications-GRCh38@all.tar.gz"
    checksum_file = root / "genome-stratifications-GRCh38@all.tar.gz.md5"
    if not archive.exists():
        request_bytes(STRAT_URL, archive)
    # The NCBI stratification release does not expose a consistently addressable
    # sidecar checksum at this archive URL; preserve observed hashes without
    # mislabelling them as publisher-verified.
    checksum_status = "OBSERVED_HASH_ONLY"

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
        ["bcftools", "query", "-f", "%CHROM\n", str(vcf)],
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


def project_vcf_by_reference_contigs(
    source: Path,
    projection_path: Path,
    auxiliary_path: Path,
    allowed_contigs: set[str],
) -> dict[str, Any]:
    """Create an explicit benchmark projection without discarding source records.

    Records on contigs absent from the benchmark FASTA are retained verbatim in
    a separate auxiliary VCF. They are not declared invalid; they are outside
    this UCSC-reference-coordinate benchmark until their source sequence
    identity has been independently established.
    """
    opener = gzip.open if source.name.lower().endswith((".gz", ".bgz")) else open
    projection_path.parent.mkdir(parents=True, exist_ok=True)
    auxiliary_path.parent.mkdir(parents=True, exist_ok=True)
    auxiliary_counts: dict[str, int] = {}
    projection_count = 0
    auxiliary_count = 0
    header_lines = 0
    with opener(source, "rt", encoding="utf-8-sig") as input_handle, \
         projection_path.open("w", encoding="utf-8", newline="\n") as projection, \
         auxiliary_path.open("w", encoding="utf-8", newline="\n") as auxiliary:
        for raw in input_handle:
            if raw.startswith("#"):
                projection.write(raw)
                auxiliary.write(raw)
                header_lines += 1
                continue
            line = raw.rstrip("\r\n")
            fields = line.split("\t", 2)
            if len(fields) < 2:
                raise RuntimeError(f"Malformed source VCF row while projecting benchmark contigs: {line[:200]!r}")
            chrom = fields[0]
            if chrom in allowed_contigs:
                projection.write(raw)
                projection_count += 1
            else:
                auxiliary.write(raw)
                auxiliary_count += 1
                auxiliary_counts[chrom] = auxiliary_counts.get(chrom, 0) + 1
    if projection_count == 0:
        raise RuntimeError(f"No records overlap the pinned benchmark reference contigs in {source}")
    return {
        "projection_path": str(projection_path),
        "projection_record_count": projection_count,
        "auxiliary_path": str(auxiliary_path),
        "auxiliary_record_count": auxiliary_count,
        "auxiliary_records_by_contig": dict(sorted(auxiliary_counts.items())),
        "header_line_count": header_lines,
        "source_record_count": projection_count + auxiliary_count,
        "disposition": "CANONICAL_REFERENCE_PROJECTION_WITH_AUXILIARY_RECORDS_PRESERVED",
    }


def run_reference_pipeline(callset: dict[str, Any], fasta: Path, lengths: dict[str, int], root: Path, smoke):
    caller = callset["caller"]
    source = Path(callset["local_path"])
    if caller == "DRAGEN":
        attestation = smoke.dragen_gp_attestation(callset, source)
    else:
        attestation = None
    strict = smoke.validate_vcf_strict(source, caller_attestation=attestation)
    provenance = strict["caller_provenance"]
    if strict["sample_count"] != 1:
        raise RuntimeError(f"{caller}: expected one HG002 sample in caller VCF, observed {strict['sample_count']}")
    sample_names = run(["bcftools", "query", "-l", str(source)]).splitlines()
    expected_profile = EXPECTED_CALLERS[caller]
    if provenance.get("caller_profile_id") != expected_profile:
        raise RuntimeError(
            f"{caller} profile mismatch: expected {expected_profile}, "
            f"observed {provenance.get('caller_profile_id')}"
        )
    present_contigs = observed_contigs(source)
    unknown = sorted(present_contigs - set(lengths))
    projection_dir = root / f"{caller.lower()}_reference_projection"
    projection = project_vcf_by_reference_contigs(
        source,
        projection_dir / "canonical-reference-projection.vcf",
        projection_dir / "auxiliary-noncanonical-records.vcf",
        set(lengths),
    )
    routed_dir = root / f"{caller.lower()}_full_reference_routed"
    routed = smoke.route_vcf_records(
        projection["projection_path"], routed_dir, reference_contig_lengths=lengths
    )
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
            "sample_count": strict["sample_count"], "sample_names": sample_names,
        },
        "caller_provenance": provenance,
        "reference_contigs_observed_in_vcf": sorted(present_contigs),
        "unknown_record_contigs": unknown,
        "benchmark_reference_projection": projection,
        "original_reference_identity_status": "UNRESOLVED_SOURCE_REFERENCE_IDENTITY",
        "auxiliary_contigs_excluded_from_giab_comparison_not_discarded": True,
        "routing": routed,
        "full_reference_ref_check": {
            "status": "PASS_ON_CANONICAL_REFERENCE_PROJECTION",
            "method": "SIRALOOM sequence-resolved routing of the explicit canonical-contig projection followed by BCFtools 1.25 normalization with full UCSC GRCh38 FASTA and REF check -c e; noncanonical source records are preserved separately and excluded from this benchmark",
            "normalized_records": normalized_strict["records"],
            "source_reference_identity": "UNRESOLVED_SOURCE_REFERENCE_IDENTITY",
            "projection_record_count": projection["projection_record_count"],
            "auxiliary_record_count": projection["auxiliary_record_count"],
            "auxiliary_records_by_contig": projection["auxiliary_records_by_contig"],
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


def genotype_comparison(query: Path, truth: Path, regions: Path, contig_order: dict[str, int]):
    """Compare GTs for exactly shared normalized alleles inside the GIAB BED.

    This is a shared-allele genotype concordance metric; RTG remains authoritative
    for TP/FP/FN because this calculation does not count unmatched calls.
    """
    fmt = "%CHROM\t%POS\t%REF\t%ALT[\t%GT]\n"

    def stream(path: Path):
        proc = subprocess.Popen(
            ["bcftools", "query", "-R", str(regions), "-f", fmt, str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 5:
                raise RuntimeError(f"Expected one-sample genotype row from {path}: {line!r}")
            chrom, pos, ref, alt, gt = fields
            if chrom not in contig_order:
                raise RuntimeError(f"Unknown contig in genotype comparison: {chrom}")
            alleles = gt.replace("|", "/").split("/")
            normalized_gt = None if "." in alleles else tuple(sorted(alleles))
            yield ((contig_order[chrom], int(pos), ref, alt), normalized_gt)
        stderr = proc.stderr.read() if proc.stderr else ""
        code = proc.wait()
        if code:
            raise RuntimeError(f"bcftools query failed for genotype comparison ({path}): {stderr[-3000:]}")

    left, right = iter(stream(query)), iter(stream(truth))
    a, b = next(left, None), next(right, None)
    compared = matches = discordant = missing = 0
    while a is not None and b is not None:
        if a[0] == b[0]:
            if a[1] is None or b[1] is None:
                missing += 1
            else:
                compared += 1
                if a[1] == b[1]:
                    matches += 1
                else:
                    discordant += 1
            a, b = next(left, None), next(right, None)
        elif a[0] < b[0]:
            a = next(left, None)
        else:
            b = next(right, None)
    return {
        "method": "exact normalized CHROM/POS/REF/ALT shared-allele GT comparison within GIAB high-confidence BED",
        "compared_shared_alleles": compared,
        "matching_genotypes": matches,
        "discordant_genotypes": discordant,
        "missing_genotype_pairs": missing,
        "genotype_concordance": matches / compared if compared else None,
        "genotype_discordance_rate": discordant / compared if compared else None,
        "scope_limitation": (
            "Denominator includes only alleles represented in both callsets with non-missing GTs. "
            "It is not whole-callset concordance and does not count unmatched FP/FN; RTG vcfeval "
            "TP/FP/FN remains the primary representation-aware benchmark."
        ),
    }


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

        # Persist source identity and checksums immediately after acquisition,
        # before reference validation or any caller-specific processing can fail.
        args.report.parent.mkdir(parents=True, exist_ok=True)
        acquisition_manifest = {
            "schema_version": 1,
            "acquisition_status": "COMPLETE",
            "callsets": [
                {
                    key: value for key, value in item.items()
                    if key != "local_path"
                } | {"local_path": str(Path(item["local_path"]).name)}
                for item in callsets
            ],
        }
        (args.report.parent / "caller-acquisition-manifest.json").write_text(
            json.dumps(acquisition_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report["caller_acquisition_manifest"] = acquisition_manifest

        diagnostic_path = Path(__file__).with_name(
            "inspect_grch38_callset_reference_provenance.py"
        )
        diagnostic_spec = importlib.util.spec_from_file_location(
            "siraloom_grch38_reference_diagnostics", diagnostic_path
        )
        if diagnostic_spec is None or diagnostic_spec.loader is None:
            raise RuntimeError("Could not load caller reference provenance diagnostics")
        diagnostic_module = importlib.util.module_from_spec(diagnostic_spec)
        sys.modules[diagnostic_spec.name] = diagnostic_module
        diagnostic_spec.loader.exec_module(diagnostic_module)
        report["caller_reference_provenance"] = diagnostic_module.inspect_callsets(
            callsets, fasta, args.report.parent / "caller-reference-provenance"
        )
        truth_normalized = root / "giab.hg002.normalized.vcf.gz"
        run(["bcftools", "norm", "-f", str(fasta), "-c", "e", "-m", "-any", "-Oz", "-o", str(truth_normalized), report["giab"]["truth_vcf"]["path"]], timeout=7200)
        run(["bcftools", "index", "-f", str(truth_normalized)])
        report["giab"]["normalized_truth"] = {
            "path": str(truth_normalized), "sha256": sha256(truth_normalized),
            "records": count_records(truth_normalized),
            "method": "BCFtools 1.25 -f UCSC GRCh38 -c e -m -any",
        }
        truth_by_type = split_variant_types(truth_normalized, root, "GIAB_HG002")
        contig_order = {entry["name"]: index for index, entry in enumerate(report["reference"]["contigs"])}
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
                genotype_metrics = {}
                for variant_type, query in by_type.items():
                    evaluations[variant_type] = {}
                    genotype_metrics[variant_type] = genotype_comparison(
                        query, truth_by_type[variant_type], regions["giab_high_confidence"], contig_order
                    )
                    for region_name, region_bed in regions.items():
                        outdir = root / "rtg" / caller.lower() / variant_type / region_name
                        evaluations[variant_type][region_name] = rtg_eval(
                            args.rtg, sdf, Path(report["giab"]["truth_vcf"]["path"]),
                            query, region_bed, outdir,
                        )
                result["benchmark"] = {
                    "truth_set": report["giab"],
                    "evaluations": evaluations,
                    "genotype_concordance": genotype_metrics,
                }
                report["callers"][caller] = result
            except Exception as error:
                report["callers"][caller] = {
                    "status": "FAIL", "error_type": type(error).__name__, "error": str(error),
                }
                report["failures"].append(f"{caller}: {type(error).__name__}: {error}")
        for caller, result in report["callers"].items():
            if result.get("full_reference_ref_check", {}).get("status") != "PASS_ON_CANONICAL_REFERENCE_PROJECTION":
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
