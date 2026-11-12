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
        "profile_version": "1.0.0",
        "source_references": [
            "https://gatk.broadinstitute.org/hc/en-us/articles/360036359552-HaplotypeCaller",
            "https://gatk.broadinstitute.org/hc/en-us/articles/360035531692-VCF-Variant-Call-Format",
        ],
        "caller_family": "GATK",
        "caller_name": "GATK HaplotypeCaller",
        "documented_example_vcf_versions": ["VCFv4.2"],
        "required_format_fields": ["GT"],
        "expected_header_definitions": {
            "INFO": {
                "AC": ("A", "Integer"), "AF": ("A", "Float"), "AN": ("1", "Integer"),
                "DP": ("1", "Integer"), "FS": ("1", "Float"), "MQ": ("1", "Float"),
                "MQRankSum": ("1", "Float"), "QD": ("1", "Float"),
                "ReadPosRankSum": ("1", "Float"), "SOR": ("1", "Float"),
            },
            "FORMAT": {
                "GT": ("1", "String"), "AD": ("R", "Integer"), "DP": ("1", "Integer"),
                "GQ": ("1", "Integer"), "PL": ("G", "Integer"), "PS": ("1", "Integer"),
                "PGT": ("1", "String"), "PID": ("1", "String"),
                "MIN_DP": ("1", "Integer"), "RGQ": ("1", "Integer"),
            },
        },
        "germline_capability": "GERMLINE_SMALL_VARIANT_CALLER",
        "documented_format_semantics": {
            "GT": "Sample genotype; allele indexes refer to REF followed by ALT order.",
            "AD": "Unfiltered allele depth in REF/ALT order, excluding reads deemed uninformative; this is not interchangeable with DP.",
            "DP": "Filtered sample-level depth: reads passing caller filters are counted, including uninformative reads; the GATK header documents MQ=255 and bad-mate filtering.",
            "GQ": "Genotype quality derived from genotype likelihoods; GATK documents a cap of 99.",
            "PL": "Normalized Phred-scaled genotype likelihoods; Number=G ordering is defined by VCF genotype ordering.",
            "PS": "Phase-set identifier when emitted.",
            "PGT": "Physical phasing genotype when emitted.",
            "PID": "Physical phasing identifier when emitted.",
            "MIN_DP": "Minimum depth within a GVCF reference block when emitted.",
            "RGQ": "Reference genotype quality in GVCF workflows when emitted.",
        },
        "documented_info_semantics": {
            "DP": "Approximate site-level depth; distinct from sample-level FORMAT/DP.",
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
        "profile_version": "1.0.0",
        "source_references": [
            "https://github.com/google/deepvariant",
            "https://github.com/google/deepvariant/blob/r1.10/deepvariant/testdata/golden.postprocess_single_site_output.vcf",
        ],
        "caller_family": "GOOGLE_DEEPVARIANT",
        "caller_name": "Google DeepVariant",
        "documented_example_vcf_versions": ["VCFv4.2"],
        "required_format_fields": ["GT"],
        "expected_header_definitions": {
            "INFO": {"END": ("1", "Integer")},
            "FORMAT": {
                "GT": ("1", "String"), "GQ": ("1", "Integer"), "DP": ("1", "Integer"),
                "MIN_DP": ("1", "Integer"), "AD": ("R", "Integer"), "VAF": ("A", "Float"),
                "PL": ("G", "Integer"), "PS": ("1", "Integer"),
                "MF": ("R", "Float"), "MD": ("R", "Integer"), "MT": ("1", "String"),
                "MI": ("1", "Float"), "MED_DP": ("1", "Integer"),
            },
        },
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
        "profile_version": "1.0.0",
        "source_references": [
            "https://help.dragen.illumina.com/dragen-v4.3/product-guide/dragen-v4.3/dragen-dna-pipeline/small-variant-calling",
        ],
        "caller_family": "ILLUMINA_DRAGEN",
        "caller_name": "Illumina DRAGEN Small Variant Caller",
        "documented_example_vcf_versions": ["VCFv4.2"],
        "required_format_fields": ["GT"],
        "expected_header_definitions": {
            "INFO": {
                "AC": ("A", "Integer"), "AF": ("A", "Float"), "AN": ("1", "Integer"),
                "DP": ("1", "Integer"), "FS": ("1", "Float"), "MQ": ("1", "Float"),
                "QD": ("1", "Float"), "SOR": ("1", "Float"),
                "FractionInformativeReads": ("1", "Float"), "R2_5P_bias": ("1", "Float"),
            },
            "FORMAT": {
                "GT": ("1", "String"), "AD": ("R", "Integer"), "AF": ("A", "Float"),
                "DP": ("1", "Integer"), "F1R2": ("R", "Integer"), "F2R1": ("R", "Integer"),
                "GQ": ("1", "Integer"), "PL": ("G", "Integer"), "GL": ("G", "Float"),
                "GP": ("G", "Float"), "PRI": ("G", "Float"), "SB": ("4", "Integer"),
                "MB": ("4", "Integer"), "PS": ("1", "Integer"), "MIN_DP": ("1", "Integer"),
            },
        },
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
            "GP": "DRAGEN-defined Phred-scaled posterior genotype values; this deliberately differs from the VCF-reserved FORMAT/GP probability scale (0–1) and must not be interpreted as normalized probabilities.",
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
    sample_record_count: int = 0,
    sample_records_without_gt: int = 0,
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
    info_definitions: dict[str, dict[str, str | None]] = {}
    format_definitions: dict[str, dict[str, str | None]] = {}
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
            attributes = _attributes(line)
            field_id = attributes.get("ID") or _header_id(line)
            if field_id:
                info_fields.add(field_id)
                info_definitions[field_id] = {
                    "number": attributes.get("Number"),
                    "type": attributes.get("Type"),
                }
        elif line.startswith("##FORMAT=<"):
            attributes = _attributes(line)
            field_id = attributes.get("ID") or _header_id(line)
            if field_id:
                format_fields.add(field_id)
                format_definitions[field_id] = {
                    "number": attributes.get("Number"),
                    "type": attributes.get("Type"),
                }
        elif line.startswith("##FILTER=<"):
            field_id = _header_id(line)
            if field_id:
                filter_ids.add(field_id)
        elif line.startswith("##ALT=<"):
            field_id = _header_id(line)
            if field_id:
                alt_ids.add(field_id)

    source_set = {value.strip() for value in source_values if value.strip()}
    chrom_header = next((line for line in lines if line.startswith("#CHROM\t")), None)
    sample_count = max(0, len(chrom_header.split("\t")) - 9) if chrom_header else 0
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

    if version_status == "CONFLICTED":
        identity_status = "CONFLICTED"
        identity_evidence.append("MULTIPLE_CALLER_RELEASE_MARKERS")
    elif profile_id and version_status == "MISSING":
        identity_status = "PARTIAL"
        identity_evidence.append("CALLER_RELEASE_NOT_DECLARED")

    command_lines = gatk_command_lines + dragen_command_lines
    command_line_digest = (
        hashlib.sha256("\n".join(command_lines).encode("utf-8")).hexdigest()
        if command_lines
        else None
    )

    definition = (
        _PROFILE_DEFINITIONS.get(profile_id or "")
        if identity_status != "CONFLICTED"
        else None
    )
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
    unique_models = sorted(set(deepvariant_models))
    model_status = (
        "DECLARED" if len(unique_models) == 1
        else "CONFLICTED" if len(unique_models) > 1
        else "NOT_DECLARED"
    )

    field_declaration_checks: list[dict[str, str]] = []
    field_declaration_mismatches: list[dict[str, str]] = []
    if definition:
        for namespace, expected_fields in definition["expected_header_definitions"].items():
            observed_definitions = info_definitions if namespace == "INFO" else format_definitions
            for field_id, (expected_number, expected_type) in expected_fields.items():
                observed = observed_definitions.get(field_id)
                if observed is None:
                    continue
                check = {
                    "namespace": namespace,
                    "field_id": field_id,
                    "observed_number": str(observed.get("number") or ""),
                    "observed_type": str(observed.get("type") or ""),
                    "expected_number": expected_number,
                    "expected_type": expected_type,
                    "status": (
                        "PASS"
                        if observed.get("number") == expected_number
                        and observed.get("type") == expected_type
                        else "MISMATCH"
                    ),
                }
                field_declaration_checks.append(check)
                if check["status"] == "MISMATCH":
                    field_declaration_mismatches.append(check)

    required_format_fields = definition["required_format_fields"] if definition else []
    required_format_field_violations: list[dict[str, str | int]] = []
    if definition and sample_count > 0:
        for field_id in required_format_fields:
            if field_id not in format_fields:
                required_format_field_violations.append({
                    "field_id": field_id,
                    "reason": "REQUIRED_FORMAT_HEADER_DEFINITION_MISSING",
                })
            if field_id == "GT" and sample_records_without_gt:
                required_format_field_violations.append({
                    "field_id": field_id,
                    "reason": "MISSING_FROM_SAMPLE_RECORD_FORMAT",
                    "record_count": sample_records_without_gt,
                })

    field_semantic_deviations = (
        [{
            "namespace": "FORMAT",
            "field_id": "GP",
            "status": "CALLER_SPECIFIC_SCALE_DIFFERS_FROM_VCF_RESERVED_SEMANTICS",
            "description": "DRAGEN documents FORMAT/GP in Phred scale; VCF reserves FORMAT/GP for posterior probabilities in [0, 1].",
        }]
        if profile_id == "dragen_snv_germline" and "GP" in format_fields
        else []
    )

    if identity_status == "CONFLICTED":
        semantic_status = "CONFLICTED_CALLER_METADATA"
    elif not definition:
        semantic_status = "NOT_ASSESSED"
    elif required_format_field_violations:
        semantic_status = "MISSING_REQUIRED_FORMAT_FIELD"
    elif field_declaration_mismatches:
        semantic_status = "DECLARATION_MISMATCH"
    elif field_semantic_deviations:
        semantic_status = "CALLER_SPEC_SEMANTIC_DEVIATION"
    elif not field_declaration_checks:
        semantic_status = "NO_DOCUMENTED_CALLER_FIELDS_PRESENT"
    elif version_status == "DECLARED":
        semantic_status = "DOCUMENTED_HEADER_CONVENTIONS_MATCH_RELEASE_NOT_QUALIFIED"
    else:
        semantic_status = "DOCUMENTED_HEADER_CONVENTIONS_MATCH_RELEASE_UNVERIFIED"

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
        "deepvariant_model_type": unique_models[0] if len(unique_models) == 1 else None,
        "deepvariant_model_type_status": model_status,
        "command_line_header_present": bool(command_lines),
        "command_line_header_sha256": command_line_digest,
        "vcf_specification_version": fileformat,
        "caller_profile_version": definition["profile_version"] if definition else None,
        "caller_profile_source_references": definition["source_references"] if definition else [],
        "caller_germline_capability": definition["germline_capability"] if definition else None,
        "documented_gvcf_markers": definition["gvcf_markers"] if definition else [],
        "profile_semantic_scope": "DOCUMENTED_OUTPUT_CONVENTIONS_NOT_RELEASE_QUALIFICATION",
        "documented_example_vcf_versions": definition["documented_example_vcf_versions"] if definition else [],
        "declared_info_fields": sorted(info_fields),
        "declared_format_fields": sorted(format_fields),
        "declared_filter_ids": sorted(filter_ids),
        "declared_alt_ids": sorted(alt_ids),
        "sample_count": sample_count,
        "sample_record_count": sample_record_count,
        "sample_records_without_gt": sample_records_without_gt,
        "required_format_fields": required_format_fields,
        "required_format_field_violations": required_format_field_violations,
        "documented_format_semantics_for_present_fields": present_format_semantics,
        "documented_info_semantics_for_present_fields": present_info_semantics,
        "field_declaration_checks": field_declaration_checks,
        "field_declaration_mismatches": field_declaration_mismatches,
        "field_semantic_deviations": field_semantic_deviations,
        "caller_semantic_compatibility_status": semantic_status,
        "caller_semantic_compatibility_review_required": semantic_status not in {
            "DOCUMENTED_HEADER_CONVENTIONS_MATCH_RELEASE_NOT_QUALIFIED",
            "NO_DOCUMENTED_CALLER_FIELDS_PRESENT",
        },
        "documented_filter_ids": definition["documented_filter_ids"] if definition else [],
        "gvcf_reference_confidence_markers_present": bool(gvcf_marker_count),
        "gvcf_handling_status": "ROUTE_TO_GVCF_WORKFLOW" if gvcf_marker_count else "NO_GVCF_MARKER_DETECTED",
        "cross_caller_comparison_policy": definition["cross_caller_comparison"] if definition else "CALLER_SEMANTICS_UNKNOWN; DO_NOT_INTERPRET_CALLER_METRICS_BY_NAME_ALONE",
        "assay_mode_status": "NOT_ATTESTED_BY_VCF_HEADER",
        "release_qualification_status": "NOT_ESTABLISHED",
        "clinical_qualification_status": "NOT_ESTABLISHED",
        "profile_match_status": (
            "CONFLICTED_METADATA" if identity_status == "CONFLICTED"
            else "CALLER_FAMILY_MATCH_VERSION_MISSING" if profile_id and version_status == "MISSING"
            else "METADATA_MATCH_ONLY" if profile_id
            else "NO_CALLER_PROFILE_MATCH"
        ),
    }
