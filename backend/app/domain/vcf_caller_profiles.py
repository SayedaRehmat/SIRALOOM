"""Caller-aware VCF provenance and semantic compatibility profiles.

The profiles describe documented output conventions. Header declarations are
untrusted provenance claims: they do not prove the executable, release, assay,
model, or clinical qualification that produced a VCF.
"""
from __future__ import annotations

import gzip
import hashlib
import re
from pathlib import Path
from typing import Any

_PROFILE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "gatk_haplotypecaller": {
        "caller_family": "GATK",
        "caller_name": "GATK HaplotypeCaller",
        "documented_example_vcf_versions": ["VCFv4.2"],
        "germline_capability": "GERMLINE_SMALL_VARIANT_CALLER",
        "documented_format_semantics": {
            "GT": "Sample genotype; allele indexes refer to REF followed by ALT order.",
            "AD": "Allelic depths in REF/ALT order. GATK documentation distinguishes AD from DP: AD is unfiltered allele evidence, while DP is approximate depth after caller read filtering.",
            "DP": "Approximate sample read depth; GATK documents exclusion of reads with MQ=255 or bad mates.",
            "GQ": "Genotype quality derived from genotype likelihoods; GATK documents a cap of 99.",
            "PL": "Normalized Phred-scaled genotype likelihoods; Number=G ordering is defined by VCF genotype ordering.",
            "PS": "Phase-set identifier when emitted.",
            "PGT": "Physical phasing genotype when emitted.",
            "PID": "Physical phasing identifier when emitted.",
            "MIN_DP": "Minimum depth within a GVCF reference block when emitted.",
            "RGQ": "Reference genotype quality in GVCF workflows when emitted.",
        },
        "documented_info_semantics": {
            "QD": "Quality by depth; caller-defined calculation and not a universal cross-caller threshold.",
            "FS": "Fisher strand-bias statistic.",
            "SOR": "Symmetric odds-ratio strand-bias statistic.",
            "MQ": "Mapping-quality summary.",
            "MQRankSum": "Mapping-quality rank-sum statistic.",
            "ReadPosRankSum": "Read-position rank-sum statistic.",
        },
        "documented_filter_ids": ["LowQual"],
        "gvcf_markers": ["<NON_REF>", "END", "MIN_DP"],
        "cross_caller_comparison": "QUAL, DP, AD and GQ must not be compared to another caller by numeric threshold without an assay- and release-specific validation.",
    },
    "deepvariant_germline": {
        "caller_family": "GOOGLE_DEEPVARIANT",
        "caller_name": "Google DeepVariant",
        "documented_example_vcf_versions": ["VCFv4.2"],
        "germline_capability": "GERMLINE_SMALL_VARIANT_CALLER",
        "documented_format_semantics": {
            "GT": "Sample genotype; allele indexes refer to REF followed by ALT order.",
            "GQ": "Conditional genotype quality as declared in the DeepVariant output header.",
            "DP": "Read depth as declared in the DeepVariant output header.",
            "AD": "Read depth for each allele in REF/ALT order.",
            "VAF": "Variant allele fraction for each ALT allele; Number=A in the documented output.",
            "PL": "Phred-scaled genotype likelihoods; Number=G in the documented output.",
            "PS": "Phase-set identifier when emitted.",
            "MIN_DP": "Minimum depth within a GVCF reference block when emitted.",
        },
        "documented_info_semantics": {
            "END": "End coordinate for symbolic/reference-block records when emitted.",
        },
        "documented_filter_ids": ["PASS", "RefCall", "LowQual", "NoCall"],
        "gvcf_markers": ["<NON_REF>", "<*>", "END", "MIN_DP"],
        "cross_caller_comparison": "QUAL, DP, AD and GQ must not be compared to another caller by numeric threshold without an assay-, model- and release-specific validation.",
    },
    "dragen_snv_germline": {
        "caller_family": "ILLUMINA_DRAGEN",
        "caller_name": "Illumina DRAGEN Small Variant Caller",
        "documented_example_vcf_versions": ["VCFv4.2"],
        "germline_capability": "GERMLINE_AND_SOMATIC_MODES; MODE_NOT_ATTESTED_BY_SOURCE_TAG",
        "documented_format_semantics": {
            "GT": "Sample genotype; interpret with the declared sample ploidy and DRAGEN mode.",
            "AD": "Allele depths based on informative reads, in REF/ALT order.",
            "AF": "Allele frequencies based on informative depth, one value per ALT allele.",
            "DP": "Informative sample depth for variant calls; do not confuse with INFO/DP, which DRAGEN documents as unfiltered depth.",
            "F1R2": "Read-orientation counts in the DRAGEN FORMAT output when emitted.",
            "F2R1": "Read-orientation counts in the DRAGEN FORMAT output when emitted.",
            "GQ": "DRAGEN genotype quality; its interpretation differs between variant and homozygous-reference GVCF calls.",
            "PL": "Phred-scaled genotype likelihoods when emitted.",
            "GL": "Log10 genotype likelihoods when emitted.",
            "GP": "Genotype posterior probabilities when emitted.",
            "PRI": "Genotype prior values when emitted.",
            "SB": "Strand-bias evidence when emitted.",
            "MB": "Mate-bias evidence when emitted.",
            "PS": "Phase-set identifier; DRAGEN documents the first phased variant position as the phase-set value.",
            "MIN_DP": "Minimum depth in a banded GVCF reference block when emitted.",
        },
        "documented_info_semantics": {
            "DP": "Unfiltered site depth for ordinary variant records; DRAGEN documents FORMAT/DP as informative depth.",
            "AC": "Alternate allele counts.",
            "AF": "Alternate allele frequencies.",
            "AN": "Total called allele number.",
            "QD": "DRAGEN quality-by-depth metric; not numerically interchangeable with GATK QD.",
            "FractionInformativeReads": "Fraction of reads informative for the calling decision.",
            "R2_5P_bias": "Read/mate positional-bias metric when emitted.",
        },
        "documented_filter_ids": ["PASS", "MosaicLowAF"],
        "gvcf_markers": ["<NON_REF>", "END", "MIN_DP"],
        "cross_caller_comparison": "DRAGEN explicitly documents different QUAL formulation and DP/AD/AF read-counting semantics from GATK. Never apply GATK QUAL/GQ/DP/AD thresholds to DRAGEN without DRAGEN- and assay-specific validation.",
    },
}

_PROFILE_ALIASES = {
    "gatk_haplotypecaller": "gatk_haplotypecaller",
    "deepvariant_germline": "deepvariant_germline",
    "dragen_snv_germline": "dragen_snv_germline",
}

_ID_RE = re.compile(r"(?:^|[<,])ID=([^,>]+)")
_ATTR_RE = re.compile(r'([A-Za-z][A-Za-z0-9_.-]*)=(?:"((?:\\.|[^"])*)"|([^,>]*))')


def _open_text(path: str | Path):
    source = Path(path)
    opener = gzip.open if source.name.lower().endswith((".gz", ".bgz")) else open
    return opener(source, "rt", encoding="utf-8-sig", newline="")


def _header(path: str | Path) -> list[str]:
    lines: list[str] = []
    with _open_text(path) as handle:
        for raw in handle:
            line = raw.rstrip("\r\n")
            if line.startswith("##"):
                lines.append(line)
                continue
            if line.startswith("#CHROM"):
                lines.append(line)
            break
    return lines


def _scalar_value(line: str) -> str:
    _key, _separator, value = line.partition("=")
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def _attributes(line: str) -> dict[str, str]:
    match = re.search(r"<(.*)>$", line)
    if not match:
        return {}
    result: dict[str, str] = {}
    for item in _ATTR_RE.finditer(match.group(1)):
        result[item.group(1)] = item.group(2) if item.group(2) is not None else (item.group(3) or "").strip()
    return result


def _header_id(line: str) -> str | None:
    match = _ID_RE.search(line)
    return match.group(1).strip('"') if match else None


def inspect_caller_provenance(
    path: str | Path,
    *,
    fileformat: str | None = None,
    gvcf_marker_count: int = 0,
) -> dict[str, Any]:
    """Identify declared caller metadata without treating it as authenticated.

    This function deliberately does not infer caller identity from common
    FORMAT names such as GT, AD, DP, GQ or PL. It never applies caller-specific
    quality thresholds and never marks a caller release clinically qualified.
    """
    lines = _header(path)
    source_values: list[str] = []
    gatk_stages: list[dict[str, str]] = []
    gatk_command_lines: list[str] = []
    deepvariant_versions: list[str] = []
    deepvariant_models: list[str] = []
    dragen_versions: list[str] = []
    dragen_command_lines: list[str] = []
    info_fields: set[str] = set()
    format_fields: set[str] = set()
    filter_ids: set[str] = set()
    alt_ids: set[str] = set()

    for line in lines:
        if line.startswith("##source="):
            source_values.append(_scalar_value(line))
        elif line.startswith("##GATKCommandLine"):
            gatk_command_lines.append(line)
            attributes = _attributes(line)
            stage = line.split("=", 1)[0].removeprefix("##GATKCommandLine.")
            stage = stage if stage != "##GATKCommandLine" else attributes.get("ID", "")
            if stage:
                gatk_stages.append({
                    "stage": stage,
                    "version": attributes.get("Version", ""),
                })
        elif line.startswith("##DeepVariant_version=") or line.startswith("##DeepVariantVersion="):
            deepvariant_versions.append(_scalar_value(line))
        elif line.startswith("##DeepVariant_model_type=") or line.startswith("##DeepVariantModelType="):
            deepvariant_models.append(_scalar_value(line))
        elif line.startswith("##DRAGENVersion="):
            dragen_versions.append(_scalar_value(line))
        elif line.startswith("##DRAGENCommandLine=") or line.startswith("##DRAGENCommandLine<"):
            dragen_command_lines.append(line)
        elif line.startswith("##INFO=<"):
            field_id = _header_id(line)
            if field_id:
                info_fields.add(field_id)
        elif line.startswith("##FORMAT=<"):
            field_id = _header_id(line)
            if field_id:
                format_fields.add(field_id)
        elif line.startswith("##FILTER=<"):
            field_id = _header_id(line)
            if field_id:
                filter_ids.add(field_id)
        elif line.startswith("##ALT=<"):
            field_id = _header_id(line)
            if field_id:
                alt_ids.add(field_id)

    source_set = {value.strip() for value in source_values if value.strip()}
    gatk_haplotypecaller = any(
        item["stage"].lower() == "haplotypecaller" for item in gatk_stages
    ) or any(value.lower() == "haplotypecaller" for value in source_set)
    deepvariant_declared = bool(deepvariant_versions) or any(
        value.lower() == "deepvariant" for value in source_set
    )
    dragen_snv_declared = any(value.upper() == "DRAGEN_SNV" for value in source_set)
    dragen_other_declared = any(
        value.upper() in {"DRAGEN_SV", "DRAGEN_CNV"} for value in source_set
    )

    candidates: list[str] = []
    if gatk_haplotypecaller:
        candidates.append("gatk_haplotypecaller")
    if deepvariant_declared:
        candidates.append("deepvariant_germline")
    if dragen_snv_declared:
        candidates.append("dragen_snv_germline")

    profile_id: str | None = None
    identity_status = "UNKNOWN"
    caller_family: str | None = None
    caller_name: str | None = None
    caller_version: str | None = None
    version_status = "MISSING"
    identity_evidence: list[str] = []

    if len(set(candidates)) > 1:
        identity_status = "CONFLICTED"
        identity_evidence.append("MULTIPLE_CALLER_FAMILY_MARKERS")
    elif candidates:
        profile_id = candidates[0]
        definition = _PROFILE_DEFINITIONS[profile_id]
        caller_family = definition["caller_family"]
        caller_name = definition["caller_name"]
        identity_status = "DECLARED"
        identity_evidence.append(profile_id.upper())
    elif dragen_versions:
        caller_family = "ILLUMINA_DRAGEN"
        caller_name = "Illumina DRAGEN (small-variant mode not established)"
        identity_status = "PARTIAL"
        identity_evidence.append("DRAGEN_VERSION_WITHOUT_DRAGEN_SNV_SOURCE")
    elif gatk_stages:
        caller_family = "GATK"
        caller_name = "GATK pipeline stage (variant caller not established)"
        identity_status = "PARTIAL"
        identity_evidence.append("GATK_STAGE_WITHOUT_HAPLOTYPECALLER_MARKER")
    elif dragen_other_declared:
        caller_family = "ILLUMINA_DRAGEN"
        caller_name = "Illumina DRAGEN non-SNV pipeline"
        identity_status = "PARTIAL"
        identity_evidence.append("DRAGEN_NON_SNV_SOURCE")

    versions: list[str] = []
    if profile_id == "gatk_haplotypecaller":
        versions = [item["version"] for item in gatk_stages if item["stage"].lower() == "haplotypecaller" and item["version"]]
    elif profile_id == "deepvariant_germline":
        versions = deepvariant_versions
    elif profile_id == "dragen_snv_germline":
        versions = dragen_versions
    elif caller_family == "ILLUMINA_DRAGEN":
        versions = dragen_versions

    unique_versions = sorted(set(version.strip() for version in versions if version.strip()))
    if len(unique_versions) == 1:
        caller_version = unique_versions[0]
        version_status = "DECLARED"
    elif len(unique_versions) > 1:
        version_status = "CONFLICTED"

    if profile_id and version_status == "MISSING":
        identity_status = "PARTIAL"
        identity_evidence.append("CALLER_RELEASE_NOT_DECLARED")

    command_lines = gatk_command_lines + dragen_command_lines
    command_line_digest = (
        hashlib.sha256("\n".join(command_lines).encode("utf-8")).hexdigest()
        if command_lines
        else None
    )

    definition = _PROFILE_DEFINITIONS.get(profile_id or "")
    present_format_semantics = {
        key: definition["documented_format_semantics"][key]
        for key in sorted(format_fields)
        if definition and key in definition["documented_format_semantics"]
    }
    present_info_semantics = {
        key: definition["documented_info_semantics"][key]
        for key in sorted(info_fields)
        if definition and key in definition["documented_info_semantics"]
    }

    return {
        "schema_version": 1,
        "identity_status": identity_status,
        "identity_source": "VCF_HEADER_DECLARATION_UNVERIFIED",
        "identity_evidence": sorted(set(identity_evidence)),
        "caller_profile_id": profile_id,
        "caller_family": caller_family,
        "caller_name": caller_name,
        "caller_version": caller_version,
        "version_status": version_status,
        "producer_stages": sorted({item["stage"] for item in gatk_stages}),
        "declared_source_values": sorted(source_set),
        "deepvariant_model_type": sorted(set(deepvariant_models))[0] if len(set(deepvariant_models)) == 1 else None,
        "deepvariant_model_type_status": "DECLARED" if len(set(deepvariant_models)) == 1 else "NOT_DECLARED_OR_CONFLICTED",
        "command_line_header_present": bool(command_lines),
        "command_line_header_sha256": command_line_digest,
        "vcf_specification_version": fileformat,
        "documented_example_vcf_versions": definition["documented_example_vcf_versions"] if definition else [],
        "declared_info_fields": sorted(info_fields),
        "declared_format_fields": sorted(format_fields),
        "declared_filter_ids": sorted(filter_ids),
        "declared_alt_ids": sorted(alt_ids),
        "documented_format_semantics_for_present_fields": present_format_semantics,
        "documented_info_semantics_for_present_fields": present_info_semantics,
        "documented_filter_ids": definition["documented_filter_ids"] if definition else [],
        "gvcf_reference_confidence_markers_present": bool(gvcf_marker_count),
        "gvcf_handling_status": "ROUTE_TO_GVCF_WORKFLOW" if gvcf_marker_count else "NO_GVCF_MARKER_DETECTED",
        "cross_caller_comparison_policy": definition["cross_caller_comparison"] if definition else "CALLER_SEMANTICS_UNKNOWN; DO_NOT_INTERPRET_CALLER_METRICS_BY_NAME_ALONE",
        "assay_mode_status": "NOT_ATTESTED_BY_VCF_HEADER",
        "release_qualification_status": "NOT_ESTABLISHED",
        "clinical_qualification_status": "NOT_ESTABLISHED",
        "profile_match_status": "METADATA_MATCH_ONLY" if profile_id else "NO_CALLER_PROFILE_MATCH",
    }
