from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path

GVCF_WILDCARD_ALLELES = {"<NON_REF>", "<*>"}


def route_vcf_records(input_path: str | Path, output_dir: str | Path) -> dict:
    """Partition a validated VCF without changing records or sample semantics.

    Only sequence-resolved records are sent to ordinary normalization. GVCF
    reference blocks and structural records are copied byte-for-text unchanged
    into separate review artifacts. A GVCF variant is eligible for the
    sequence path only when every sample has a complete GT that does not call
    a wildcard allele; bcftools 1.19 ``view -A`` then removes that unseen
    wildcard while updating allele-indexed fields.
    """
    import gzip

    source = Path(input_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    names = {
        "sequence": output / "sequence-input.vcf",
        "gvcf_blocks": output / "gvcf-reference-blocks.vcf",
        "gvcf_unresolved": output / "gvcf-unresolved-variants.vcf",
        "structural": output / "structural-variants.vcf",
        "spanning_deletions": output / "spanning-deletion-records.vcf",
        "telomere": output / "telomere-records.vcf",
    }
    opener = gzip.open if source.name.lower().endswith((".gz", ".bgz")) else open
    headers: list[str] = []
    counts = {key: 0 for key in names}
    counts["reference_only"] = 0
    handles = {}
    sample_count = 0
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
                alts = fields[4].split(",")
                if alts == ["."]:
                    counts["reference_only"] += 1
                    continue
                try:
                    position = int(fields[1])
                except ValueError as exc:
                    raise VCFToolError("Cannot route VCF record with a non-integer POS.") from exc
                if position == 0:
                    emit("telomere", line)
                    continue
                wildcard_indexes = {i + 1 for i, alt in enumerate(alts) if alt in GVCF_WILDCARD_ALLELES}
                if any(alt == "*" for alt in alts):
                    emit("spanning_deletions", line)
                    continue
                is_structural = any(
                    alt not in GVCF_WILDCARD_ALLELES and
                    (alt.startswith("<") or "[" in alt or "]" in alt)
                    for alt in alts
                )
                if is_structural:
                    emit("structural", line)
                    continue
                if wildcard_indexes:
                    concrete_alts = [alt for alt in alts if alt not in GVCF_WILDCARD_ALLELES]
                    if not concrete_alts:
                        emit("gvcf_blocks", line)
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
                    emit("sequence" if fully_unseen else "gvcf_unresolved", line)
                    continue
                emit("sequence", line)
    return {
        "routing_version": "1",
        "records_total": sum(counts.values()),
        "sequence_records": counts["sequence"],
        "reference_only_records": counts["reference_only"],
        "gvcf_reference_blocks": counts["gvcf_blocks"],
        "gvcf_unresolved_variant_records": counts["gvcf_unresolved"],
        "structural_variant_records": counts["structural"],
        "spanning_deletion_records": counts["spanning_deletions"],
        "telomere_records": counts["telomere"],
        "sequence_path": str(names["sequence"]) if counts["sequence"] else None,
        "gvcf_blocks_path": str(names["gvcf_blocks"]) if counts["gvcf_blocks"] else None,
        "gvcf_unresolved_path": str(names["gvcf_unresolved"]) if counts["gvcf_unresolved"] else None,
        "structural_path": str(names["structural"]) if counts["structural"] else None,
        "spanning_deletions_path": str(names["spanning_deletions"]) if counts["spanning_deletions"] else None,
        "telomere_path": str(names["telomere"]) if counts["telomere"] else None,
        "gvcf_wildcard_policy": "BCFTOOLS_VIEW_TRIM_UNSEEN_AT_VARIANT_SITES",
    }


MNV_POLICY = "PRESERVE"
MULTIALLELIC_POLICY = "SPLIT_WITH_BCFTOOLS"


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
        "bcftools", "norm", "-m", "-any", "-N", "-Ov",
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
        "command": "bcftools norm -m -any -N",
        "stderr": (completed.stderr or "").strip(),
    }


def normalize_vcf_with_bcftools(
    input_path: str | Path,
    output_path: str | Path,
    *,
    reference_fasta: str | Path,
    expected_bcftools_version: str | None = None,
    timeout_seconds: int = 1800,
) -> dict:
    """Normalize, sort, and CSI-index a VCF before publishing either output.

    All expensive work occurs in a private directory on the destination
    filesystem. Existing output and index files remain untouched until
    normalization, sorting, and indexing have all succeeded.
    """
    if not bcftools_available():
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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    index_path = Path(str(output_path) + ".csi")

    try:
        version_result = subprocess.run(
            ["bcftools", "--version"],
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

        # ``view -A`` is available in the pinned 1.19 release. The router only
        # places records here when the GVCF wildcard is provably uncalled.
        prepared_path = work / "prepared.vcf.gz"
        view_command = ["bcftools", "view", "-A", "-Oz", "-o", str(prepared_path), str(input_path)]
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

        normalize_command = [
            "bcftools", "norm", "-f", str(reference_fasta), "-c", "e",
            "-m", "-any", "-Oz", "-o", str(normalized_path), str(prepared_path),
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

        sort_command = ["bcftools", "sort", "-Oz", "-o", str(sorted_path), str(normalized_path)]
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

        index_command = ["bcftools", "index", "--csi", "--force", str(sorted_path)]
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
            "command": " && ".join([" ".join(view_command), " ".join(normalize_command), " ".join(sort_command), " ".join(index_command)]),
            "reference_fasta": str(reference_fasta),
            "reference_check": "error",
            "multiallelic_mode": MULTIALLELIC_POLICY,
            "mnv_policy": MNV_POLICY,
            "compression": "BGZF",
            "index": "CSI",
            "index_path": str(index_path),
            "gvcf_wildcard_command": "bcftools view -A",
            "stderr": "\n".join(x for x in (view_stderr, normalized_stderr, sorted_stderr, indexed_stderr) if x),
        }

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
