from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import ExitStack
from functools import lru_cache
from pathlib import Path

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    _base_modification_field_kind,
    _parse_field_definition,
    declared_vcf_contig_lengths,
)

GVCF_WILDCARD_ALLELES = {"<NON_REF>", "<*>"}
SOURCE_RECORD_TAG = "SIRALOOM_SOURCE"
SOURCE_RECORD_TAG_HEADER = (
    '##INFO=<ID=SIRALOOM_SOURCE,Number=1,Type=String,'
    'Description="Base64url JSON source record identity and ALT mapping">')


def route_vcf_records(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    reference_contig_lengths: dict[str, int] | None = None,
) -> dict:
    """Partition a validated VCF without changing records or sample semantics.

    Only sequence-resolved records are sent to ordinary normalization. GVCF
    reference blocks and structural records are copied byte-for-text unchanged
    into separate review artifacts. A GVCF variant is eligible for the
    sequence path only when every sample has a complete GT that does not call
    a wildcard allele; bcftools 1.24 ``view -A`` then removes that unseen
    wildcard while updating allele-indexed fields.
    """
    import gzip

    source = Path(input_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    coordinate_lengths = (
        reference_contig_lengths
        if reference_contig_lengths is not None
        else declared_vcf_contig_lengths(source)
    )
    names = {
        "sequence": output / "sequence-input.vcf",
        "gvcf_blocks": output / "gvcf-reference-blocks.vcf",
        "gvcf_unresolved": output / "gvcf-unresolved-variants.vcf",
        "structural": output / "structural-variants.vcf",
        "spanning_deletions": output / "spanning-deletion-records.vcf",
        "telomere": output / "telomere-records.vcf",
        "telomere_after": output / "telomere-after-contig-records.vcf",
        "exclusions": output / "excluded-source-records.jsonl",
    }
    opener = gzip.open if source.name.lower().endswith((".gz", ".bgz")) else open
    headers: list[str] = []
    counts = {key: 0 for key in names}
    counts["reference_only"] = 0
    counts["reference_only_genotype_alleles"] = 0
    handles = {}
    sample_count = 0
    source_record_index = 0
    exclusion_handle = None
    excluded_source_record_indexes: set[int] = set()

    def record_exclusion(
        record: str,
        reason_code: str,
        routed_type: str,
        *,
        source_alt_index: int | None = None,
    ) -> None:
        nonlocal exclusion_handle
        if exclusion_handle is None:
            exclusion_handle = stack.enter_context(
                names["exclusions"].open("w", encoding="utf-8", newline="\n")
            )
        fields = record.split("\t")
        entry = {
            "schema_version": "1",
            "source_record_index": source_record_index,
            "source_record_sha256": hashlib.sha256(record.encode("utf-8")).hexdigest(),
            "chrom": fields[0],
            "pos": fields[1],
            "id": fields[2],
            "ref": fields[3],
            "alt": fields[4],
            "reason_code": reason_code,
            "routed_artifact_type": routed_type,
        }
        if source_alt_index is not None:
            entry["source_alt_index"] = source_alt_index
        else:
            excluded_source_record_indexes.add(source_record_index)
        exclusion_handle.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")

    def record_reference_genotype_exclusions(record: str, fields: list[str], alts: list[str]) -> None:
        if sample_count == 0 or len(fields) < 10:
            return
        format_keys = fields[8].split(":")
        if "GT" not in format_keys:
            return
        gt_index = format_keys.index("GT")
        called_alt_indexes: set[int] = set()
        for sample in fields[9:]:
            values = sample.split(":")
            if gt_index >= len(values):
                return
            genotype = values[gt_index]
            alleles = re.split(r"[/|]", genotype)
            if not alleles or any(not allele.isdigit() for allele in alleles):
                return
            called_alt_indexes.update(int(allele) for allele in alleles if int(allele) > 0)
        for index, alternate in enumerate(alts, start=1):
            if alternate not in GVCF_WILDCARD_ALLELES and index not in called_alt_indexes:
                counts["reference_only_genotype_alleles"] += 1
                record_exclusion(
                    record,
                    "REFERENCE_ONLY_GENOTYPE",
                    "SEQUENCE_NORMALIZATION_CANDIDATE_FILTER",
                    source_alt_index=index,
                )
    with ExitStack() as stack:
        def emit(key: str, record: str) -> None:
            handle = handles.get(key)
            if handle is None:
                handle = stack.enter_context(names[key].open("w", encoding="utf-8", newline="\n"))
                handles[key] = handle
                for header in headers:
                    if key == "sequence" and header.startswith("#CHROM\t"):
                        handle.write(SOURCE_RECORD_TAG_HEADER + "\n")
                    handle.write(header + "\n")
            if key == "sequence":
                record_fields = record.split("\t")
                if any(
                    item.startswith(SOURCE_RECORD_TAG + "=")
                    for item in record_fields[7].split(";")
                ):
                    raise VCFToolError(
                        f"Input VCF record already contains reserved INFO tag {SOURCE_RECORD_TAG}."
                    )
                source_alts = record_fields[4].split(",")
                source_payload = {
                    "schema_version": "1",
                    "source_record_index": source_record_index,
                    "source_record_sha256": hashlib.sha256(record.encode("utf-8")).hexdigest(),
                    "source_alt_count": len(source_alts),
                    "normalized_alt_source_indexes": [
                        index
                        for index, alternate in enumerate(source_alts, start=1)
                        if alternate not in GVCF_WILDCARD_ALLELES
                    ],
                }
                encoded_payload = base64.urlsafe_b64encode(
                    json.dumps(source_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).decode("ascii").rstrip("=")
                source_info = f"{SOURCE_RECORD_TAG}={encoded_payload}"
                record_fields[7] = (
                    f"{record_fields[7]};{source_info}"
                    if record_fields[7] not in {"", "."}
                    else source_info
                )
                record = "\t".join(record_fields)
            handle.write(record + "\n")
            counts[key] += 1

        with opener(source, "rt", encoding="utf-8-sig") as handle:
            for raw in handle:
                line = raw.rstrip("\r\n")
                if line.startswith("#"):
                    if line.startswith(f"##INFO=<ID={SOURCE_RECORD_TAG},"):
                        raise VCFToolError(
                            f"Input VCF already declares reserved INFO tag {SOURCE_RECORD_TAG}."
                        )
                    headers.append(line)
                    if line.startswith("#CHROM\t"):
                        sample_count = max(0, len(line.split("\t")) - 9)
                    continue
                fields = line.split("\t")
                if len(fields) < 8:
                    raise VCFToolError("Cannot route malformed VCF record with fewer than 8 columns.")
                source_record_index += 1
                alts = fields[4].split(",")
                if alts == ["."]:
                    counts["reference_only"] += 1
                    record_exclusion(line, "NO_ALTERNATE_ALLELE", "REFERENCE_ONLY_RECORDS")
                    continue
                try:
                    position = int(fields[1])
                except ValueError as exc:
                    raise VCFToolError("Cannot route VCF record with a non-integer POS.") from exc
                if position == 0:
                    emit("telomere", line)
                    record_exclusion(line, "VCF_TELOMERE_COORDINATE_UNSUPPORTED", "TELOMERE_COORDINATE_RECORDS")
                    continue
                if position == coordinate_lengths.get(fields[0], -2) + 1:
                    emit("telomere_after", line)
                    record_exclusion(line, "VCF_TELOMERE_COORDINATE_UNSUPPORTED", "TELOMERE_AFTER_CONTIG_RECORDS")
                    continue
                wildcard_indexes = {i + 1 for i, alt in enumerate(alts) if alt in GVCF_WILDCARD_ALLELES}
                if any(alt == "*" for alt in alts):
                    emit("spanning_deletions", line)
                    record_exclusion(line, "SPANNING_DELETION_NOT_INTERPRETED", "SPANNING_DELETION_RECORDS")
                    continue
                is_structural = any(
                    alt not in GVCF_WILDCARD_ALLELES and
                    (alt.startswith("<") or "[" in alt or "]" in alt)
                    for alt in alts
                )
                if is_structural:
                    emit("structural", line)
                    record_exclusion(line, "STRUCTURAL_VARIANT_INTERPRETATION_UNSUPPORTED", "STRUCTURAL_VARIANT_RECORDS")
                    continue
                if wildcard_indexes:
                    concrete_alts = [alt for alt in alts if alt not in GVCF_WILDCARD_ALLELES]
                    if not concrete_alts:
                        emit("gvcf_blocks", line)
                        record_exclusion(line, "GVCF_REFERENCE_CONFIDENCE_ANALYSIS_UNSUPPORTED", "GVCF_REFERENCE_BLOCKS")
                        continue
                    format_keys = fields[8].split(":") if len(fields) > 8 else []
                    gt_index = format_keys.index("GT") if "GT" in format_keys else None
                    fully_unseen = sample_count > 0 and gt_index is not None
                    if fully_unseen:
                        for sample in fields[9:]:
                            sample_values = sample.split(":")
                            if gt_index >= len(sample_values):
                                fully_unseen = False
                                break
                            gt = sample_values[gt_index]
                            if gt in {".", "./.", ".|."}:
                                fully_unseen = False
                                break
                            for allele in re.split(r"[/|]", gt):
                                if allele == ".":
                                    fully_unseen = False
                                    break
                                try:
                                    if int(allele) in wildcard_indexes:
                                        fully_unseen = False
                                        break
                                except ValueError:
                                    fully_unseen = False
                                    break
                            if not fully_unseen:
                                break
                    if fully_unseen:
                        emit("sequence", line)
                        record_reference_genotype_exclusions(line, fields, alts)
                    else:
                        emit("gvcf_unresolved", line)
                        record_exclusion(line, "GVCF_VARIANT_ALLELE_UNRESOLVED", "UNRESOLVED_GVCF_VARIANTS")
                    continue
                emit("sequence", line)
                record_reference_genotype_exclusions(line, fields, alts)
    record_disposition_counts = {
        "sequence": counts["sequence"],
        "gvcf_reference_blocks": counts["gvcf_blocks"],
        "gvcf_unresolved_variants": counts["gvcf_unresolved"],
        "structural_variants": counts["structural"],
        "spanning_deletions": counts["spanning_deletions"],
        "telomere_coordinates": counts["telomere"],
        "after_contig_coordinates": counts["telomere_after"],
        "reference_only": counts["reference_only"],
    }
    routed_record_count = sum(record_disposition_counts.values())
    if routed_record_count != source_record_index:
        raise VCFToolError(
            "VCF routing record reconciliation failed: "
            f"source_records={source_record_index}, routed_records={routed_record_count}, "
            f"dispositions={record_disposition_counts!r}"
        )

    return {
        "routing_version": "2",
        "source_record_count": source_record_index,
        "records_total": routed_record_count,
        "record_reconciliation": {
            "method": "SOURCE_RECORD_INDEX_VS_EXCLUSIVE_ROUTING_DISPOSITIONS",
            "source_records": source_record_index,
            "routed_records": routed_record_count,
            "delta": source_record_index - routed_record_count,
            "balanced": source_record_index == routed_record_count,
            "disposition_counts": record_disposition_counts,
        },
        "excluded_source_record_count": len(excluded_source_record_indexes),
        "sequence_records": counts["sequence"],
        "reference_only_records": counts["reference_only"],
        "gvcf_reference_blocks": counts["gvcf_blocks"],
        "gvcf_unresolved_variant_records": counts["gvcf_unresolved"],
        "structural_variant_records": counts["structural"],
        "spanning_deletion_records": counts["spanning_deletions"],
        "telomere_records": counts["telomere"],
        "telomere_after_contig_records": counts["telomere_after"],
        "reference_only_genotype_alleles": counts["reference_only_genotype_alleles"],
        "exclusion_manifest_path": str(names["exclusions"]) if exclusion_handle is not None else None,
        "exclusion_manifest_records": sum(counts[key] for key in (
            "reference_only", "gvcf_blocks", "gvcf_unresolved", "structural",
            "spanning_deletions", "telomere", "telomere_after",
            "reference_only_genotype_alleles",
        )),
        "sequence_path": str(names["sequence"]) if counts["sequence"] else None,
        "gvcf_blocks_path": str(names["gvcf_blocks"]) if counts["gvcf_blocks"] else None,
        "gvcf_unresolved_path": str(names["gvcf_unresolved"]) if counts["gvcf_unresolved"] else None,
        "structural_path": str(names["structural"]) if counts["structural"] else None,
        "spanning_deletions_path": str(names["spanning_deletions"]) if counts["spanning_deletions"] else None,
        "telomere_path": str(names["telomere"]) if counts["telomere"] else None,
        "telomere_after_contig_path": str(names["telomere_after"]) if counts["telomere_after"] else None,
        "gvcf_wildcard_policy": "BCFTOOLS_VIEW_TRIM_UNSEEN_AT_VARIANT_SITES",
    }


MNV_POLICY = "PRESERVE"
MULTIALLELIC_POLICY = "SPLIT_WITH_BCFTOOLS"
MULTIALLELIC_OVERLAP_POLICY = "MISSING_OTHER_ALT"
ORIGINAL_RECORD_TAG = "SIRALOOM_ORIG"
SOURCE_GT_FORMAT_TAG = "SIRALOOM_SOURCE_GT"
SOURCE_ALT_COUNT_FORMAT_TAG = "SIRALOOM_SOURCE_ALT_COUNT"


class VCFToolError(RuntimeError):
    pass


def bcftools_available() -> bool:
    return shutil.which("bcftools") is not None


def has_multiallelic_records(path: str | Path) -> bool:
    import gzip

    p = Path(path)
    opener = gzip.open if p.name.lower().endswith((".gz", ".bgz")) else open
    with opener(p, "rt", encoding="utf-8-sig") as fh:
        for line in fh:
            if not line or line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) >= 5 and "," in fields[4]:
                return True
    return False


def split_multiallelic_vcf(input_path: str | Path, output_path: str | Path) -> dict:
    """
    Split multiallelic records into biallelic records without doing reference-aware
    normalization. bcftools performs genotype/allele bookkeeping; SIRALOOM's
    Ensembl-backed normalizer remains responsible for reference validation and
    left-alignment.

    This deliberately does not use -f: bcftools requires a local FASTA for
    reference-aware normalization, while SIRALOOM currently uses Ensembl REST.
    """
    if not bcftools_available():
        raise VCFToolError(
            "bcftools is required to split multiallelic VCF records in the deployed "
            "normalization pipeline."
        )

    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "bcftools", "norm", "--no-version", "-m", "-any", "-N", "-Ov",
        "--multi-overlaps", ".",
        "-o", str(output_path), str(input_path),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown bcftools error").strip()
        raise VCFToolError(f"bcftools could not split the multiallelic VCF: {detail}")

    return {
        "tool": "bcftools",
        "operation": "split_multiallelic",
        "command": " ".join(command),
        "multiallelic_mode": MULTIALLELIC_POLICY,
        "multiallelic_overlap_policy": MULTIALLELIC_OVERLAP_POLICY,
        "stderr": (completed.stderr or "").strip(),
    }



def _validate_csi_index_record_counts(
    vcf_path: Path,
    *,
    bcftools_executable: str,
    timeout_seconds: int,
) -> dict:
    """Verify indexed per-contig record streams against the staged BGZF file.

    Per-contig counts alone cannot detect an index whose offsets resolve to
    different records with the same count. This check compares SHA-256 digests
    of the exact record-line streams returned by indexed BCFtools queries with
    sequential BGZF scans. Query output is streamed to temporary files so
    WES/WGS-scale VCFs are not accumulated in process memory.
    """
    try:
        stats = subprocess.run(
            [bcftools_executable, "index", "--stats", str(vcf_path)],
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_seconds)),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise VCFToolError("Timed out while validating CSI index record counts.") from exc
    except OSError as exc:
        raise VCFToolError(f"Unable to execute CSI index validation: {exc}") from exc

    if stats.returncode != 0:
        detail = (stats.stderr or stats.stdout or "unknown CSI index statistics error").strip()
        raise VCFToolError(f"CSI index record-count validation failed: {detail}")

    indexed_counts: dict[str, int] = {}
    for line in (stats.stdout or "").splitlines():
        fields = line.split("\t")
        if len(fields) != 3:
            raise VCFToolError("CSI index statistics returned a malformed contig row.")
        contig, contig_length, record_count = fields
        if contig_length != ".":
            try:
                parsed_length = int(contig_length)
            except ValueError as exc:
                raise VCFToolError("CSI index statistics returned an invalid contig length.") from exc
            if parsed_length < 0:
                raise VCFToolError("CSI index statistics returned an invalid contig length.")
        try:
            count = int(record_count)
        except ValueError as exc:
            raise VCFToolError("CSI index statistics returned a non-integer record count.") from exc
        if not contig or count < 0 or contig in indexed_counts:
            raise VCFToolError("CSI index statistics returned invalid or duplicate contig counts.")
        indexed_counts[contig] = count

    sequential: dict[str, dict[str, object]] = {}
    try:
        with gzip.open(vcf_path, "rt", encoding="utf-8", newline="") as handle:
            for line in handle:
                if not line or line.startswith("#"):
                    continue
                contig = line.split("\t", 1)[0]
                if not contig:
                    raise VCFToolError("Sequential VCF scan found a record with an empty contig.")
                state = sequential.setdefault(contig, {"count": 0, "digest": hashlib.sha256()})
                state["count"] = int(state["count"]) + 1
                state["digest"].update(line.encode("utf-8"))
    except (OSError, EOFError, UnicodeDecodeError) as exc:
        raise VCFToolError(f"Cannot read staged BGZF VCF for index concordance: {exc}") from exc

    sequential_counts = {contig: int(state["count"]) for contig, state in sequential.items()}
    if indexed_counts != sequential_counts:
        raise VCFToolError(
            "CSI index and staged VCF record counts disagree by contig: "
            f"index={indexed_counts!r}, sequential={sequential_counts!r}"
        )

    indexed_digests: dict[str, str] = {}
    for contig in sorted(sequential):
        with tempfile.TemporaryFile(mode="w+b") as query_output, tempfile.TemporaryFile(mode="w+b") as query_error:
            try:
                queried = subprocess.run(
                    [
                        bcftools_executable,
                        "view",
                        "--no-header",
                        "--regions-overlap",
                        "0",
                        "--regions",
                        contig,
                        str(vcf_path),
                    ],
                    stdout=query_output,
                    stderr=query_error,
                    timeout=max(1, int(timeout_seconds)),
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise VCFToolError(
                    f"Timed out while querying CSI-indexed records for contig {contig!r}."
                ) from exc
            except OSError as exc:
                raise VCFToolError(
                    f"Unable to execute CSI-indexed query for contig {contig!r}: {exc}"
                ) from exc
            if queried.returncode != 0:
                query_error.seek(0)
                detail = query_error.read().decode("utf-8", errors="replace").strip()
                raise VCFToolError(
                    f"CSI-indexed record query failed for contig {contig!r}: "
                    f"{detail or 'unknown bcftools view error'}"
                )

            query_output.seek(0)
            digest = hashlib.sha256()
            count = 0
            for raw_line in query_output:
                if not raw_line or raw_line.startswith(b"#"):
                    continue
                fields = raw_line.split(b"\t", 1)
                if not fields or fields[0].decode("utf-8", errors="replace") != contig:
                    raise VCFToolError(
                        f"CSI-indexed query for contig {contig!r} returned a record from another contig."
                    )
                digest.update(raw_line)
                count += 1
            if count != sequential_counts[contig]:
                raise VCFToolError(
                    f"CSI-indexed query count mismatch for contig {contig!r}: "
                    f"indexed={count}, sequential={sequential_counts[contig]}."
                )
            expected_digest = sequential[contig]["digest"].hexdigest()
            actual_digest = digest.hexdigest()
            if actual_digest != expected_digest:
                raise VCFToolError(
                    f"CSI-indexed query records disagree with the sequential VCF stream for contig {contig!r}."
                )
            indexed_digests[contig] = actual_digest

    return {
        "method": "CSI_INDEXED_QUERY_SHA256_VS_SEQUENTIAL_BGZF_SCAN",
        "records": sum(sequential_counts.values()),
        "contigs": len(sequential_counts),
        "indexed_query_contigs_verified": len(indexed_digests),
        "indexed_query_records_verified": sum(sequential_counts.values()),
    }

def _validate_source_child_reconciliation(source_path: Path, normalized_path: Path) -> dict:
    """Validate one-to-one source-ALT mapping for normalized sequence children.

    The router embeds an immutable source-record payload in SIRALOOM_SOURCE.
    BCFtools' SIRALOOM_ORIG tag identifies the selected ALT in the prepared
    pre-normalization record. These two tags are reconciled so wildcard trimming
    cannot silently shift source ALT indexes.
    """
    def open_text(path: Path):
        return gzip.open(path, "rt", encoding="utf-8-sig") if path.name.lower().endswith((".gz", ".bgz")) else path.open("r", encoding="utf-8-sig")

    def info_tag(fields: list[str], tag: str) -> str | None:
        values = [
            item[len(tag) + 1:]
            for item in fields[7].split(";")
            if item.startswith(tag + "=")
        ]
        if len(values) > 1:
            raise VCFToolError(f"Record contains duplicate {tag} INFO tags.")
        return values[0] if values else None

    def decode_source_payload(value: str) -> dict:
        try:
            padded = value + ("=" * (-len(value) % 4))
            payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VCFToolError("SIRALOOM_SOURCE contains an invalid source payload.") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != "1":
            raise VCFToolError("SIRALOOM_SOURCE payload has an unsupported schema.")
        return payload

    source_header = None
    with open_text(source_path) as handle:
        for raw in handle:
            line = raw.rstrip("\r\n")
            if line.startswith("##INFO=<ID=SIRALOOM_SOURCE,"):
                source_header = line
                break
            if line.startswith("#CHROM\t"):
                break
    if source_header is None:
        with open_text(source_path) as handle:
            for raw in handle:
                line = raw.rstrip("\r\n")
                if not line.startswith("#") and "SIRALOOM_SOURCE=" in line:
                    raise VCFToolError(
                        "SIRALOOM_SOURCE record tag is present without its header definition."
                    )
        return {
            "status": "NOT_PROVIDED",
            "method": "SIRALOOM_SOURCE_TAG_ABSENT",
            "source_records": None,
            "expected_child_records": None,
            "normalized_child_records": None,
            "balanced": None,
        }
    if source_header != SOURCE_RECORD_TAG_HEADER:
        raise VCFToolError("SIRALOOM_SOURCE header does not match the SIRALOOM contract.")

    expected: dict[int, dict] = {}
    with open_text(source_path) as handle:
        for raw in handle:
            line = raw.rstrip("\r\n")
            if line.startswith("##INFO=<ID=SIRALOOM_SOURCE,"):
                continue
            if line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 8:
                raise VCFToolError("Source-mapped VCF contains a malformed record.")
            value = info_tag(fields, SOURCE_RECORD_TAG)
            if value is None:
                raise VCFToolError("Source-mapped VCF record is missing SIRALOOM_SOURCE.")
            payload = decode_source_payload(value)
            try:
                source_index = int(payload["source_record_index"])
                source_alt_count = int(payload["source_alt_count"])
                expected_indexes = payload["normalized_alt_source_indexes"]
                source_hash = payload["source_record_sha256"]
            except (KeyError, TypeError, ValueError) as exc:
                raise VCFToolError("SIRALOOM_SOURCE payload is missing required source identity fields.") from exc
            if (
                source_index < 1
                or source_alt_count != len(fields[4].split(","))
                or not isinstance(expected_indexes, list)
                or not all(isinstance(index, int) and not isinstance(index, bool) for index in expected_indexes)
                or not re.fullmatch(r"[0-9a-f]{64}", str(source_hash))
            ):
                raise VCFToolError("SIRALOOM_SOURCE payload does not match its source VCF record.")
            source_alts = fields[4].split(",")
            actual_indexes = [
                index
                for index, alternate in enumerate(source_alts, start=1)
                if alternate not in GVCF_WILDCARD_ALLELES
            ]
            if expected_indexes != actual_indexes or not actual_indexes:
                raise VCFToolError("SIRALOOM_SOURCE ALT-index mapping is inconsistent with source alleles.")
            if source_index in expected:
                raise VCFToolError("SIRALOOM_SOURCE contains a duplicate source record index.")
            info_items = fields[7].split(";")
            if not info_items[-1].startswith(SOURCE_RECORD_TAG + "="):
                raise VCFToolError("SIRALOOM_SOURCE must be the final INFO field for integrity verification.")
            original_info_items = info_items[:-1]
            fields[7] = ";".join(original_info_items) if original_info_items else "."
            original_record = "\t".join(fields)
            if hashlib.sha256(original_record.encode("utf-8")).hexdigest() != source_hash:
                raise VCFToolError("SIRALOOM_SOURCE source-record SHA-256 does not match the original record.")
            expected[source_index] = {
                "payload": payload,
                "alt_indexes": actual_indexes,
                "prepared_alt_values": [source_alts[index - 1] for index in actual_indexes],
            }

    if not expected:
        raise VCFToolError("Source-to-normalized reconciliation requires tagged source records.")

    observed: set[tuple[int, int]] = set()
    normalized_count = 0
    with open_text(normalized_path) as handle:
        for raw in handle:
            line = raw.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 8:
                raise VCFToolError("Normalized VCF contains a malformed record during source reconciliation.")
            source_value = info_tag(fields, SOURCE_RECORD_TAG)
            original_value = info_tag(fields, ORIGINAL_RECORD_TAG)
            if source_value is None or original_value is None:
                raise VCFToolError("Normalized child is missing required source ALT mapping tags.")
            payload = decode_source_payload(source_value)
            try:
                source_index = int(payload["source_record_index"])
            except (KeyError, TypeError, ValueError) as exc:
                raise VCFToolError("Normalized child has an invalid source record index.") from exc
            source = expected.get(source_index)
            if source is None or payload != source["payload"]:
                raise VCFToolError("Normalized child source identity does not match the routed source record.")
            try:
                original_fields = original_value.split("|", 4)
                if len(original_fields) != 5:
                    raise ValueError("expected five source mapping fields")
                prepared_alts = original_fields[3].split(",")
                used_alt_index = int(original_fields[4])
                if (
                    prepared_alts != source["prepared_alt_values"]
                    or used_alt_index < 1
                    or used_alt_index > len(prepared_alts)
                ):
                    raise ValueError("ALT index or prepared ALT list disagrees with source mapping")
            except ValueError as exc:
                raise VCFToolError("SIRALOOM_ORIG contains an invalid source ALT mapping.") from exc
            mapping = (source_index, source["alt_indexes"][used_alt_index - 1])
            if mapping in observed:
                raise VCFToolError("Multiple normalized children map to the same source ALT.")
            observed.add(mapping)
            normalized_count += 1

    expected_mappings = {
        (source_index, alt_index)
        for source_index, source in expected.items()
        for alt_index in source["alt_indexes"]
    }
    if observed != expected_mappings:
        missing = sorted(expected_mappings - observed)
        unexpected = sorted(observed - expected_mappings)
        raise VCFToolError(
            "Source-to-normalized ALT reconciliation failed: "
            f"missing={missing!r}, unexpected={unexpected!r}"
        )

    return {
        "status": "VALIDATED",
        "method": "IMMUTABLE_SOURCE_PAYLOAD_VS_BCFTOOLS_OLD_RECORD_ALT_MAPPING",
        "source_records": len(expected),
        "expected_child_records": len(expected_mappings),
        "normalized_child_records": normalized_count,
        "source_alt_mappings": len(observed),
        "balanced": True,
    }


@lru_cache(maxsize=64)
def _sha256_file_cached(
    path_string: str,
    device: int,
    inode: int,
    size_bytes: int,
    mtime_ns: int,
    ctime_ns: int,
) -> str:
    """Cache a digest only for one exact filesystem identity."""
    path = Path(path_string)
    before = path.stat()
    before_identity = (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns
    )
    if before_identity != (device, inode, size_bytes, mtime_ns, ctime_ns):
        raise VCFToolError(f"Reference artifact changed before hashing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    after_identity = (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
    )
    if after_identity != before_identity:
        raise VCFToolError(f"Reference artifact changed while hashing: {path}")
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    """Hash a reference artifact, caching only while its filesystem identity is unchanged."""
    resolved = path.resolve()
    stat = resolved.stat()
    return _sha256_file_cached(
        str(resolved),
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )


def _reference_artifact_identity(reference_fasta: Path) -> dict:
    """Attest the exact FASTA and index files used for normalization."""
    artifacts = {
        "fasta": reference_fasta,
        "fai": Path(str(reference_fasta) + ".fai"),
    }
    if reference_fasta.name.lower().endswith((".gz", ".bgz")):
        artifacts["gzi"] = Path(str(reference_fasta) + ".gzi")

    identity_artifacts: dict[str, dict] = {}
    for role, artifact_path in artifacts.items():
        if not artifact_path.is_file():
            sidecar = "FASTA index" if role == "fai" else "BGZF FASTA index" if role == "gzi" else "reference FASTA"
            raise VCFToolError(
                f"Required {sidecar} artifact is missing or empty: {artifact_path}"
            )
        try:
            before = artifact_path.stat()
            if before.st_size <= 0:
                sidecar = "FASTA index" if role == "fai" else "BGZF FASTA index" if role == "gzi" else "reference FASTA"
                raise VCFToolError(
                    f"Required {sidecar} artifact is missing or empty: {artifact_path}"
                )
            digest = _sha256_file(artifact_path)
            after = artifact_path.stat()
        except OSError as exc:
            raise VCFToolError(f"Unable to attest reference artifact {artifact_path}: {exc}") from exc
        if (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns
        ) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
        ):
            raise VCFToolError(f"Reference artifact changed while being attested: {artifact_path}")
        identity_artifacts[role] = {
            "path": str(artifact_path.resolve()),
            "size_bytes": after.st_size,
            "sha256": digest,
        }
    return {
        "method": "SHA256_REFERENCE_FASTA_AND_INDEX_ARTIFACTS",
        "artifacts": identity_artifacts,
    }


def _strip_vcf45_number_m_format_fields(
    source_vcf_path: Path,
    normalized_path: Path,
    destination_path: Path,
) -> list[str]:
    """Remove Number=M FORMAT values from the per-ALT artifact.

    BCFtools 1.24 preserves Number=M values when splitting a multiallelic
    record, although the emitted GT and ALT representation changes. Those
    values are therefore not safe to publish as if they described each
    normalized child. The immutable source VCF remains authoritative; this
    transform removes Number=M values and their header declarations from the
    derived small-variant artifact and records the source-only policy.
    """
    source_opener = gzip.open if source_vcf_path.name.lower().endswith((".gz", ".bgz")) else open
    try:
        with source_opener(source_vcf_path, "rt", encoding="utf-8-sig") as header_handle:
            source_fileformat_header = header_handle.readline().rstrip("\r\n")
    except OSError as exc:
        raise VCFToolError(f"Unable to inspect source VCF fileformat before Number=M handling: {exc}") from exc
    if source_fileformat_header != "##fileformat=VCFv4.5":
        return []

    source_opener = gzip.open if normalized_path.name.lower().endswith((".gz", ".bgz")) else open

    source_only_fields: set[str] = set()
    fileformat: str | None = None
    policy_line = (
        "##SIRALOOM_SOURCE_ONLY_FORMAT_FIELDS_POLICY="
        "VCFv4.5_Number_M_fields_are_retained_in_immutable_source_VCF_and_omitted_from_normalized_small_variant_artifact"
    )

    try:
        with source_opener(normalized_path, "rt", encoding="utf-8-sig") as input_handle, destination_path.open(
            "w", encoding="utf-8", newline=""
        ) as output_handle:
            for line_no, raw in enumerate(input_handle, 1):
                line = raw.rstrip("\r\n")
                if line.startswith("##fileformat="):
                    fileformat = line.split("=", 1)[1]
                if line.startswith("##FORMAT="):
                    try:
                        identifier, definition = _parse_field_definition(
                            line, "FORMAT", line_no, "VCFv4.5"
                        )
                    except StrictVCFValidationError as exc:
                        raise VCFToolError(
                            f"Cannot inspect VCFv4.5 FORMAT definition at line {line_no}: {exc}"
                        ) from exc
                    if definition["Number"] == "M":
                        source_only_fields.add(identifier)
                        continue
                if line.startswith("#CHROM"):
                    if fileformat == "VCFv4.5":
                        output_handle.write(policy_line + "\n")
                    output_handle.write(line + "\n")
                    continue
                if line.startswith("#"):
                    output_handle.write(line + "\n")
                    continue

                fields = line.split("\t")
                if len(fields) >= 10:
                    format_keys = fields[8].split(":")
                    implicit_fields = {
                        key
                        for key in format_keys
                        if _base_modification_field_kind(key) is not None
                    }
                    source_only_fields.update(implicit_fields)
                    removed_fields = {
                        key for key in format_keys if key in source_only_fields
                    }
                    if removed_fields:
                        retained_indexes = [
                            index
                            for index, key in enumerate(format_keys)
                            if key not in removed_fields
                        ]
                        retained_keys = [
                            key for key in format_keys if key not in removed_fields
                        ]
                        fields[8] = ":".join(retained_keys) if retained_keys else "."
                        for sample_index in range(9, len(fields)):
                            sample_values = fields[sample_index].split(":")
                            retained_values = [
                                sample_values[index] if index < len(sample_values) else "."
                                for index in retained_indexes
                            ]
                            fields[sample_index] = (
                                ":".join(retained_values) if retained_values else "."
                            )
                output_handle.write("\t".join(fields) + "\n")
    except OSError as exc:
        raise VCFToolError(
            f"Unable to create source-only Number=M normalized VCF: {exc}"
        ) from exc

    if fileformat != "VCFv4.5" or not source_only_fields:
        destination_path.unlink(missing_ok=True)
        return []
    return sorted(source_only_fields)


def normalize_vcf_with_bcftools(
    input_path: str | Path,
    output_path: str | Path,
    *,
    reference_fasta: str | Path,
    expected_bcftools_version: str | None = None,
    timeout_seconds: int = 1800,
    preserve_existing_source_mapping: bool = False,
    bcftools_executable: str = "bcftools",
) -> dict:
    """Normalize, sort, and CSI-index a VCF before publishing either output.

    All expensive work occurs in a private directory on the destination
    filesystem. Existing output and index files remain untouched until
    normalization, sorting, and indexing have all succeeded.
    """
    executable_available = (
        bcftools_available()
        if bcftools_executable == "bcftools"
        else Path(bcftools_executable).is_file() or shutil.which(bcftools_executable) is not None
    )
    if not executable_available:
        raise VCFToolError("bcftools is required for SIRALOOM reference-aware VCF normalization.")
    input_path = Path(input_path)
    output_path = Path(output_path)
    reference_fasta = Path(reference_fasta)
    if not input_path.is_file():
        raise VCFToolError(f"VCF input does not exist: {input_path}")
    if not reference_fasta.is_file():
        raise VCFToolError(f"Reference FASTA does not exist: {reference_fasta}")
    reference_identity_before = _reference_artifact_identity(reference_fasta)
    if output_path.suffixes[-2:] != [".vcf", ".gz"]:
        raise VCFToolError("Canonical normalized VCF output must use the .vcf.gz filename extension.")
    has_existing_source_mapping = _reject_original_record_tag_collision(
        input_path, allow_existing=preserve_existing_source_mapping
    )
    if has_existing_source_mapping:
        _validate_existing_source_genotype_fields(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    index_path = Path(str(output_path) + ".csi")

    try:
        version_result = subprocess.run(
            [bcftools_executable, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise VCFToolError("Timed out while checking the bcftools version.") from exc
    except OSError as exc:
        raise VCFToolError(f"Unable to execute bcftools: {exc}") from exc
    if version_result.returncode != 0:
        detail = (version_result.stderr or version_result.stdout or "unknown bcftools error").strip()
        raise VCFToolError(f"Unable to determine bcftools version: {detail}")
    version_line = next((line.strip() for line in version_result.stdout.splitlines() if line.strip()), "unknown")
    detected_version = version_line.split()[1] if len(version_line.split()) > 1 and version_line.split()[0] == "bcftools" else None
    if expected_bcftools_version and detected_version != expected_bcftools_version:
        raise VCFToolError(f"bcftools version mismatch: expected {expected_bcftools_version}, found {detected_version or version_line}")

    timeout = max(1, int(timeout_seconds))
    with tempfile.TemporaryDirectory(
        prefix=f".{output_path.name}.siraloom-",
        dir=str(output_path.parent),
    ) as work_dir:
        work = Path(work_dir)
        normalized_path = work / "normalized.vcf.gz"
        sorted_path = work / "sorted.vcf.gz"
        staged_index_path = Path(str(sorted_path) + ".csi")
        normalized_stderr = ""
        view_stderr = ""
        sorted_stderr = ""
        indexed_stderr = ""

        # ``view -A`` is available in the pinned 1.24 release. The router only
        # places records here when the GVCF wildcard is provably uncalled.
        prepared_path = work / "prepared.vcf.gz"
        view_command = [
            bcftools_executable, "view", "--no-version", "-A", "-Oz",
            "-o", str(prepared_path), str(input_path),
        ]
        try:
            viewed = subprocess.run(
                view_command, capture_output=True, text=True, timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise VCFToolError(f"bcftools GVCF wildcard preparation timed out after {timeout}s.") from exc
        except OSError as exc:
            raise VCFToolError(f"Unable to execute bcftools GVCF wildcard preparation: {exc}") from exc
        view_stderr = (viewed.stderr or "").strip()
        if viewed.returncode != 0:
            detail = (viewed.stderr or viewed.stdout or "unknown bcftools view error").strip()
            raise VCFToolError(f"bcftools could not remove unseen GVCF wildcard alleles: {detail}")
        if not prepared_path.is_file() or prepared_path.stat().st_size == 0:
            raise VCFToolError("bcftools reported success but produced no prepared VCF.")

        provenance_input = prepared_path
        header_injection = None
        if not has_existing_source_mapping:
            provenance_input = work / "provenance-input.vcf"
            header_injection = _write_original_record_info_header(prepared_path, provenance_input)

        normalize_command = [
            bcftools_executable, "norm", "--no-version", "-f", str(reference_fasta), "-c", "e",
            "-m", "-any", "--multi-overlaps", ".",
            *( [] if has_existing_source_mapping else ["--old-rec-tag", ORIGINAL_RECORD_TAG] ),
            "-Oz", "-o", str(normalized_path), str(provenance_input),
        ]
        try:
            completed = subprocess.run(
                normalize_command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise VCFToolError(f"bcftools reference-aware normalization timed out after {timeout}s.") from exc
        except OSError as exc:
            raise VCFToolError(f"Unable to execute bcftools normalization: {exc}") from exc
        normalized_stderr = (completed.stderr or "").strip()
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown bcftools normalization error").strip()
            raise VCFToolError(f"bcftools reference-aware normalization failed (exit {completed.returncode}): {detail}")
        if not normalized_path.is_file() or normalized_path.stat().st_size == 0:
            raise VCFToolError("bcftools reported success but produced no normalized VCF.")

        sort_command = [
            bcftools_executable, "sort", "-Oz", "-o", str(sorted_path),
            str(normalized_path),
        ]
        try:
            sorted_result = subprocess.run(
                sort_command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise VCFToolError(f"bcftools sorting timed out after {timeout}s.") from exc
        except OSError as exc:
            raise VCFToolError(f"Unable to execute bcftools sorting: {exc}") from exc
        sorted_stderr = (sorted_result.stderr or "").strip()
        if sorted_result.returncode != 0:
            detail = (sorted_result.stderr or sorted_result.stdout or "unknown bcftools sort error").strip()
            raise VCFToolError(f"bcftools sorting of normalized VCF failed (exit {sorted_result.returncode}): {detail}")
        if not sorted_path.is_file() or sorted_path.stat().st_size == 0:
            raise VCFToolError("bcftools reported success but produced no sorted VCF.")

        source_only_plain_path = work / "source-only-format-fields.vcf"
        source_only_compressed_path = work / "source-only-format-fields.vcf.gz"
        source_only_format_fields = _strip_vcf45_number_m_format_fields(
            input_path, sorted_path, source_only_plain_path
        )
        source_only_stderr = ""
        source_only_command: list[str] = []
        if source_only_format_fields:
            source_only_command = [
                bcftools_executable,
                "view",
                "--no-version",
                "-Oz",
                "-o",
                str(source_only_compressed_path),
                str(source_only_plain_path),
            ]
            try:
                source_only_result = subprocess.run(
                    source_only_command,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise VCFToolError(
                    f"bcftools compression of source-only FORMAT output timed out after {timeout}s."
                ) from exc
            except OSError as exc:
                raise VCFToolError(
                    f"Unable to execute bcftools compression of source-only FORMAT output: {exc}"
                ) from exc
            source_only_stderr = (source_only_result.stderr or "").strip()
            if source_only_result.returncode != 0:
                detail = (
                    source_only_result.stderr
                    or source_only_result.stdout
                    or "unknown bcftools view error"
                ).strip()
                raise VCFToolError(
                    f"bcftools could not compress source-only FORMAT output: {detail}"
                )
            if not source_only_compressed_path.is_file() or source_only_compressed_path.stat().st_size == 0:
                raise VCFToolError(
                    "bcftools reported success but produced no source-only normalized VCF."
                )
            os.replace(source_only_compressed_path, sorted_path)

        reference_identity_after = _reference_artifact_identity(reference_fasta)
        if reference_identity_after != reference_identity_before:
            raise VCFToolError(
                "Reference FASTA or index artifacts changed during normalization; staged outputs will not be published."
            )

        source_child_reconciliation = _validate_source_child_reconciliation(
            input_path, sorted_path
        )

        index_command = [bcftools_executable, "index", "--csi", "--force", str(sorted_path)]
        try:
            indexed_result = subprocess.run(
                index_command,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise VCFToolError("bcftools CSI indexing timed out after 120s.") from exc
        except OSError as exc:
            raise VCFToolError(f"Unable to execute bcftools CSI indexing: {exc}") from exc
        indexed_stderr = (indexed_result.stderr or "").strip()
        if indexed_result.returncode != 0:
            detail = (indexed_result.stderr or indexed_result.stdout or "unknown bcftools index error").strip()
            raise VCFToolError(f"bcftools CSI indexing failed (exit {indexed_result.returncode}): {detail}")
        if not staged_index_path.is_file() or staged_index_path.stat().st_size == 0:
            raise VCFToolError("bcftools reported success but produced no CSI index.")

        index_validation = _validate_csi_index_record_counts(
            sorted_path,
            bcftools_executable=bcftools_executable,
            timeout_seconds=120,
        )

        # Flush staged files before publication. The private directory is on the
        # destination filesystem, so os.replace avoids cross-device partial copies.
        for staged in (sorted_path, staged_index_path):
            with staged.open("rb") as handle:
                os.fsync(handle.fileno())

        output_backup = work / "previous.vcf.gz"
        index_backup = work / "previous.vcf.gz.csi"
        moved_old_output = False
        moved_old_index = False
        published_output = False
        published_index = False
        try:
            if output_path.exists():
                os.replace(output_path, output_backup)
                moved_old_output = True
            if index_path.exists():
                os.replace(index_path, index_backup)
                moved_old_index = True

            os.replace(sorted_path, output_path)
            published_output = True
            os.replace(staged_index_path, index_path)
            published_index = True
        except BaseException:
            if published_output:
                output_path.unlink(missing_ok=True)
            if published_index:
                index_path.unlink(missing_ok=True)
            if moved_old_output and output_backup.exists():
                os.replace(output_backup, output_path)
            if moved_old_index and index_backup.exists():
                os.replace(index_backup, index_path)
            raise

        return {
            "tool": "bcftools",
            "tool_version": version_line,
            "expected_tool_version": expected_bcftools_version,
            "operation": "reference_aware_normalization_sort_index",
            "command": " && ".join([
                " ".join(view_command),
                header_injection or "preserve existing SIRALOOM_ORIG mapping",
                " ".join(normalize_command),
                " ".join(sort_command),
                " ".join(source_only_command) if source_only_command else "preserve source fields unchanged",
                " ".join(index_command),
            ]),
            "reference_fasta": str(reference_fasta),
            "reference_identity": reference_identity_before,
            "reference_check": "error",
            "multiallelic_mode": MULTIALLELIC_POLICY,
            "multiallelic_overlap_policy": MULTIALLELIC_OVERLAP_POLICY,
            "source_record_mapping_tag": ORIGINAL_RECORD_TAG,
            "source_record_mapping_policy": "BCFTOOLS_OLD_REC_TAG_SOURCE_ALT_INDEX",
            "mnv_policy": MNV_POLICY,
            "compression": "BGZF",
            "index": "CSI",
            "index_path": str(index_path),
            "index_validation": index_validation,
            "source_child_reconciliation": source_child_reconciliation,
            "source_only_format_fields": source_only_format_fields,
            "source_only_format_fields_policy": (
                "IMMUTABLE_SOURCE_VCF_ONLY" if source_only_format_fields else None
            ),
            "gvcf_wildcard_command": "bcftools view -A",
            "stderr": "\n".join(
                x for x in (
                    view_stderr, normalized_stderr, sorted_stderr,
                    source_only_stderr, indexed_stderr,
                ) if x
            ),
        }


def _write_original_record_info_header(source: Path, destination: Path) -> str:
    """Attach immutable source-GT provenance before BCFtools splits ALT alleles.

    BCFtools rewrites GT when a multiallelic record is split. The selected ALT
    remains in GT and non-selected ALTs become missing under the conservative
    overlap policy. These Number=1 FORMAT fields preserve the pre-split GT and
    original ALT count on every emitted child record.
    """
    opener = gzip.open if source.name.lower().endswith((".gz", ".bgz")) else open
    info_header_line = (
        '##INFO=<ID=SIRALOOM_ORIG,Number=.,Type=String,'
        'Description="Original source record CHROM|POS|REF|ALT|USED_ALT_IDX">\n'
    )
    source_gt_header_line = (
        '##FORMAT=<ID=SIRALOOM_SOURCE_GT,Number=1,Type=String,'
        'Description="Sample GT on routed sequence input before SIRALOOM per-ALT splitting">\n'
    )
    source_alt_count_header_line = (
        '##FORMAT=<ID=SIRALOOM_SOURCE_ALT_COUNT,Number=1,Type=Integer,'
        'Description="Number of ALT alleles in routed sequence input before splitting">\n'
    )
    found_chrom_header = False
    with opener(source, "rt", encoding="utf-8-sig") as input_handle, destination.open(
        "w", encoding="utf-8", newline=""
    ) as output_handle:
        for line in input_handle:
            if line.startswith("#CHROM"):
                output_handle.write(info_header_line)
                output_handle.write(source_gt_header_line)
                output_handle.write(source_alt_count_header_line)
                found_chrom_header = True
                output_handle.write(line)
                continue
            if line.startswith("#"):
                output_handle.write(line)
                continue
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) < 8:
                raise VCFToolError("Cannot add source mapping to a malformed prepared VCF record.")

            alternate_count = len(fields[4].split(","))
            if len(fields) > 9:
                format_keys = [] if fields[8] in {"", "."} else fields[8].split(":")
                if SOURCE_GT_FORMAT_TAG in format_keys or SOURCE_ALT_COUNT_FORMAT_TAG in format_keys:
                    raise VCFToolError("Input VCF uses a reserved SIRALOOM source-genotype FORMAT tag.")
                gt_index = format_keys.index("GT") if "GT" in format_keys else None
                updated_samples: list[str] = []
                for sample_value in fields[9:]:
                    values = [] if sample_value in {"", "."} and not format_keys else sample_value.split(":")
                    if len(values) > len(format_keys):
                        raise VCFToolError("Cannot preserve source GT from a malformed sample FORMAT value.")
                    values.extend(["."] * (len(format_keys) - len(values)))
                    source_gt = values[gt_index] if gt_index is not None else "."
                    values.extend([source_gt, str(alternate_count)])
                    updated_samples.append(":".join(values))
                fields[8] = ":".join([
                    *format_keys,
                    SOURCE_GT_FORMAT_TAG,
                    SOURCE_ALT_COUNT_FORMAT_TAG,
                ])
                fields[9:] = updated_samples

            if alternate_count == 1:
                try:
                    position = int(fields[1])
                except ValueError as exc:
                    raise VCFToolError("Cannot add source mapping to a record with invalid POS.") from exc
                if position < 1:
                    raise VCFToolError("Cannot add source mapping to a record with invalid POS.")
                source_value = f"{fields[0]}|{position}|{fields[3]}|{fields[4]}|1"
                fields[7] = (
                    f"{fields[7]};SIRALOOM_ORIG={source_value}"
                    if fields[7] not in {"", "."}
                    else f"SIRALOOM_ORIG={source_value}"
                )
            output_handle.write("\t".join(fields) + "\n")
    if not found_chrom_header:
        destination.unlink(missing_ok=True)
        raise VCFToolError("Cannot declare source mapping: prepared VCF has no #CHROM header.")
    return (
        "inject reserved SIRALOOM_ORIG source mappings and "
        "SIRALOOM_SOURCE_GT/SIRALOOM_SOURCE_ALT_COUNT FORMAT provenance"
    )


def _validate_existing_source_genotype_fields(input_path: Path) -> None:
    """Reject re-normalization when the immutable source genotype lineage is absent."""
    opener = gzip.open if input_path.name.lower().endswith((".gz", ".bgz")) else open
    definitions: dict[str, str] = {}
    header_columns: int | None = None
    with opener(input_path, "rt", encoding="utf-8-sig") as handle:
        for line in handle:
            if line.startswith("##FORMAT=<ID="):
                tag = line.split("##FORMAT=<ID=", 1)[1].split(",", 1)[0]
                if tag in {SOURCE_GT_FORMAT_TAG, SOURCE_ALT_COUNT_FORMAT_TAG}:
                    definitions[tag] = line.rstrip("\r\n")
            elif line.startswith("#CHROM"):
                header_columns = len(line.rstrip("\r\n").split("\t"))
                break
    expected_definitions = {
        SOURCE_GT_FORMAT_TAG: '##FORMAT=<ID=SIRALOOM_SOURCE_GT,Number=1,Type=String,Description="Sample GT on routed sequence input before SIRALOOM per-ALT splitting">',
        SOURCE_ALT_COUNT_FORMAT_TAG: '##FORMAT=<ID=SIRALOOM_SOURCE_ALT_COUNT,Number=1,Type=Integer,Description="Number of ALT alleles in routed sequence input before splitting">',
    }
    if definitions != expected_definitions:
        raise VCFToolError(
            "Existing normalized VCF lacks the complete SIRALOOM source-genotype provenance contract."
        )
    if header_columns is None:
        raise VCFToolError("Existing source-mapping VCF is missing its #CHROM header.")

    sample_count = max(0, header_columns - 9)
    if sample_count == 0:
        return
    with opener(input_path, "rt", encoding="utf-8-sig") as handle:
        for line in handle:
            if not line or line.startswith("#"):
                continue
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) != header_columns or len(fields) < 10:
                raise VCFToolError("Existing source-genotype VCF has a malformed record.")
            format_keys = fields[8].split(":")
            if SOURCE_GT_FORMAT_TAG not in format_keys or SOURCE_ALT_COUNT_FORMAT_TAG not in format_keys:
                raise VCFToolError("Existing normalized record is missing source-genotype FORMAT fields.")
            mapping_values = [
                item.partition("=")[2]
                for item in fields[7].split(";")
                if item.partition("=")[0] == ORIGINAL_RECORD_TAG
            ]
            if len(mapping_values) != 1:
                raise VCFToolError("Existing normalized record has a missing or duplicate source mapping.")
            mapping = mapping_values[0].split("|", 4)
            if len(mapping) != 5:
                raise VCFToolError("Existing normalized record has a malformed source mapping.")
            gt_index = format_keys.index(SOURCE_GT_FORMAT_TAG)
            count_index = format_keys.index(SOURCE_ALT_COUNT_FORMAT_TAG)
            for sample_value in fields[9:]:
                values = sample_value.split(":")
                if max(gt_index, count_index) >= len(values):
                    raise VCFToolError("Existing normalized sample is missing source-genotype FORMAT values.")
                try:
                    alt_count = int(values[count_index])
                except ValueError as exc:
                    raise VCFToolError("Existing normalized sample has an invalid source ALT count.") from exc
                if alt_count < 1:
                    raise VCFToolError("Existing normalized sample has a non-positive source ALT count.")
                if alt_count != len(mapping[3].split(",")):
                    raise VCFToolError("Existing normalized source ALT count disagrees with its source mapping.")

def _reject_original_record_tag_collision(input_path: Path, *, allow_existing: bool) -> bool:
    opener = gzip.open if input_path.name.lower().endswith((".gz", ".bgz")) else open
    has_definition = False
    has_reserved_source_format_definition = False
    header = None
    with opener(input_path, "rt", encoding="utf-8-sig") as handle:
        for line in handle:
            if line.startswith("#CHROM"):
                header = line
                break
            if line.startswith(f"##INFO=<ID={ORIGINAL_RECORD_TAG},"):
                if not allow_existing:
                    raise VCFToolError(
                        f"Input VCF already declares reserved INFO tag {ORIGINAL_RECORD_TAG}."
                    )
                has_definition = line.startswith(
                    '##INFO=<ID=SIRALOOM_ORIG,Number=.,Type=String,Description="Original source record '
                )
                if not has_definition:
                    raise VCFToolError("Existing source-mapping tag does not match the SIRALOOM mapping contract.")
            if line.startswith(f"##FORMAT=<ID={SOURCE_GT_FORMAT_TAG},") or line.startswith(
                f"##FORMAT=<ID={SOURCE_ALT_COUNT_FORMAT_TAG},"
            ):
                has_reserved_source_format_definition = True
                if not allow_existing:
                    raise VCFToolError("Input VCF already declares a reserved SIRALOOM source-genotype FORMAT tag.")
    if not has_definition:
        if has_reserved_source_format_definition:
            raise VCFToolError(
                "SIRALOOM source-genotype FORMAT fields require a matching SIRALOOM_ORIG source mapping."
            )
        return False

    if header is None:
        raise VCFToolError("Input VCF is missing its #CHROM header.")
    columns = len(header.rstrip("\r\n").split("\t"))
    with opener(input_path, "rt", encoding="utf-8-sig") as handle:
        for line in handle:
            if not line or line.startswith("#"):
                continue
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) != columns or len(fields) < 8:
                raise VCFToolError("Existing source-mapping VCF has a malformed record.")
            tags = [
                item.partition("=")[2]
                for item in fields[7].split(";")
                if item.partition("=")[0] == ORIGINAL_RECORD_TAG
            ]
            if len(tags) != 1:
                raise VCFToolError("Existing source-mapping VCF has a missing or malformed mapping.")
            mapping = tags[0].split("|", 4)
            if len(mapping) not in {4, 5}:
                raise VCFToolError("Existing source-mapping VCF has a missing or malformed mapping.")
            try:
                source_position = int(mapping[1])
                source_alt_index = int(mapping[4]) if len(mapping) == 5 else 1
            except ValueError as exc:
                raise VCFToolError("Existing source-mapping VCF has invalid coordinates or ALT index.") from exc
            source_alternates = mapping[3].split(",")
            if (
                source_position < 1
                or (len(mapping) == 4 and len(source_alternates) != 1)
                or source_alt_index < 1
                or source_alt_index > len(source_alternates)
            ):
                raise VCFToolError("Existing source-mapping VCF has invalid coordinates or ALT index.")
    return True

def classify_records(path: str | Path) -> dict:
    import gzip

    p = Path(path)
    opener = gzip.open if p.name.lower().endswith((".gz", ".bgz")) else open
    multiallelic = 0
    symbolic = 0
    gvcf_markers = 0
    records = 0
    with opener(p, "rt", encoding="utf-8-sig") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 5:
                continue
            records += 1
            alts = fields[4].split(",")
            if len(alts) > 1:
                multiallelic += 1
            if any(
                alt.startswith("<") or alt.startswith("*") or "[" in alt or "]" in alt
                for alt in alts
            ):
                symbolic += 1
            if any(alt in GVCF_WILDCARD_ALLELES for alt in alts):
                gvcf_markers += 1
    return {
        "records": records,
        "multiallelic_records": multiallelic,
        "symbolic_records": symbolic,
        "gvcf_markers": gvcf_markers,
    }
