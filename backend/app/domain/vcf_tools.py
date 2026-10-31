from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path

from backend.app.domain.vcf_validation import declared_vcf_contig_lengths

GVCF_WILDCARD_ALLELES = {"<NON_REF>", "<*>"}


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
                    handle.write(header + "\n")
            handle.write(record + "\n")
            counts[key] += 1

        with opener(source, "rt", encoding="utf-8-sig") as handle:
            for raw in handle:
                line = raw.rstrip("\r\n")
                if line.startswith("#"):
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
    return {
        "routing_version": "1",
        "records_total": sum(counts[key] for key in (
            "sequence", "gvcf_blocks", "gvcf_unresolved", "structural",
            "spanning_deletions", "telomere", "telomere_after", "reference_only",
        )),
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
                " ".join(index_command),
            ]),
            "reference_fasta": str(reference_fasta),
            "reference_check": "error",
            "multiallelic_mode": MULTIALLELIC_POLICY,
            "multiallelic_overlap_policy": MULTIALLELIC_OVERLAP_POLICY,
            "source_record_mapping_tag": ORIGINAL_RECORD_TAG,
            "source_record_mapping_policy": "BCFTOOLS_OLD_REC_TAG_SOURCE_ALT_INDEX",
            "mnv_policy": MNV_POLICY,
            "compression": "BGZF",
            "index": "CSI",
            "index_path": str(index_path),
            "gvcf_wildcard_command": "bcftools view -A",
            "stderr": "\n".join(x for x in (view_stderr, normalized_stderr, sorted_stderr, indexed_stderr) if x),
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
        'Description="Original source record CHROM|POS|REF|ALT|USED_ALT_IDX">\\n'
    )
    source_gt_header_line = (
        '##FORMAT=<ID=SIRALOOM_SOURCE_GT,Number=1,Type=String,'
        'Description="Original sample GT before SIRALOOM per-ALT splitting">\\n'
    )
    source_alt_count_header_line = (
        '##FORMAT=<ID=SIRALOOM_SOURCE_ALT_COUNT,Number=1,Type=Integer,'
        'Description="Number of ALT alleles in the source record before splitting">\\n'
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
            fields = line.rstrip("\\r\\n").split("\\t")
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
            output_handle.write("\\t".join(fields) + "\\n")
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
    definitions: set[str] = set()
    header_columns: int | None = None
    with opener(input_path, "rt", encoding="utf-8-sig") as handle:
        for line in handle:
            if line.startswith("##FORMAT=<ID="):
                tag = line.split("##FORMAT=<ID=", 1)[1].split(",", 1)[0]
                if tag in {SOURCE_GT_FORMAT_TAG, SOURCE_ALT_COUNT_FORMAT_TAG}:
                    definitions.add(tag)
            elif line.startswith("#CHROM"):
                header_columns = len(line.rstrip("\\r\\n").split("\\t"))
                break
    if definitions != {SOURCE_GT_FORMAT_TAG, SOURCE_ALT_COUNT_FORMAT_TAG}:
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
            fields = line.rstrip("\\r\\n").split("\\t")
            if len(fields) != header_columns or len(fields) < 10:
                raise VCFToolError("Existing source-genotype VCF has a malformed record.")
            format_keys = fields[8].split(":")
            if SOURCE_GT_FORMAT_TAG not in format_keys or SOURCE_ALT_COUNT_FORMAT_TAG not in format_keys:
                raise VCFToolError("Existing normalized record is missing source-genotype FORMAT fields.")
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

def _reject_original_record_tag_collision(input_path: Path, *, allow_existing: bool) -> bool:
    opener = gzip.open if input_path.name.lower().endswith((".gz", ".bgz")) else open
    has_definition = False
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
    if not has_definition:
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
