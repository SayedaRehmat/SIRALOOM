import base64
import gzip
import json
import re
from dataclasses import dataclass, field
from typing import Iterator

from backend.app.domain.schemas import CanonicalVariant
from backend.app.domain.vcf_validation import declared_vcf_contig_lengths

SOURCE_GT_FORMAT_TAG = "SIRALOOM_SOURCE_GT"
SOURCE_ALT_COUNT_FORMAT_TAG = "SIRALOOM_SOURCE_ALT_COUNT"
SOURCE_RECORD_INFO_TAG = "SIRALOOM_ORIG"
SOURCE_ROUTING_INFO_TAG = "SIRALOOM_SOURCE"


@dataclass(frozen=True)
class VCFRecord:
    chrom: str
    pos: int
    ref: str
    alt: str
    raw: str
    sample_calls: dict[str, dict] = field(default_factory=dict)

class VCFValidationError(ValueError):
    pass

def open_text(path: str):
    # Preserve BOMs so the parser can reject them: the VCF specification forbids a
    # byte-order mark, and silently stripping it would make malformed input look valid.
    if path.endswith((".gz", ".bgz")):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "rt", encoding="utf-8")

def _phase_status(genotype: str | None) -> str:
    if not genotype:
        return "UNSPECIFIED"
    if "|" in genotype and "/" in genotype:
        return "PARTIALLY_PHASED"
    if "|" in genotype:
        return "PHASED"
    if "/" in genotype:
        return "UNPHASED"
    return "UNSPECIFIED"


def parse_vcf(
    path: str,
    *,
    sample_name: str | None = None,
    allow_unselected_multisample: bool = False,
) -> Iterator[VCFRecord]:
    found_header = False
    sample_names: list[str] = []
    declared_contig_lengths = declared_vcf_contig_lengths(path)
    with open_text(path) as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.rstrip("\n")
            if line_no == 1 and line.startswith("\ufeff"):
                raise VCFValidationError("VCF files must not contain a UTF-8 byte-order mark")
            if not line:
                continue
            if line.startswith("##"):
                continue
            if line.startswith("#CHROM"):
                found_header = True
                sample_names = line.split("\t")[9:]
                if sample_name is not None and sample_name not in sample_names:
                    raise VCFValidationError(
                        f"Selected VCF sample {sample_name!r} is not present in the #CHROM header"
                    )
                if (
                    len(sample_names) > 1
                    and sample_name is None
                    and not allow_unselected_multisample
                ):
                    raise VCFValidationError(
                        "Multisample VCF parsing requires an explicit sample_name; "
                        "refusing to combine different individuals' genotype calls."
                    )
                continue
            if line.startswith("#"):
                continue
            if not found_header:
                raise VCFValidationError(f"VCF data encountered before #CHROM header at line {line_no}")
            fields = line.split("\t")
            if len(fields) < 8:
                raise VCFValidationError(f"Malformed VCF record at line {line_no}: expected at least 8 tab-separated columns")
            chrom, pos_s, _id, ref, alt = fields[:5]
            try:
                pos = int(pos_s)
            except ValueError as exc:
                raise VCFValidationError(f"Invalid POS at line {line_no}: {pos_s!r}") from exc
            if pos < 0:
                raise VCFValidationError(f"POS must be non-negative at line {line_no}")
            if not re.fullmatch(r"[A-Za-z*.]+", ref) or not re.fullmatch(r"[A-Za-z*.,<>\[\]():]+", alt):
                raise VCFValidationError(f"Invalid REF/ALT allele syntax at line {line_no}")
            if not ref or not alt:
                raise VCFValidationError(f"REF/ALT missing at line {line_no}")
            if alt == ".":
                continue
            if "." in alt.split(","):
                raise VCFValidationError(
                    f"ALT '.' cannot be combined with alternate alleles at line {line_no}"
                )
            if pos == 0 or pos == declared_contig_lengths.get(chrom, -2) + 1:
                # Telomere sentinels are not allele coordinates suitable for
                # canonical small-variant processing. N+1 is provisional
                # until the pinned reference verifies the declared length.
                continue
            source_mapping = _source_record_mapping(fields[7])
            source_lineage = _source_record_lineage(fields[7])
            if (
                source_mapping is not None
                and source_lineage is not None
                and source_mapping[1] != len(source_lineage["normalized_alt_source_indexes"])
            ):
                raise VCFValidationError(
                    f"SIRALOOM_ORIG ALT count disagrees with {SOURCE_ROUTING_INFO_TAG} at line {line_no}"
                )
            sample_calls: dict[str, dict] = {}
            if len(fields) > 8 and sample_names:
                format_keys = [] if fields[8] in {"", "."} else fields[8].split(":")
                selected_samples = (
                    [sample_name] if sample_name is not None else sample_names
                )
                sample_indexes = {name: sample_names.index(name) for name in selected_samples}
                for selected_name in selected_samples:
                    sample_value = fields[9 + sample_indexes[selected_name]]
                    values = sample_value.split(":")
                    # VCF permits omitted trailing FORMAT values; preserve the
                    # declared schema by materializing those values as missing.
                    call_fields = {
                        key: values[index] if index < len(values) else "."
                        for index, key in enumerate(format_keys)
                    }
                    genotype = call_fields.get("GT")
                    source_alt_count_value = call_fields.get(SOURCE_ALT_COUNT_FORMAT_TAG)
                    if source_alt_count_value not in {None, "", "."}:
                        try:
                            source_alt_count = int(source_alt_count_value)
                        except ValueError as exc:
                            raise VCFValidationError(
                                f"Invalid {SOURCE_ALT_COUNT_FORMAT_TAG} at line {line_no}"
                            ) from exc
                        if source_alt_count < 1:
                            raise VCFValidationError(
                                f"Non-positive {SOURCE_ALT_COUNT_FORMAT_TAG} at line {line_no}"
                            )
                    else:
                        source_alt_count = source_mapping[1] if source_mapping else None
                    if (
                        source_mapping is not None
                        and source_alt_count is not None
                        and source_alt_count != source_mapping[1]
                    ):
                        raise VCFValidationError(
                            f"{SOURCE_ALT_COUNT_FORMAT_TAG} disagrees with SIRALOOM_ORIG at line {line_no}"
                        )
                    if SOURCE_GT_FORMAT_TAG in call_fields:
                        source_genotype = call_fields.get(SOURCE_GT_FORMAT_TAG)
                    elif source_mapping and source_mapping[1] > 1:
                        # A previously split multiallelic record without its
                        # source GT cannot be interpreted as a patient genotype.
                        source_genotype = None
                    else:
                        source_genotype = genotype
                    source_zygosity = (
                        _zygosity(source_genotype)
                        if source_genotype is not None
                        else "GENOTYPE_UNAVAILABLE"
                    )
                    sample_calls[selected_name] = {
                        "sample_name": selected_name,
                        # The source genotype is authoritative for clinical
                        # interpretation; the split biallelic GT is retained
                        # separately for exact normalized-artifact traceability.
                        "genotype": source_genotype,
                        "source_genotype": source_genotype,
                        "normalized_genotype": genotype,
                        "source_alt_index": source_mapping[0] if source_mapping else None,
                        "source_alt_count": source_alt_count,
                        "source_record_index": source_lineage["source_record_index"] if source_lineage else None,
                        "source_record_sha256": source_lineage["source_record_sha256"] if source_lineage else None,
                        "source_genotype_stage": (
                            "ROUTED_SEQUENCE_INPUT_PRE_SPLIT"
                            if SOURCE_GT_FORMAT_TAG in call_fields
                            else "INPUT_RECORD"
                        ),
                        "original_source_alt_count": source_lineage["source_alt_count"] if source_lineage else None,
                        "zygosity": source_zygosity,
                        "source_zygosity": source_zygosity,
                        "normalized_zygosity": _zygosity(genotype),
                        "phase": _phase_status(source_genotype),
                        "normalized_phase": _phase_status(genotype),
                        "phase_set": call_fields.get("PS"),
                        # Retain standard, local-allele, caller-specific, and
                        # future FORMAT fields for traceability rather than
                        # silently dropping data that the interpretation layer
                        # may need to evaluate or review.
                        "format_values": {
                            key: value for key, value in call_fields.items() if key != "GT"
                        },
                        "status": (
                            "AVAILABLE"
                            if source_zygosity not in {
                                "GENOTYPE_UNAVAILABLE", "NO_CALL", "PARTIAL_CALL", "INVALID_CALL"
                            }
                            else "MISSING_OR_PARTIAL"
                        ),
                    }
            alt_alleles = alt.split(",")
            for source_alt_index, alt_allele in enumerate(alt_alleles, start=1):
                routed_source_alt_index = (
                    source_mapping[0] if source_mapping is not None else source_alt_index
                )
                per_alt_calls = _sample_calls_for_alt(
                    sample_calls,
                    source_alt_index=source_alt_index,
                    source_alt_count=len(alt_alleles),
                )
                original_source_alt_index = (
                    source_lineage["normalized_alt_source_indexes"][routed_source_alt_index - 1]
                    if source_lineage is not None and source_mapping is not None
                    else None
                )
                for call in per_alt_calls.values():
                    call["original_source_alt_index"] = original_source_alt_index
                yield VCFRecord(chrom, pos, ref, alt_allele, line, per_alt_calls)


def _source_record_lineage(info: str) -> dict | None:
    """Decode the router's immutable mapping from routed ALT indexes to raw source ALT indexes."""
    values = [
        item.partition("=")[2]
        for item in info.split(";")
        if item.partition("=")[0] == SOURCE_ROUTING_INFO_TAG
    ]
    if not values:
        return None
    if len(values) != 1:
        raise VCFValidationError("VCF record has duplicate SIRALOOM_SOURCE lineage payloads")
    encoded = values[0]
    try:
        if re.fullmatch(r"[A-Za-z0-9_-]+", encoded) is None:
            raise ValueError("invalid base64 alphabet")
        padded = encoded + ("=" * (-len(encoded) % 4))
        decoded = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        payload = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VCFValidationError("VCF record has malformed SIRALOOM_SOURCE lineage payload") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "1":
        raise VCFValidationError("VCF record has an unsupported SIRALOOM_SOURCE lineage schema")
    try:
        source_record_index = payload["source_record_index"]
        source_alt_count = payload["source_alt_count"]
        indexes = payload["normalized_alt_source_indexes"]
        source_record_sha256 = payload["source_record_sha256"]
    except KeyError as exc:
        raise VCFValidationError("VCF record has incomplete SIRALOOM_SOURCE lineage fields") from exc
    if (
        not isinstance(source_record_index, int)
        or isinstance(source_record_index, bool)
        or source_record_index < 1
        or not isinstance(source_alt_count, int)
        or isinstance(source_alt_count, bool)
        or source_alt_count < 1
        or not isinstance(indexes, list)
        or not indexes
        or any(not isinstance(index, int) or isinstance(index, bool) for index in indexes)
        or len(set(indexes)) != len(indexes)
        or any(index < 1 or index > source_alt_count for index in indexes)
        or not isinstance(source_record_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_record_sha256) is None
    ):
        raise VCFValidationError("VCF record has invalid SIRALOOM_SOURCE lineage values")
    return {
        "source_record_index": source_record_index,
        "source_record_sha256": source_record_sha256,
        "source_alt_count": source_alt_count,
        "normalized_alt_source_indexes": indexes,
    }


def _source_record_mapping(info: str) -> tuple[int, int] | None:
    """Return (source ALT index, source ALT count) from SIRALOOM_ORIG."""
    values = [
        item.partition("=")[2]
        for item in info.split(";")
        if item.partition("=")[0] == SOURCE_RECORD_INFO_TAG
    ]
    if not values:
        return None
    if len(values) != 1:
        raise VCFValidationError("Normalized VCF record has duplicate SIRALOOM_ORIG mappings")
    mapping = values[0].split("|", 4)
    if len(mapping) not in {4, 5}:
        raise VCFValidationError("Invalid source-record mapping: malformed SIRALOOM_ORIG mapping")
    alternates = mapping[3].split(",")
    try:
        source_position = int(mapping[1])
        alt_index = int(mapping[4]) if len(mapping) == 5 else 1
    except ValueError as exc:
        raise VCFValidationError("Invalid source-record mapping: invalid position or ALT index") from exc
    if (
        not mapping[0]
        or source_position < 1
        or not mapping[2]
        or not alternates
        or (len(mapping) == 4 and len(alternates) != 1)
        or alt_index < 1
        or alt_index > len(alternates)
    ):
        raise VCFValidationError("Invalid source-record mapping: out-of-range SIRALOOM_ORIG ALT index")
    return alt_index, len(alternates)


def _sample_calls_for_alt(
    sample_calls: dict[str, dict],
    *,
    source_alt_index: int,
    source_alt_count: int,
) -> dict[str, dict]:
    """Add a source-aware per-ALT dosage projection without inventing REF alleles.

    The source GT and FORMAT values remain authoritative and unchanged. A
    conventional biallelic GT is emitted only when every called source allele
    is either REF or this record's selected ALT. Other ALT alleles remain
    explicit OTHER_ALT states and make that conventional projection unavailable.
    """
    projected: dict[str, dict] = {}
    for sample_name, source_call in sample_calls.items():
        call = dict(source_call)
        source_genotype = call.get("source_genotype")
        if source_genotype is None and "source_genotype" not in call:
            source_genotype = call.get("genotype")
        selected_source_alt_index = call.get("source_alt_index") or source_alt_index
        original_alt_count = call.get("source_alt_count") or source_alt_count
        call["source_genotype"] = source_genotype
        call["source_alt_index"] = selected_source_alt_index
        call["source_alt_count"] = original_alt_count
        call["source_zygosity"] = (
            _zygosity(source_genotype)
            if source_genotype is not None
            else "GENOTYPE_UNAVAILABLE"
        )
        call.update({
            "projected_genotype": None,
            "projected_zygosity": None,
            "projected_phase": call.get("phase", "UNSPECIFIED"),
            "projected_status": "GENOTYPE_UNAVAILABLE",
            "projection_status": "GENOTYPE_UNAVAILABLE",
            "reference_allele_dosage": 0,
            "selected_alt_dosage": 0,
            "other_alt_dosage": 0,
            "missing_allele_count": 0,
            "projected_allele_states": [],
        })
        if source_genotype is None or source_genotype == "":
            call["projection_status"] = "GENOTYPE_UNAVAILABLE"
            call["projected_status"] = "GENOTYPE_UNAVAILABLE"
            projected[sample_name] = call
            continue
        if (
            not isinstance(selected_source_alt_index, int)
            or not isinstance(original_alt_count, int)
            or selected_source_alt_index < 1
            or selected_source_alt_index > original_alt_count
        ):
            call["projection_status"] = "INVALID_SOURCE_ALT_MAPPING"
            call["projected_status"] = "INVALID_SOURCE_ALT_MAPPING"
            projected[sample_name] = call
            continue

        # VCF 4.4/4.5 allow the first phasing indicator to be written
        # before the first allele (for example, |0/1/2). It is not a missing
        # allele; preserve it as a prefix while projecting the allele tokens.
        leading_phase_indicator = (
            source_genotype[0] if source_genotype[:1] in {"/", "|"} else ""
        )
        genotype_body = source_genotype[1:] if leading_phase_indicator else source_genotype
        if not genotype_body:
            call["projection_status"] = "INVALID_SOURCE_GT"
            call["projected_status"] = "INVALID_SOURCE_GT"
            projected[sample_name] = call
            continue
        tokens = re.split(r"([/|])", genotype_body)
        allele_positions = [i for i, token in enumerate(tokens) if token not in {"/", "|"}]
        normalized_genotype = call.get("normalized_genotype")
        if normalized_genotype not in {None, ""}:
            normalized_body = (
                normalized_genotype[1:]
                if normalized_genotype[:1] in {"/", "|"}
                else normalized_genotype
            )
            normalized_ploidy = len(re.split(r"[/|]", normalized_body)) if normalized_body else 0
            if normalized_ploidy != len(allele_positions):
                call["projection_status"] = "SOURCE_NORMALIZED_PLOIDY_MISMATCH"
                call["projected_status"] = "SOURCE_NORMALIZED_PLOIDY_MISMATCH"
                projected[sample_name] = call
                continue
        projected_tokens = list(tokens)
        states: list[str] = []
        contains_other_alt = False
        invalid_source_gt = False
        for token_index in allele_positions:
            token = tokens[token_index]
            if token in {"", "."}:
                state = "MISSING"
                call["missing_allele_count"] += 1
                projected_tokens[token_index] = "."
            elif token.isdigit():
                allele_index = int(token)
                if allele_index == 0:
                    state = "REFERENCE"
                    call["reference_allele_dosage"] += 1
                    projected_tokens[token_index] = "0"
                elif 1 <= allele_index <= original_alt_count:
                    if allele_index == selected_source_alt_index:
                        state = "SELECTED_ALT"
                        call["selected_alt_dosage"] += 1
                        projected_tokens[token_index] = "1"
                    else:
                        state = "OTHER_ALT"
                        call["other_alt_dosage"] += 1
                        contains_other_alt = True
                        # Never encode a different ALT as reference or missing.
                        projected_tokens[token_index] = token
                else:
                    state = "INVALID"
                    invalid_source_gt = True
                    projected_tokens[token_index] = token
            else:
                state = "INVALID"
                invalid_source_gt = True
                projected_tokens[token_index] = token
            states.append(state)

        call["projected_allele_states"] = states
        if invalid_source_gt:
            call["projection_status"] = "INVALID_SOURCE_GT"
            call["projected_status"] = "INVALID_SOURCE_GT"
        elif contains_other_alt and call["missing_allele_count"]:
            call["projection_status"] = "CONTAINS_OTHER_ALT_AND_MISSING"
            call["projected_status"] = "CONTAINS_OTHER_ALT_AND_MISSING"
        elif contains_other_alt:
            call["projection_status"] = "CONTAINS_OTHER_ALT"
            call["projected_status"] = "CONTAINS_OTHER_ALT"
        else:
            projected_genotype = leading_phase_indicator + "".join(projected_tokens)
            call["projected_genotype"] = projected_genotype
            call["projected_zygosity"] = _zygosity(projected_genotype)
            if call["missing_allele_count"] == len(allele_positions):
                status = "NO_CALL"
            elif call["missing_allele_count"]:
                status = "PARTIAL_CALL"
            else:
                status = "AVAILABLE"
            call["projection_status"] = status
            call["projected_status"] = status
        projected[sample_name] = call
    return projected


def _zygosity(genotype: str | None) -> str:
    if not genotype or genotype == ".":
        return "NO_CALL"
    # VCFv4.4+ permits a leading phase separator before the first allele.
    # Strict version-aware validation decides whether the input version permits it.
    if genotype[:1] in {"/", "|"}:
        genotype = genotype[1:]
    alleles = re.split(r"[/|]", genotype)
    if not genotype or any(allele == "" for allele in alleles):
        return "INVALID_CALL"
    if not alleles:
        return "INVALID_CALL"
    if all(allele == "." for allele in alleles):
        return "NO_CALL"
    if any(allele == "." for allele in alleles):
        return "PARTIAL_CALL"
    try:
        indexes = [int(allele) for allele in alleles]
    except ValueError:
        return "INVALID_CALL"
    if any(index < 0 for index in indexes):
        return "INVALID_CALL"
    if all(index == 0 for index in indexes):
        return "HOMOZYGOUS_REFERENCE" if len(indexes) > 1 else "REFERENCE_CALL"
    if len(indexes) == 1:
        return "HAPLOID_ALTERNATE"
    if all(index != 0 for index in indexes):
        return "HOMOZYGOUS_ALTERNATE" if len(set(indexes)) == 1 else "MULTIPLE_ALTERNATE_ALLELES"
    return "HETEROZYGOUS"

def validate_and_extract(
    path: str,
    genome_build: str,
    *,
    sample_name: str | None = None,
) -> list[CanonicalVariant]:
    records = list(parse_vcf(path, sample_name=sample_name))
    if not records:
        raise VCFValidationError("VCF contains no variant records")
    variants = []
    for r in records:
        variants.append(CanonicalVariant(
            genome_build=genome_build,
            chromosome=r.chrom,
            position=r.pos,
            reference=r.ref,
            alternate=r.alt,
        ))
    return variants
