from __future__ import annotations

import gzip
import re
from pathlib import Path

SUPPORTED_VCF_VERSIONS = {"VCFv4.2", "VCFv4.3"}
STANDARD_COLUMNS = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO"]
DNA_RE = re.compile(r"^[ACGTN]+$")
SYMBOLIC_RE = re.compile(r"^<[^>]+>$")
BREAKEND_RE = re.compile(
    r"^(?:[ACGTNacgtn.]+(?P<left>[\[\]])[^:\[\]]+:[1-9][0-9]*(?P=left)|"
    r"(?P<right>[\[\]])[^:\[\]]+:[1-9][0-9]*(?P=right)[ACGTNacgtn.]+)$"
)


class StrictVCFValidationError(ValueError):
    def __init__(self, message: str, *, code: str = "VCF_INVALID"):
        super().__init__(message)
        self.code = code


def _open(path: str | Path):
    p = Path(path)
    return gzip.open(p, "rt", encoding="utf-8") if p.name.lower().endswith((".gz", ".bgz")) else open(p, "rt", encoding="utf-8")


def _validate_info(value: str, line_no: int) -> None:
    if value == ".":
        return
    if not value:
        raise StrictVCFValidationError(f"INFO is empty at line {line_no}", code="VCF_INFO_INVALID")
    for item in value.split(";"):
        if not item:
            raise StrictVCFValidationError(f"Empty INFO entry at line {line_no}", code="VCF_INFO_INVALID")
        if "=" in item:
            key, val = item.split("=", 1)
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]*", key) or val == "":
                raise StrictVCFValidationError(f"Malformed INFO entry at line {line_no}: {item!r}", code="VCF_INFO_INVALID")
        elif not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]*", item):
            raise StrictVCFValidationError(f"Malformed INFO flag at line {line_no}: {item!r}", code="VCF_INFO_INVALID")


def _info_values(value: str) -> dict[str, str | None]:
    if value == ".":
        return {}
    result: dict[str, str | None] = {}
    for item in value.split(";"):
        key, separator, raw = item.partition("=")
        result[key] = raw if separator else None
    return result


def _validate_structural_alt(alt: str, *, alt_index: int, alts: list[str], info: dict[str, str | None], pos: int, line_no: int) -> None:
    if alt in {"<NON_REF>", "<*>"} or alt == "*" or "[" in alt or "]" in alt:
        return
    if not SYMBOLIC_RE.fullmatch(alt):
        return
    end_value = info.get("END")
    if end_value is not None:
        try:
            end = int(end_value)
        except ValueError as exc:
            raise StrictVCFValidationError(f"Symbolic ALT has a non-integer END at line {line_no}", code="VCF_SV_INVALID") from exc
        if end < pos:
            raise StrictVCFValidationError(f"Symbolic ALT END precedes POS at line {line_no}", code="VCF_SV_INVALID")
    svlen_value = info.get("SVLEN")
    svlen_values = svlen_value.split(",") if svlen_value is not None else []
    if svlen_value is not None and len(svlen_values) != len(alts):
        raise StrictVCFValidationError(f"SVLEN cardinality does not match ALT alleles at line {line_no}", code="VCF_SV_INVALID")
    svlen_for_alt = svlen_values[alt_index] if svlen_values else None
    if svlen_for_alt not in {None, "."}:
        try:
            int(svlen_for_alt)
        except ValueError as exc:
            raise StrictVCFValidationError(f"Symbolic ALT has a non-integer SVLEN at line {line_no}", code="VCF_SV_INVALID") from exc
    if end_value is None and svlen_for_alt in {None, "."}:
        raise StrictVCFValidationError(
            f"Symbolic structural ALT {alt} requires END or allele-specific SVLEN at line {line_no}",
            code="VCF_SV_SPAN_MISSING",
        )


def _deleted_reference_interval(pos: int, ref: str, alt: str) -> tuple[int, int] | None:
    prefix = 0
    while prefix < min(len(ref), len(alt)) and ref[prefix] == alt[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < len(ref) - prefix
        and suffix < len(alt) - prefix
        and ref[len(ref) - suffix - 1] == alt[len(alt) - suffix - 1]
    ):
        suffix += 1
    start = pos + prefix
    end = pos + len(ref) - suffix - 1
    return (start, end) if end >= start else None


def _validate_record(fields: list[str], line_no: int, reference_contigs: set[str] | None) -> tuple[str, int, list[str]]:
    if len(fields) < 8:
        raise StrictVCFValidationError(f"Expected at least 8 VCF columns at line {line_no}", code="VCF_RECORD_INVALID")
    chrom, pos_text, identifier, ref, alt, qual, filt, info = fields[:8]

    if not chrom or chrom.startswith("#"):
        raise StrictVCFValidationError(f"Invalid CHROM at line {line_no}", code="VCF_CHROM_INVALID")
    if reference_contigs is not None and chrom not in reference_contigs:
        raise StrictVCFValidationError(
            f"Contig {chrom!r} is not present in the selected reference package at line {line_no}",
            code="REFERENCE_CONTIG_MISMATCH",
        )

    try:
        pos = int(pos_text)
    except ValueError as exc:
        raise StrictVCFValidationError(f"Invalid POS at line {line_no}: {pos_text!r}", code="VCF_POS_INVALID") from exc
    if pos <= 0:
        raise StrictVCFValidationError(f"POS must be > 0 at line {line_no}", code="VCF_POS_INVALID")

    if identifier == "":
        raise StrictVCFValidationError(f"ID is empty at line {line_no}", code="VCF_ID_INVALID")
    if identifier != "." and any(not re.fullmatch(r"[A-Za-z0-9_.:-]+", x) for x in identifier.split(";")):
        raise StrictVCFValidationError(f"Malformed ID at line {line_no}: {identifier!r}", code="VCF_ID_INVALID")

    ref = ref.upper()
    if not DNA_RE.fullmatch(ref):
        raise StrictVCFValidationError(f"REF must contain only A/C/G/T/N for Phase 1 at line {line_no}", code="VCF_REF_INVALID")

    alts = [a.upper() for a in alt.split(",")]
    if not alt or any(
        not DNA_RE.fullmatch(a) and not SYMBOLIC_RE.fullmatch(a) and not BREAKEND_RE.fullmatch(a) and a != "*"
        for a in alts
    ):
        raise StrictVCFValidationError(f"Malformed ALT at line {line_no}: {alt!r}", code="VCF_ALT_INVALID")

    if qual != ".":
        try:
            q = float(qual)
        except ValueError as exc:
            raise StrictVCFValidationError(f"Invalid QUAL at line {line_no}: {qual!r}", code="VCF_QUAL_INVALID") from exc
        if q < 0:
            raise StrictVCFValidationError(f"QUAL must be non-negative at line {line_no}", code="VCF_QUAL_INVALID")

    if filt != ".":
        if not filt or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", x) for x in filt.split(";")):
            raise StrictVCFValidationError(f"Malformed FILTER at line {line_no}: {filt!r}", code="VCF_FILTER_INVALID")

    _validate_info(info, line_no)
    info_values = _info_values(info)
    for alt_index, alternate in enumerate(alts):
        _validate_structural_alt(
            alternate, alt_index=alt_index, alts=alts, info=info_values, pos=pos, line_no=line_no,
        )
    if alts and all(alt in {"<NON_REF>", "<*>"} for alt in alts):
        end_value = info_values.get("END")
        if end_value is None:
            raise StrictVCFValidationError(f"GVCF reference block requires END at line {line_no}", code="VCF_GVCF_BLOCK_INVALID")
        try:
            if int(end_value) < pos:
                raise StrictVCFValidationError(f"GVCF block END precedes POS at line {line_no}", code="VCF_GVCF_BLOCK_INVALID")
        except ValueError as exc:
            raise StrictVCFValidationError(f"GVCF block END must be an integer at line {line_no}", code="VCF_GVCF_BLOCK_INVALID") from exc

    if len(fields) >= 9:
        fmt = fields[8]
        if not fmt:
            raise StrictVCFValidationError(f"FORMAT is empty at line {line_no}", code="VCF_FORMAT_INVALID")
        keys = fmt.split(":")
        if len(keys) != len(set(keys)) or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]*", k) for k in keys):
            raise StrictVCFValidationError(f"Malformed or duplicate FORMAT key at line {line_no}", code="VCF_FORMAT_INVALID")
        if "GT" in keys and keys[0] != "GT":
            raise StrictVCFValidationError(
                f"GT must be the first FORMAT key when present at line {line_no}",
                code="VCF_FORMAT_INVALID",
            )
        for sample_index, sample in enumerate(fields[9:], start=1):
            values = sample.split(":")
            if not sample or any(value == "" for value in values) or len(values) > len(keys):
                raise StrictVCFValidationError(
                    f"Sample {sample_index} has malformed FORMAT values for {len(keys)} keys at line {line_no}",
                    code="VCF_SAMPLE_INVALID",
                )
            # VCF permits trailing FORMAT fields to be omitted. A missing value
            # within the supplied values must still use the explicit '.' token.
            if "GT" in keys:
                gt = values[keys.index("GT")]
                if gt != ".":
                    for allele_index in re.split(r"[|/]", gt):
                        if allele_index == ".":
                            continue
                        try:
                            index = int(allele_index)
                        except ValueError as exc:
                            raise StrictVCFValidationError(
                                f"Invalid GT allele index at line {line_no}: {gt!r}",
                                code="VCF_GENOTYPE_INVALID",
                            ) from exc
                        if index < 0 or index > len(alts):
                            raise StrictVCFValidationError(
                                f"GT allele index {index} exceeds ALT count {len(alts)} at line {line_no}",
                                code="VCF_GENOTYPE_INVALID",
                            )

    return chrom, pos, alts


def validate_vcf_strict(path: str | Path, *, reference_contigs: set[str] | None = None) -> dict:
    fileformat: str | None = None
    chrom_header: list[str] | None = None
    found_header = False
    records = 0
    multiallelic = 0
    symbolic = 0
    breakends = 0
    gvcf_markers = 0
    singleton_headers: set[str] = set()
    deletion_intervals: dict[str, list[tuple[int, int, set[int] | None]]] = {}
    spanning_deletion_records: list[tuple[str, int, int, set[int] | None]] = []
    breakend_records_by_id: dict[str, dict] = {}
    breakend_links: list[tuple[str, str, int, set[str], list[tuple[str, int]], int]] = []

    with _open(path) as fh:
        for line_no, raw in enumerate(fh, 1):
            line = raw.rstrip("\n\r")
            if line_no == 1 and line.startswith("\ufeff"):
                raise StrictVCFValidationError(
                    "VCF files must not contain a UTF-8 byte-order mark",
                    code="VCF_BOM_FORBIDDEN",
                )
            if line_no == 1 and not line.startswith("##fileformat="):
                raise StrictVCFValidationError(
                    "The ##fileformat line must be the first line in a VCF file",
                    code="VCF_FILEFORMAT_POSITION_INVALID",
                )
            if not line:
                continue
            if line.startswith("##"):
                if line.startswith("##fileformat="):
                    if fileformat is not None:
                        raise StrictVCFValidationError("Duplicate ##fileformat header", code="VCF_HEADER_INVALID")
                    fileformat = line.split("=", 1)[1]
                if line.startswith("##ALT=<ID=NON_REF"):
                    gvcf_markers += 1
                continue
            if line.startswith("#CHROM"):
                if found_header:
                    raise StrictVCFValidationError("Duplicate #CHROM header", code="VCF_HEADER_INVALID")
                columns = line.split("\t")
                if len(columns) < 8 or columns[:8] != STANDARD_COLUMNS:
                    raise StrictVCFValidationError(
                        "The #CHROM header must begin with CHROM, POS, ID, REF, ALT, QUAL, FILTER, INFO",
                        code="VCF_HEADER_INVALID",
                    )
                if any(column == "" for column in columns):
                    raise StrictVCFValidationError(
                        "The #CHROM header cannot contain empty columns",
                        code="VCF_HEADER_INVALID",
                    )
                if len(columns) >= 9 and columns[8] != "FORMAT":
                    raise StrictVCFValidationError("Column 9 must be FORMAT when sample columns are present", code="VCF_HEADER_INVALID")
                if len(columns) > 9 and len(columns[9:]) != len(set(columns[9:])):
                    raise StrictVCFValidationError("Duplicate sample names are not allowed", code="VCF_SAMPLE_INVALID")
                chrom_header = columns
                found_header = True
                continue
            if line.startswith("#"):
                if line.startswith("##"):
                    continue
                if "=" in line:
                    key = line[2:].split("=", 1)[0]
                    if key in singleton_headers and key not in {"INFO", "FORMAT", "FILTER", "ALT", "contig"}:
                        raise StrictVCFValidationError(f"Duplicate singleton header: {key}", code="VCF_HEADER_INVALID")
                    singleton_headers.add(key)
                continue
            if not found_header:
                raise StrictVCFValidationError(
                    f"VCF data encountered before #CHROM at line {line_no}",
                    code="VCF_HEADER_INVALID",
                )
            fields = line.split("\t")
            if chrom_header is None or len(fields) != len(chrom_header):
                expected = len(chrom_header) if chrom_header is not None else 0
                raise StrictVCFValidationError(
                    f"VCF record has {len(fields)} columns but the #CHROM header declares {expected} at line {line_no}",
                    code="VCF_RECORD_INVALID",
                )
            _chrom, _pos, alts = _validate_record(fields, line_no, reference_contigs)
            info_values = _info_values(fields[7])
            breakend_alts = [alt for alt in alts if "[" in alt or "]" in alt]
            if breakend_alts:
                if info_values.get("SVTYPE") != "BND":
                    raise StrictVCFValidationError(
                        f"Breakend ALT requires INFO/SVTYPE=BND at line {line_no}",
                        code="VCF_BREAKEND_SVTYPE_INVALID",
                    )
                record_ids = set() if fields[2] == "." else set(fields[2].split(";"))
                mate_value = info_values.get("MATEID")
                mate_ids = set(mate_value.split(",")) if mate_value else set()
                # The ALT grammar above already requires one complete bracket
                # pair. Retain its remote coordinates for MATEID checks after
                # the whole file has been read; the VCF-defined orientations
                # are preserved but are not constrained by a local heuristic.
                remote_loci = [
                    (match.group(2), int(match.group(3)))
                    for alt in breakend_alts
                    for match in [re.search(r"([\[\]])([^:\[\]]+):([1-9][0-9]*)\1", alt)]
                    if match is not None
                ]
                if len(remote_loci) != len(breakend_alts):
                    raise StrictVCFValidationError(
                        f"Breakend ALT does not contain one unambiguous mate locus at line {line_no}",
                        code="VCF_BREAKEND_ALT_INVALID",
                    )
                if mate_ids:
                    if not record_ids:
                        raise StrictVCFValidationError(
                            f"Breakend with INFO/MATEID requires a non-missing record ID at line {line_no}",
                            code="VCF_BREAKEND_MATE_INVALID",
                        )
                    if len(mate_ids) != len(breakend_alts):
                        raise StrictVCFValidationError(
                            f"Breakend MATEID cardinality does not match breakend ALT alleles at line {line_no}",
                            code="VCF_BREAKEND_MATE_INVALID",
                        )
                    breakend_links.append((
                        fields[2], _chrom, _pos, mate_ids, remote_loci, line_no,
                    ))
                for record_id in record_ids:
                    if record_id in breakend_records_by_id:
                        raise StrictVCFValidationError(
                            f"Breakend record ID {record_id!r} is not unique at line {line_no}",
                            code="VCF_BREAKEND_MATE_INVALID",
                        )
                    breakend_records_by_id[record_id] = {
                        "chrom": _chrom,
                        "pos": _pos,
                        "remote_loci": remote_loci,
                        "mate_ids": mate_ids,
                        "line_no": line_no,
                    }
            format_keys = fields[8].split(":") if len(fields) > 8 else []
            gt_index = format_keys.index("GT") if "GT" in format_keys else None

            def carriers(alt_index: int) -> set[int] | None:
                if len(fields) <= 9 or gt_index is None:
                    return None
                result: set[int] = set()
                for sample_index, sample in enumerate(fields[9:]):
                    values = sample.split(":")
                    if gt_index >= len(values):
                        continue
                    gt = values[gt_index]
                    if gt == ".":
                        continue
                    try:
                        called = {int(item) for item in re.split(r"[/|]", gt) if item != "."}
                    except ValueError:
                        continue
                    if alt_index in called:
                        result.add(sample_index)
                return result

            if "*" in alts:
                spanning_deletion_records.append((_chrom, _pos, line_no, carriers(alts.index("*") + 1)))
            for alt_index, alternate in enumerate(alts, start=1):
                if DNA_RE.fullmatch(alternate):
                    interval = _deleted_reference_interval(_pos, fields[3].upper(), alternate)
                    if interval is not None:
                        deletion_intervals.setdefault(_chrom, []).append((*interval, carriers(alt_index)))
                elif alternate == "<DEL>":
                    structural_end = _info_values(fields[7]).get("END")
                    if structural_end is not None:
                        end = int(structural_end)  # checked by _validate_record
                        if end > _pos:
                            deletion_intervals.setdefault(_chrom, []).append(
                                (_pos + 1, end, carriers(alt_index))
                            )
            records += 1
            if len(alts) > 1:
                multiallelic += 1
            for alt in alts:
                if SYMBOLIC_RE.fullmatch(alt) or alt == "*":
                    symbolic += 1
                if "[" in alt or "]" in alt:
                    breakends += 1
                if alt == "<NON_REF>":
                    gvcf_markers += 1

    if fileformat not in SUPPORTED_VCF_VERSIONS:
        raise StrictVCFValidationError(
            f"Unsupported or missing ##fileformat header: {fileformat!r}; supported versions are VCFv4.2 and VCFv4.3",
            code="VCF_FILEFORMAT_UNSUPPORTED",
        )
    if not found_header or chrom_header is None:
        raise StrictVCFValidationError("VCF is missing the #CHROM header", code="VCF_HEADER_INVALID")
    if records == 0:
        raise StrictVCFValidationError("VCF contains no variant records", code="VCF_EMPTY")
    for source_id, chrom, pos, mate_ids, remote_loci, line_no in breakend_links:
        source_ids = set(source_id.split(";"))
        for mate_id in mate_ids:
            mate = breakend_records_by_id.get(mate_id)
            if mate is None:
                raise StrictVCFValidationError(
                    f"Breakend MATEID {mate_id!r} has no corresponding record at line {line_no}",
                    code="VCF_BREAKEND_MATE_MISSING",
                )
            if (mate["chrom"], mate["pos"]) not in remote_loci:
                raise StrictVCFValidationError(
                    f"Breakend MATEID {mate_id!r} does not match the ALT mate coordinate at line {line_no}",
                    code="VCF_BREAKEND_MATE_COORDINATE_MISMATCH",
                )
            if not (mate["mate_ids"] & source_ids):
                raise StrictVCFValidationError(
                    f"Breakend MATEID {mate_id!r} does not refer back to record {source_id!r} at line {line_no}",
                    code="VCF_BREAKEND_MATE_NOT_RECIPROCAL",
                )
            if not any(
                (remote_chrom, remote_pos) == (chrom, pos)
                for remote_chrom, remote_pos in mate["remote_loci"]
            ):
                raise StrictVCFValidationError(
                    f"Breakend mate record {mate_id!r} does not point back to {chrom}:{pos} at line {line_no}",
                    code="VCF_BREAKEND_MATE_COORDINATE_MISMATCH",
                )
    for chrom, pos, line_no, star_carriers in spanning_deletion_records:
        if star_carriers is not None and not star_carriers:
            continue
        overlaps = [
            deletion_carriers
            for start, end, deletion_carriers in deletion_intervals.get(chrom, ())
            if start <= pos <= end
        ]
        context_exists = any(
            deletion_carriers is None
            or bool(star_carriers & deletion_carriers)
            for deletion_carriers in overlaps
        )
        if not overlaps or not context_exists:
            raise StrictVCFValidationError(
                f"Spanning-deletion ALT '*' has no overlapping deletion record on {chrom} at line {line_no}",
                code="VCF_SPANNING_DELETION_CONTEXT_MISSING",
            )

    return {
        "fileformat": fileformat,
        "records": records,
        "multiallelic_records": multiallelic,
        "symbolic_records": symbolic,
        "breakend_records": breakends,
        "gvcf_markers": gvcf_markers,
        "sample_count": max(0, len(chrom_header) - 9),
        "reference_contig_policy": "EXACT" if reference_contigs is not None else "NOT_CHECKED",
    }


def validate_vcf_reference_alleles(path: str | Path, reference_fasta: str | Path) -> dict:
    """Check every source record's REF and reference-span coordinates.

    This deliberately includes records routed away from sequence normalization
    (GVCF blocks, symbolic SVs, breakends, and spanning-deletion records), so a
    successful partial analysis cannot conceal a selected-reference mismatch.
    """
    from backend.app.domain.reference import FastaReference, ReferenceError

    checked_records = 0
    checked_breakend_mates = 0
    try:
        with FastaReference(reference_fasta) as reference, _open(path) as handle:
            for line_no, raw in enumerate(handle, 1):
                if not raw or raw.startswith("#"):
                    continue
                fields = raw.rstrip("\r\n").split("\t")
                if len(fields) < 8:
                    continue  # validate_vcf_strict reports the structural error first.
                chrom, pos_text, _identifier, ref, alt_text = fields[:5]
                pos = int(pos_text)
                try:
                    observed = reference.fetch(chrom, pos - 1, pos - 1 + len(ref))
                except ReferenceError as exc:
                    raise StrictVCFValidationError(
                        f"Reference interval is invalid at {chrom}:{pos} line {line_no}: {exc}",
                        code="VCF_REFERENCE_COORDINATE_INVALID",
                    ) from exc
                if observed != ref.upper():
                    raise StrictVCFValidationError(
                        f"Reference allele mismatch at {chrom}:{pos} line {line_no}: "
                        f"VCF REF={ref.upper()}, selected reference={observed}",
                        code="VCF_REFERENCE_MISMATCH",
                    )
                contig_length = reference.contig_length(chrom)
                info = _info_values(fields[7])
                if info.get("END") is not None:
                    end = int(info["END"])
                    if end > contig_length:
                        raise StrictVCFValidationError(
                            f"Reference span END={end} exceeds contig {chrom} length {contig_length} at line {line_no}",
                            code="VCF_REFERENCE_SPAN_OUT_OF_BOUNDS",
                        )
                for alt in alt_text.split(","):
                    if "[" not in alt and "]" not in alt:
                        continue
                    match = re.search(r"[\[\]]([^:\[\]]+):([1-9][0-9]*)[\[\]]", alt)
                    if match is None:
                        continue
                    mate_contig, mate_position = match.group(1), int(match.group(2))
                    try:
                        mate_length = reference.contig_length(mate_contig)
                    except ReferenceError as exc:
                        raise StrictVCFValidationError(
                            f"Breakend mate contig {mate_contig!r} is absent from the selected reference at line {line_no}",
                            code="VCF_BREAKEND_REFERENCE_MISMATCH",
                        ) from exc
                    if mate_position > mate_length:
                        raise StrictVCFValidationError(
                            f"Breakend mate coordinate {mate_contig}:{mate_position} exceeds selected reference length {mate_length} at line {line_no}",
                            code="VCF_BREAKEND_REFERENCE_MISMATCH",
                        )
                    checked_breakend_mates += 1
                checked_records += 1
    except ReferenceError as exc:
        raise StrictVCFValidationError(
            f"Selected reference cannot validate VCF REF alleles: {exc}",
            code="REFERENCE_PACKAGE_INVALID",
        ) from exc
    return {
        "checked_record_count": checked_records,
        "checked_breakend_mate_count": checked_breakend_mates,
        "reference_fasta": str(reference_fasta),
        "result": "PASS",
    }
