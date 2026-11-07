from __future__ import annotations

import gzip
import hashlib
import re
import struct
import zlib
from contextlib import contextmanager
from math import comb, isnan
from pathlib import Path

SUPPORTED_VCF_VERSIONS = frozenset({f"VCFv4.{minor}" for minor in range(0, 6)})
VCF41_42_RESERVED_INFO_IDS = frozenset({
    "AA", "AC", "AF", "AN", "BQ", "CIGAR", "DB", "DP", "END",
    "H2", "H3", "MQ", "MQ0", "NS", "SB", "SOMATIC", "VALIDATED", "1000G",
})
STANDARD_COLUMNS = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO"]
DNA_RE = re.compile(r"^[ACGTN]+$")
VCF_CONTIG_NAME_RE = re.compile(
    r"^[0-9A-Za-z!#$%&+./:;?@^_|~-][0-9A-Za-z!#$%&*+./:;=?@^_|~-]*$"
)
SYMBOLIC_RE = re.compile(r"^<[^<>,\s]+>$")
BREAKEND_RE = re.compile(
    r"^(?:[ACGTNacgtn.]+(?P<left>[\[\]])[^:\[\]\s]+:[0-9]+(?P=left)|"
    r"(?P<right>[\[\]])[^:\[\]\s]+:[0-9]+(?P=right)[ACGTNacgtn.]+)$"
)
SINGLE_BREAKEND_RE = re.compile(r"^(?:\.[ACGTNacgtn]+|[ACGTNacgtn]+\.)$")


def _is_vcf45_breakend_alt(allele: str) -> bool:
    """Identify paired and single VCFv4.5 breakpoint-notation alleles."""
    return "[" in allele or "]" in allele or bool(SINGLE_BREAKEND_RE.fullmatch(allele))


def _is_vcf44_plus_sv_or_breakend_alt(allele: str) -> bool:
    """Identify VCFv4.5 symbolic SVs and paired or single breakend alleles."""
    if _is_vcf45_breakend_alt(allele):
        return True
    match = re.fullmatch(r"<([A-Z]+)(?::[^<>]+)?>", allele)
    return match is not None and match.group(1) in {"DEL", "INS", "DUP", "INV", "CNV"}


def _breakend_orientation_details(allele: str) -> dict[str, str] | None:
    """Describe the four VCF breakend replacement orientations without inferring sequence."""
    match = BREAKEND_RE.fullmatch(allele)
    if match is None:
        return None
    bracket = match.group("left") or match.group("right")
    if allele[0] in "[]":
        closing = allele.find(bracket, 1)
        local_replacement = allele[closing + 1 :]
        joined_side = "BEFORE_LOCAL_REPLACEMENT"
    else:
        opening = allele.find(bracket)
        local_replacement = allele[:opening]
        joined_side = "AFTER_LOCAL_REPLACEMENT"
    return {
        "remote_piece_direction": "RIGHT" if bracket == "[" else "LEFT",
        "remote_piece_reverse_complemented": (
            "true"
            if (bracket == "]" and joined_side == "AFTER_LOCAL_REPLACEMENT")
            or (bracket == "[" and joined_side == "BEFORE_LOCAL_REPLACEMENT")
            else "false"
        ),
        "joined_side": joined_side,
        "local_replacement": local_replacement,
        "bracket": bracket,
    }


def _breakend_remote_coordinate_within_cipos(
    remote_locus: tuple[str, int], target_record: dict, target_alt_index: int
) -> bool:
    """Check a BND remote coordinate against the target ALT's POS/CIPOS interval."""
    remote_chrom, remote_position = remote_locus
    if remote_chrom != target_record["chrom"]:
        return False
    interval = target_record["cipos_by_alt"].get(target_alt_index, (0, 0))
    if interval is None:
        # Explicitly missing CIPOS means the target uncertainty is unresolved.
        return True
    lower_offset, upper_offset = interval
    return target_record["pos"] + lower_offset <= remote_position <= target_record["pos"] + upper_offset

def _alt_identity_key(allele: str) -> tuple[str, ...]:
    """Return VCF allele identity while respecting sequence and contig case rules."""
    if DNA_RE.fullmatch(allele):
        return ("SEQUENCE", allele.upper())
    if SINGLE_BREAKEND_RE.fullmatch(allele):
        return ("SINGLE_BREAKEND", allele.upper())
    if BREAKEND_RE.fullmatch(allele):
        if allele[0] in "[]":
            bracket = allele[0]
            closing = allele.find(bracket, 1)
            locus = allele[1:closing]
            contig, position = locus.rsplit(":", 1)
            inserted_sequence = allele[closing + 1 :]
            return ("BREAKEND", bracket, contig, position, inserted_sequence.upper())
        opening = next(index for index, character in enumerate(allele) if character in "[]")
        bracket = allele[opening]
        locus = allele[opening + 1 : -1]
        contig, position = locus.rsplit(":", 1)
        inserted_sequence = allele[:opening]
        return ("BREAKEND", inserted_sequence.upper(), bracket, contig, position)
    # Symbolic allele IDs and remote contig names are case-sensitive.
    return ("LITERAL", allele)

FORBIDDEN_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
INFO_KEY_RE = re.compile(r"(?:[A-Za-z_][0-9A-Za-z_.]*|1000G)\Z")
FORMAT_KEY_RE = re.compile(r"[A-Za-z_][0-9A-Za-z_.]*\Z")
INVALID_PERCENT_ESCAPE_RE = re.compile(r"%(?![0-9A-F]{2})")

NONNEGATIVE_INTEGER_FIELDS = frozenset({
    ("INFO", "AC"), ("INFO", "AD"), ("INFO", "ADF"), ("INFO", "ADR"),
    ("INFO", "AN"), ("INFO", "DP"), ("INFO", "MQ0"), ("INFO", "NS"),
    ("INFO", "SB"), ("INFO", "HOMLEN"),
    ("FORMAT", "AD"), ("FORMAT", "ADF"), ("FORMAT", "ADR"),
    ("FORMAT", "DP"), ("FORMAT", "EC"), ("FORMAT", "GQ"),
    ("FORMAT", "HQ"), ("FORMAT", "LAD"), ("FORMAT", "LADF"),
    ("FORMAT", "LADR"), ("FORMAT", "LEC"), ("FORMAT", "LPL"),
    ("FORMAT", "LPP"), ("FORMAT", "MQ"), ("FORMAT", "PL"),
    ("FORMAT", "PP"), ("FORMAT", "PQ"), ("FORMAT", "PS"), ("FORMAT", "NQ"),
    ("FORMAT", "PSO"), ("FORMAT", "PSQ"),
})
PROBABILITY_FLOAT_FIELDS = frozenset({("INFO", "AF"), ("FORMAT", "GP"), ("FORMAT", "CNP")})
NONNEGATIVE_FLOAT_FIELDS = frozenset({("INFO", "BQ"), ("INFO", "MQ"), ("FORMAT", "CNQ")})
_CONTIG_ID = re.compile(r'(?:^|,)ID=(?:"([^"]+)"|([^,>]+))')
_CONTIG_LENGTH = re.compile(r'(?:^|,)length=([0-9]+)(?:,|>)')
_CONTIG_MD5 = re.compile(r'(?:^|,)md5=([^,>]+)(?:,|>)')

VCF45_BASE_MODIFICATION_FLOAT_ALIASES = frozenset({
    "M5mC", "M5hmC", "M5fC", "M5caC", "M5hmU", "M5fU",
    "M5caU", "M6mA", "M8oxoG", "MXaoN", "MxaoN",
})
VCF45_BASE_MODIFICATION_DEPTH_ALIASES = frozenset({
    "DPM5mC", "DPM5hmC", "DPM5fC", "DPM5caC", "DPM5hmU",
    "DPM5fU", "DPM5caU", "DPM6mA", "DPM8oxoG", "DPMXaoN",
    "DPMxaoN", "ADM5mC", "ADM5hmC", "ADM5fC", "ADM5caC",
    "ADM5hmU", "ADM5fU", "ADM5caU", "ADM6mA", "ADM8oxoG",
    "ADMXaoN", "ADMxaoN",
})


def _base_modification_field_kind(field_id: str) -> str | None:
    if (
        re.fullmatch(r"M[0-9]+[ACGTUN]", field_id)
        or field_id in VCF45_BASE_MODIFICATION_FLOAT_ALIASES
    ):
        return "fraction"
    if (
        re.fullmatch(r"(?:DPM|ADM)[0-9]+[ACGTUN]", field_id)
        or field_id in VCF45_BASE_MODIFICATION_DEPTH_ALIASES
    ):
        return "depth"
    return None


def _reserved_base_modification_format_definition(field_id: str) -> dict[str, str] | None:
    """Return the VCFv4.5 built-in definition for reserved base-modification keys."""
    field_kind = _base_modification_field_kind(field_id)
    if field_kind == "fraction":
        return {"Number": "M", "Type": "Float"}
    if field_kind == "depth":
        return {"Number": "M", "Type": "Integer"}
    return None


def _reserved_vcf40_format_definition(field_id: str) -> dict[str, str] | None:
    """Return the historical VCFv4.0 implicit FORMAT field definition."""
    reserved = {
        "GT": ("1", "String"),
        "DP": ("1", "Integer"),
        "FT": ("1", "String"),
        "GL": ("3", "Float"),
        # VCFv4.0 prose describes GQ and HQ as Numeric. The example header
        # uses Integer, while the field descriptions permit numeric values.
        "GQ": ("1", "Numeric"),
        "HQ": ("2", "Numeric"),
    }
    definition = reserved.get(field_id)
    if definition is None:
        return None
    return {"Number": definition[0], "Type": definition[1]}


def _reserved_vcf41_42_format_definition(field_id: str) -> dict[str, str] | None:
    """Return VCFv4.1/4.2 prose-defined reserved FORMAT wire definitions."""
    reserved = {
        "GT": ("1", "String"),
        "DP": ("1", "Integer"),
        "FT": ("1", "String"),
        "GL": ("G", "Float"),
        "PL": ("G", "Integer"),
        "GP": ("G", "Float"),
        "GQ": ("1", "Integer"),
        "HQ": ("2", "Integer"),
        "PS": ("1", "Integer"),
        "PQ": ("1", "Integer"),
        "EC": ("A", "Integer"),
        "MQ": ("1", "Integer"),
    }
    definition = reserved.get(field_id)
    return {"Number": definition[0], "Type": definition[1]} if definition else None


def _reserved_vcf43_format_definition(field_id: str) -> dict[str, str] | None:
    """Return VCFv4.3 Table 6 reserved FORMAT definitions."""
    reserved = {
        "AD": ("R", "Integer"), "ADF": ("R", "Integer"), "ADR": ("R", "Integer"),
        "DP": ("1", "Integer"), "EC": ("A", "Integer"), "FT": ("1", "String"),
        "GL": ("G", "Float"), "GP": ("G", "Float"), "GQ": ("1", "Integer"),
        "GT": ("1", "String"), "HQ": ("2", "Integer"), "MQ": ("1", "Integer"),
        "PL": ("G", "Integer"), "PP": ("G", "Integer"), "PQ": ("1", "Integer"),
        "PS": ("1", "Integer"),
        "CN": ("1", "Integer"), "CNQ": ("1", "Float"), "CNL": ("G", "Float"),
        "CNP": ("G", "Float"), "NQ": ("1", "Integer"), "HAP": ("1", "Integer"),
        "AHAP": ("1", "Integer"),
    }
    definition = reserved.get(field_id)
    return {"Number": definition[0], "Type": definition[1]} if definition else None


def _reserved_vcf44_format_definition(field_id: str) -> dict[str, str] | None:
    """Return VCFv4.4 Table 7 and structural FORMAT definitions."""
    # CN changes from Integer in VCFv4.3 to Float in VCFv4.4.
    if field_id == "CN":
        return {"Number": "1", "Type": "Float"}
    definition = _reserved_vcf43_format_definition(field_id)
    if definition is not None:
        return definition
    reserved = {
        "PSL": ("P", "String"), "PSO": ("P", "Integer"), "PSQ": ("P", "Integer"),
        "CN": ("1", "Float"), "CICN": ("2", "Float"), "CNQ": ("1", "Float"),
        "CNL": ("G", "Float"), "CNP": ("G", "Float"), "NQ": ("1", "Integer"),
        "HAP": ("1", "Integer"), "AHAP": ("1", "Integer"),
    }
    value = reserved.get(field_id)
    return {"Number": value[0], "Type": value[1]} if value else None


def _reserved_format_definition_for_version(
    fileformat: str, field_id: str
) -> dict[str, str] | None:
    if fileformat == "VCFv4.0":
        return _reserved_vcf40_format_definition(field_id)
    if fileformat in {"VCFv4.1", "VCFv4.2"}:
        return _reserved_vcf41_42_format_definition(field_id)
    if fileformat == "VCFv4.3":
        return _reserved_vcf43_format_definition(field_id)
    if fileformat == "VCFv4.4":
        return _reserved_vcf44_format_definition(field_id)
    if fileformat == "VCFv4.5":
        return _reserved_vcf45_format_definition(field_id)
    return None


def _reserved_vcf45_format_definition(field_id: str) -> dict[str, str] | None:
    # VCFv4.5 Table of reserved genotype keys. Enforce the declared wire
    # cardinality/type even when a caller omits a redundant FORMAT header line.
    reserved = {
        "AD": ("R", "Integer"),
        "ADF": ("R", "Integer"),
        "ADR": ("R", "Integer"),
        "DP": ("1", "Integer"),
        "EC": ("A", "Integer"),
        "FT": ("1", "String"),
        "GL": ("G", "Float"),
        "GP": ("G", "Float"),
        "GQ": ("1", "Integer"),
        "GT": ("1", "String"),
        "HQ": ("2", "Integer"),
        "LA": (".", "Integer"),
        "LAA": (".", "Integer"),
        "LAD": ("LR", "Integer"),
        "LADF": ("LR", "Integer"),
        "LADR": ("LR", "Integer"),
        "LEC": ("LA", "Integer"),
        "LGL": ("LG", "Float"),
        "LGP": ("LG", "Float"),
        "LPL": ("LG", "Integer"),
        "LPP": ("LG", "Integer"),
        "LEN": ("1", "Integer"),
        "MQ": ("1", "Integer"),
        "PL": ("G", "Integer"),
        "PP": ("G", "Integer"),
        "PQ": ("1", "Integer"),
        "PS": ("1", "Integer"),
        "PSL": ("P", "String"),
        "PSO": ("P", "Integer"),
        "PSQ": ("P", "Integer"),
        # VCFv4.5 structural-variant FORMAT keys (section sv-format-keys).
        "CN": ("1", "Float"),
        "CICN": ("2", "Float"),
        "CNQ": ("1", "Float"),
        "CNL": ("G", "Float"),
        "CNP": ("G", "Float"),
        "NQ": ("1", "Integer"),
        "HAP": ("1", "Integer"),
        "AHAP": ("1", "Integer"),
    }
    definition = reserved.get(field_id)
    if definition is not None:
        return {"Number": definition[0], "Type": definition[1]}
    return _reserved_base_modification_format_definition(field_id)


def _reserved_vcf43_info_definition(field_id: str) -> dict[str, str] | None:
    """Return VCFv4.3 reserved INFO table and structural-field definitions."""
    reserved = {
        "AA": ("1", "String"), "AC": ("A", "Integer"), "AD": ("R", "Integer"),
        "ADF": ("R", "Integer"), "ADR": ("R", "Integer"), "AF": ("A", "Float"),
        "AN": ("1", "Integer"), "BQ": ("1", "Float"), "CIGAR": ("A", "String"),
        "DB": ("0", "Flag"), "DP": ("1", "Integer"), "END": ("1", "Integer"),
        "H2": ("0", "Flag"), "H3": ("0", "Flag"), "MQ": ("1", "Float"),
        "MQ0": ("1", "Integer"), "NS": ("1", "Integer"), "SB": ("4", "Integer"),
        "SOMATIC": ("0", "Flag"), "VALIDATED": ("0", "Flag"), "1000G": ("0", "Flag"),
        "IMPRECISE": ("0", "Flag"), "NOVEL": ("0", "Flag"), "SVTYPE": ("1", "String"),
        "SVLEN": (".", "Integer"), "CIPOS": ("2", "Integer"), "CIEND": ("2", "Integer"),
        "HOMLEN": (".", "Integer"), "HOMSEQ": (".", "String"), "BKPTID": (".", "String"),
        "MEINFO": ("4", "String"), "METRANS": ("4", "String"),
        "DGVID": ("1", "String"), "DBVARID": ("1", "String"), "DBRIPID": ("1", "String"),
        "MATEID": (".", "String"), "PARID": ("1", "String"), "EVENT": ("1", "String"),
        "CILEN": ("2", "Integer"), "DPADJ": (".", "Integer"), "CN": ("1", "Integer"),
        "CNADJ": (".", "Integer"), "CICN": ("2", "Integer"), "CICNADJ": (".", "Integer"),
    }
    definition = reserved.get(field_id)
    return {"Number": definition[0], "Type": definition[1]} if definition else None


def _reserved_vcf44_info_definition(field_id: str) -> dict[str, str] | None:
    """Return VCFv4.4 reserved INFO table and structural-field definitions."""
    reserved = {
        "AA": ("1", "String"), "AC": ("A", "Integer"), "AD": ("R", "Integer"),
        "ADF": ("R", "Integer"), "ADR": ("R", "Integer"), "AF": ("A", "Float"),
        "AN": ("1", "Integer"), "BQ": ("1", "Float"), "CIGAR": ("A", "String"),
        "DB": ("0", "Flag"), "DP": ("1", "Integer"), "END": ("1", "Integer"),
        "H2": ("0", "Flag"), "H3": ("0", "Flag"), "MQ": ("1", "Float"),
        "MQ0": ("1", "Integer"), "NS": ("1", "Integer"), "SB": ("4", "Integer"),
        "SOMATIC": ("0", "Flag"), "VALIDATED": ("0", "Flag"), "1000G": ("0", "Flag"),
        "IMPRECISE": ("0", "Flag"), "NOVEL": ("0", "Flag"), "SVTYPE": ("1", "String"),
        "SVLEN": ("A", "Integer"), "CIPOS": (".", "Integer"), "CIEND": (".", "Integer"),
        "HOMLEN": ("A", "Integer"), "HOMSEQ": ("A", "String"), "BKPTID": ("A", "String"),
        "MEINFO": (".", "String"), "METRANS": (".", "String"),
        "DGVID": ("A", "String"), "DBVARID": ("A", "String"), "DBRIPID": ("A", "String"),
        "MATEID": ("A", "String"), "PARID": ("A", "String"), "EVENT": ("A", "String"),
        "EVENTTYPE": ("A", "String"),
        "CILEN": (".", "Integer"),
        "CN": ("A", "Float"), "CICN": (".", "Float"), "SVCLAIM": ("A", "String"),
        "RN": ("A", "Integer"), "RUS": (".", "String"), "RUL": (".", "Integer"),
        "RUC": (".", "Float"), "RB": (".", "Integer"), "CIRUC": (".", "Float"),
        "CIRB": (".", "Integer"), "RUB": (".", "Integer"), "CILEN": (".", "Integer"),
                "CN": ("A", "Float"), "CICN": (".", "Float"), "SVCLAIM": ("A", "String"),
        "RN": ("A", "Integer"), "RUS": (".", "String"), "RUL": (".", "Integer"),
        "RUC": (".", "Float"), "RB": (".", "Integer"), "CIRUC": (".", "Float"),
        "CIRB": (".", "Integer"),
    }
    definition = reserved.get(field_id)
    return {"Number": definition[0], "Type": definition[1]} if definition else None


def _reserved_info_definition_for_version(
    fileformat: str, field_id: str
) -> dict[str, str] | None:
    if fileformat == "VCFv4.3":
        return _reserved_vcf43_info_definition(field_id)
    if fileformat == "VCFv4.4":
        return _reserved_vcf44_info_definition(field_id)
    if fileformat == "VCFv4.5":
        return _reserved_vcf45_info_definition(field_id)
    return None


def _reserved_vcf45_info_definition(field_id: str) -> dict[str, str] | None:
    # VCFv4.5 Table of reserved INFO keys and structural-variant definitions.
    reserved = {
        "AA": ("1", "String"),
        "AC": ("A", "Integer"),
        "AD": ("R", "Integer"),
        "ADF": ("R", "Integer"),
        "ADR": ("R", "Integer"),
        "AF": ("A", "Float"),
        "AN": ("1", "Integer"),
        "BQ": ("1", "Float"),
        "CIGAR": ("A", "String"),
        "DB": ("0", "Flag"),
        "DP": ("1", "Integer"),
        "END": ("1", "Integer"),
        "H2": ("0", "Flag"),
        "H3": ("0", "Flag"),
        "MQ": ("1", "Float"),
        "MQ0": ("1", "Integer"),
        "NS": ("1", "Integer"),
        "SB": ("4", "Integer"),
        "SOMATIC": ("0", "Flag"),
        "VALIDATED": ("0", "Flag"),
        "1000G": ("0", "Flag"),
        "SVLEN": ("A", "Integer"),
        # VCFv4.5 structural-variant INFO definitions.
        "IMPRECISE": ("0", "Flag"),
        "NOVEL": ("0", "Flag"),
        "SVTYPE": ("1", "String"),
        "CIPOS": (".", "Integer"),
        "CIEND": (".", "Integer"),
        "HOMLEN": ("A", "Integer"),
        "HOMSEQ": ("A", "String"),
        "BKPTID": ("A", "String"),
        "MEINFO": (".", "String"),
        "METRANS": (".", "String"),
        "DGVID": ("A", "String"),
        "DBVARID": ("A", "String"),
        "DBRIPID": ("A", "String"),
        "MATEID": ("A", "String"),
        "PARID": ("A", "String"),
        "EVENT": ("A", "String"),
        "EVENTTYPE": ("A", "String"),
        # VCFv4.5 tandem-repeat and additional SV INFO definitions.
        "CILEN": (".", "Integer"),
        "CN": ("A", "Float"),
        "CICN": (".", "Float"),
        "SVCLAIM": ("A", "String"),
        "RN": ("A", "Integer"),
        "RUS": (".", "String"),
        "RUL": (".", "Integer"),
        "RUC": (".", "Float"),
        "RB": (".", "Integer"),
        "CIRUC": (".", "Float"),
        "CIRB": (".", "Integer"),
        "RUB": (".", "Integer"),
    }
    definition = reserved.get(field_id)
    if definition is None:
        return None
    return {"Number": definition[0], "Type": definition[1]}


class StrictVCFValidationError(ValueError):
    def __init__(self, message: str, *, code: str = "VCF_INVALID"):
        super().__init__(message)
        self.code = code


def _verify_bgzf(path: str | Path) -> dict[str, int | str | bool]:
    """Validate every BGZF block and return compression provenance."""
    source = Path(path)
    offset = 0
    block_count = 0
    uncompressed_size = 0
    final_block_is_empty = False
    with source.open("rb") as handle:
        while True:
            handle.seek(offset)
            fixed_header = handle.read(12)
            if not fixed_header:
                break
            if len(fixed_header) != 12 or fixed_header[:3] != b"\x1f\x8b\x08":
                raise StrictVCFValidationError(
                    f"Compressed VCF is not a valid BGZF stream at byte offset {offset}.",
                    code="VCF_BGZF_INVALID",
                )
            if fixed_header[3] != 4:
                raise StrictVCFValidationError(
                    f"Compressed VCF is gzip but not BGZF at byte offset {offset}.",
                    code="VCF_BGZF_REQUIRED",
                )

            extra_length = struct.unpack_from("<H", fixed_header, 10)[0]
            extra = handle.read(extra_length)
            if len(extra) != extra_length:
                raise StrictVCFValidationError(
                    f"Truncated BGZF extra field at byte offset {offset}.",
                    code="VCF_BGZF_TRUNCATED",
                )

            cursor = 0
            block_size: int | None = None
            while cursor + 4 <= len(extra):
                tag = extra[cursor:cursor + 2]
                subfield_length = struct.unpack_from("<H", extra, cursor + 2)[0]
                cursor += 4
                if cursor + subfield_length > len(extra):
                    raise StrictVCFValidationError(
                        f"Malformed BGZF extra field at byte offset {offset}.",
                        code="VCF_BGZF_INVALID",
                    )
                if tag == b"BC":
                    if subfield_length != 2 or block_size is not None:
                        raise StrictVCFValidationError(
                            f"Malformed BGZF BC field at byte offset {offset}.",
                            code="VCF_BGZF_INVALID",
                        )
                    block_size = struct.unpack_from("<H", extra, cursor)[0] + 1
                cursor += subfield_length
            if cursor != len(extra) or block_size is None:
                raise StrictVCFValidationError(
                    f"Compressed VCF is gzip but not BGZF at byte offset {offset}.",
                    code="VCF_BGZF_REQUIRED",
                )

            header_size = 12 + extra_length
            if block_size < header_size + 8 or block_size > 65536:
                raise StrictVCFValidationError(
                    f"Invalid BGZF block size at byte offset {offset}.",
                    code="VCF_BGZF_INVALID",
                )
            remainder = handle.read(block_size - header_size)
            if len(remainder) != block_size - header_size:
                raise StrictVCFValidationError(
                    f"Truncated BGZF block at byte offset {offset}.",
                    code="VCF_BGZF_TRUNCATED",
                )
            compressed, trailer = remainder[:-8], remainder[-8:]
            try:
                inflater = zlib.decompressobj(wbits=-15)
                uncompressed = inflater.decompress(compressed, 65537)
            except zlib.error as exc:
                raise StrictVCFValidationError(
                    f"Corrupt BGZF deflate stream at byte offset {offset}.",
                    code="VCF_BGZF_CORRUPT",
                ) from exc
            if (
                len(uncompressed) > 65536
                or not inflater.eof
                or inflater.unused_data
                or inflater.unconsumed_tail
            ):
                raise StrictVCFValidationError(
                    f"Invalid or oversized BGZF deflate payload at byte offset {offset}.",
                    code="VCF_BGZF_INVALID",
                )
            expected_crc, expected_size = struct.unpack("<II", trailer)
            if (
                zlib.crc32(uncompressed) & 0xFFFFFFFF != expected_crc
                or len(uncompressed) != expected_size
            ):
                raise StrictVCFValidationError(
                    f"BGZF checksum or uncompressed size mismatch at byte offset {offset}.",
                    code="VCF_BGZF_CHECKSUM_MISMATCH",
                )
            offset += block_size
            block_count += 1
            uncompressed_size += len(uncompressed)
            final_block_is_empty = len(uncompressed) == 0

    if block_count == 0:
        raise StrictVCFValidationError(
            "Compressed VCF is empty and has no BGZF blocks.",
            code="VCF_BGZF_EMPTY",
        )
    return {
        "format": "BGZF",
        "block_count": block_count,
        "compressed_size_bytes": source.stat().st_size,
        "uncompressed_size_bytes": uncompressed_size,
        "eof_marker_present": final_block_is_empty,
    }


@contextmanager
def _open(path: str | Path):
    """Open a VCF text stream and normalize compressed-stream failures.

    gzip validates member headers, checksums, and trailers while the stream is
    consumed, not necessarily when it is opened. Keep the read inside this
    context so corrupt or truncated compressed input is reported as a domain
    validation error by every VCF reader using this helper.
    """
    p = Path(path)
    compressed = p.name.lower().endswith((".gz", ".bgz"))
    handle = gzip.open(p, "rt", encoding="utf-8") if compressed else open(
        p, "rt", encoding="utf-8"
    )
    try:
        with handle:
            yield handle
    except (gzip.BadGzipFile, EOFError, zlib.error) as exc:
        raise StrictVCFValidationError(
            f"VCF compressed stream is corrupt or truncated: {p.name}",
            code="VCF_COMPRESSION_INVALID",
        ) from exc


def declared_vcf_contig_md5s(path: str | Path) -> dict[str, str]:
    """Return and syntax-check optional SAM/VCF contig MD5 digests."""
    digests: dict[str, str] = {}
    with _open(path) as handle:
        for line_no, raw in enumerate(handle, 1):
            if raw.startswith("#CHROM"):
                break
            if not raw.startswith("##contig=<") or not raw.rstrip("\r\n").endswith(">"):
                continue
            line = raw.rstrip("\r\n")
            body = line[len("##contig=<"):-1]
            if "md5=" not in body:
                continue
            id_match = _CONTIG_ID.search(body)
            md5_match = _CONTIG_MD5.search(body + ",")
            if id_match is None or md5_match is None:
                raise StrictVCFValidationError(
                    f"Malformed VCF contig MD5 declaration at line {line_no}",
                    code="VCF_CONTIG_MD5_INVALID",
                )
            contig = id_match.group(1) or id_match.group(2)
            digest = md5_match.group(1)
            if not re.fullmatch(r"[0-9a-f]{32}", digest):
                raise StrictVCFValidationError(
                    f"VCF contig {contig!r} MD5 must be 32 lowercase hexadecimal characters at line {line_no}",
                    code="VCF_CONTIG_MD5_INVALID",
                )
            if contig in digests and digests[contig] != digest:
                raise StrictVCFValidationError(
                    f"VCF contig {contig!r} has conflicting MD5 declarations",
                    code="VCF_CONTIG_MD5_CONFLICT",
                )
            digests[contig] = digest
    return digests


def declared_vcf_contig_lengths(path: str | Path) -> dict[str, int]:
    """Return declared contig lengths from a VCF header, when supplied."""
    lengths: dict[str, int] = {}
    with _open(path) as handle:
        for line_no, raw in enumerate(handle, 1):
            if raw.startswith("#CHROM"):
                break
            if not raw.startswith("##contig=<") or not raw.rstrip("\r\n").endswith(">"):
                continue
            line = raw.rstrip("\r\n")
            body = line[len("##contig=<"):-1]
            id_match = _CONTIG_ID.search(body)
            length_match = _CONTIG_LENGTH.search(body + ",")
            if id_match is None or length_match is None:
                continue
            contig = id_match.group(1) or id_match.group(2)
            length = int(length_match.group(1))
            if length < 1:
                raise StrictVCFValidationError(
                    f"VCF contig {contig!r} has a non-positive length at line {line_no}",
                    code="VCF_CONTIG_LENGTH_INVALID",
                )
            if contig in lengths and lengths[contig] != length:
                raise StrictVCFValidationError(
                    f"VCF contig {contig!r} has conflicting declared lengths",
                    code="VCF_CONTIG_LENGTH_CONFLICT",
                )
            lengths[contig] = length
    return lengths


def _validate_info(value: str, line_no: int, fileformat: str | None = None) -> None:
    if value == ".":
        return
    if not value:
        raise StrictVCFValidationError(f"INFO is empty at line {line_no}", code="VCF_INFO_INVALID")
    seen: set[str] = set()
    for item in value.split(";"):
        if not item:
            raise StrictVCFValidationError(f"Empty INFO entry at line {line_no}", code="VCF_INFO_INVALID")
        if "=" in item:
            key, val = item.split("=", 1)
            if (
                not INFO_KEY_RE.fullmatch(key)
                or val == ""
                or "=" in val
                or INVALID_PERCENT_ESCAPE_RE.search(val)
                or (
                    not (fileformat == "VCFv4.5" and key in {"MEINFO", "METRANS"})
                    and any(value == "" for value in val.split(","))
                )
            ):
                raise StrictVCFValidationError(f"Malformed INFO entry at line {line_no}: {item!r}", code="VCF_INFO_INVALID")
        elif not INFO_KEY_RE.fullmatch(item):
            raise StrictVCFValidationError(f"Malformed INFO flag at line {line_no}: {item!r}", code="VCF_INFO_INVALID")
        else:
            key = item
        if key in seen:
            raise StrictVCFValidationError(f"Duplicate INFO key {key!r} at line {line_no}", code="VCF_INFO_INVALID")
        seen.add(key)


def _info_values(value: str) -> dict[str, str | None]:
    if value == ".":
        return {}
    result: dict[str, str | None] = {}
    for item in value.split(";"):
        key, separator, raw = item.partition("=")
        result[key] = raw if separator else None
    return result



def compute_vcf45_record_span(
    fields: list[str],
    line_no: int,
) -> tuple[int, list[tuple[int, int]], str] | None:
    """Compute VCFv4.5 reference span and sample-specific <*> block lengths."""
    if len(fields) < 8:
        return None
    pos = int(fields[1])
    ref = fields[3].upper()
    alts = fields[4].split(",") if fields[4] != "." else []
    ref_end = pos + len(ref) - 1
    end_candidates = [ref_end]
    unknown_span = False
    sample_lengths: list[tuple[int, int]] = []
    info_values = _info_values(fields[7])

    raw_end = info_values.get("END")
    declared_end: int | None = None
    if raw_end not in {None, "."}:
        try:
            declared_end = int(raw_end)
        except ValueError as exc:
            raise StrictVCFValidationError(
                f"INFO/END must be an integer at line {line_no}",
                code="VCF_END_INVALID",
            ) from exc
        if declared_end < ref_end:
            raise StrictVCFValidationError(
                f"INFO/END precedes the end of REF at line {line_no}",
                code="VCF_END_INVALID",
            )

    raw_svlen = info_values.get("SVLEN")
    svlen_values = raw_svlen.split(",") if raw_svlen not in {None, "."} else []
    if svlen_values and len(svlen_values) != len(alts):
        raise StrictVCFValidationError(
            f"INFO/SVLEN cardinality must match ALT at line {line_no}",
            code="VCF_SVLEN_INVALID",
        )

    wildcard_indexes = {
        index for index, alt in enumerate(alts, start=1)
        if alt in {"<*>", "<NON_REF>"}
    }
    for alt_index, alt in enumerate(alts):
        raw_value = svlen_values[alt_index] if svlen_values else None
        is_symbolic_sv = alt not in {"<*>", "<NON_REF>"} and bool(SYMBOLIC_RE.fullmatch(alt))
        if not is_symbolic_sv:
            if raw_value not in {None, "", "."}:
                raise StrictVCFValidationError(
                    f"INFO/SVLEN must be missing for non-structural ALT {alt!r} at line {line_no}",
                    code="VCF_SVLEN_INVALID",
                )
            continue
        if raw_value in {None, "", "."}:
            if declared_end is None:
                raise StrictVCFValidationError(
                    f"Symbolic structural ALT {alt!r} requires SVLEN or END at line {line_no}",
                    code="VCF_SV_INVALID",
                )
            unknown_span = True
            continue
        try:
            svlen = int(raw_value)
        except ValueError as exc:
            raise StrictVCFValidationError(
                f"INFO/SVLEN must contain integers at line {line_no}",
                code="VCF_SVLEN_INVALID",
            ) from exc
        if svlen == 0:
            raise StrictVCFValidationError(
                f"INFO/SVLEN must be non-zero for symbolic structural ALT {alt!r} at line {line_no}",
                code="VCF_SVLEN_INVALID",
            )
        end_candidates.append(pos + abs(svlen))

    format_keys = fields[8].split(":") if len(fields) > 8 else []
    gt_index = format_keys.index("GT") if "GT" in format_keys else None
    len_index = format_keys.index("LEN") if "LEN" in format_keys else None
    laa_index = format_keys.index("LAA") if "LAA" in format_keys else None

    def sample_value(values: list[str], index: int | None) -> str:
        return values[index] if index is not None and index < len(values) else "."

    def is_reference_genotype(values: list[str]) -> bool:
        if gt_index is None:
            return False
        gt = sample_value(values, gt_index)
        if gt in {"", "."}:
            return False
        tokens = _gt_allele_tokens(gt, "VCFv4.5", line_no)
        return bool(tokens) and all(token == "0" for token in tokens)

    def validate_laa(values: list[str], sample_index: int) -> None:
        if laa_index is None:
            return
        raw_laa = sample_value(values, laa_index)
        try:
            local_indexes = set() if raw_laa in {"", "."} else {
                int(value) for value in raw_laa.split(",")
            }
        except ValueError as exc:
            raise StrictVCFValidationError(
                f"FORMAT/LAA contains a non-integer ALT index at line {line_no}, sample {sample_index}",
                code="VCF_LOCAL_ALLELE_INVALID",
            ) from exc
        if not wildcard_indexes.intersection(local_indexes):
            raise StrictVCFValidationError(
                f"FORMAT/LAA must include <*> when starting a reference block at line {line_no}, sample {sample_index}",
                code="VCF_GVCF_BLOCK_LAA_INVALID",
            )

    if len_index is not None and not wildcard_indexes:
        for sample_index, sample in enumerate(fields[9:], 1):
            raw_length = sample_value(sample.split(":"), len_index)
            if raw_length not in {"", "."}:
                raise StrictVCFValidationError(
                    f"FORMAT/LEN is only valid when ALT contains <*> or <NON_REF> at line {line_no}",
                    code="VCF_LEN_INVALID",
                )

    for sample_index, sample in enumerate(fields[9:], 1):
        values = sample.split(":")
        raw_length = sample_value(values, len_index)
        reference_gt = is_reference_genotype(values)
        if raw_length not in {"", "."}:
            if not wildcard_indexes:
                raise StrictVCFValidationError(
                    f"FORMAT/LEN is only valid when ALT contains <*> or <NON_REF> at line {line_no}",
                    code="VCF_LEN_INVALID",
                )
            if not reference_gt:
                raise StrictVCFValidationError(
                    f"FORMAT/LEN requires a reference GT at line {line_no}, sample {sample_index}",
                    code="VCF_LEN_GENOTYPE_INVALID",
                )
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise StrictVCFValidationError(
                    f"FORMAT/LEN must contain integers at line {line_no}, sample {sample_index}",
                    code="VCF_LEN_INVALID",
                ) from exc
            if length <= 0 or length < len(ref) or length > 2_147_483_647:
                raise StrictVCFValidationError(
                    f"FORMAT/LEN must be a positive 32-bit integer at least as long as REF at line {line_no}, sample {sample_index}",
                    code="VCF_LEN_INVALID",
                )
            validate_laa(values, sample_index)
            sample_lengths.append((sample_index, length))
            end_candidates.append(pos + length - 1)
        elif wildcard_indexes and declared_end is not None and reference_gt:
            # Backwards compatibility: infer a missing sample LEN from INFO/END.
            length = declared_end - pos + 1
            if length < len(ref):
                raise StrictVCFValidationError(
                    f"INFO/END is shorter than REF for a reference block at line {line_no}, sample {sample_index}",
                    code="VCF_END_INVALID",
                )
            validate_laa(values, sample_index)
            sample_lengths.append((sample_index, length))
            unknown_span = True

    if wildcard_indexes and declared_end is not None and len(fields) == 8:
        unknown_span = True

    computed_end = max(end_candidates)
    if declared_end is not None:
        if declared_end < computed_end:
            raise StrictVCFValidationError(
                f"INFO/END is shorter than the computed VCFv4.5 reference span at line {line_no}",
                code="VCF_END_MISMATCH",
            )
        if not unknown_span and declared_end != computed_end:
            raise StrictVCFValidationError(
                f"INFO/END must equal the computed VCFv4.5 reference span at line {line_no}",
                code="VCF_END_MISMATCH",
            )
        return declared_end, sample_lengths, "INFO_END"
    return computed_end, sample_lengths, "COMPUTED"


def _validate_vcf45_reference_block_coverage(
    fields: list[str],
    *,
    chrom: str,
    pos: int,
    active_blocks: dict[int, tuple[str, int]],
    line_no: int,
) -> None:
    """Enforce sample-level missing-call semantics inside preceding <*> blocks."""
    if not active_blocks:
        return
    format_keys = fields[8].split(":") if len(fields) > 8 else []
    gt_index = format_keys.index("GT") if "GT" in format_keys else None
    for sample_index, (block_chrom, block_end) in list(active_blocks.items()):
        if block_chrom != chrom or pos > block_end:
            del active_blocks[sample_index]
            continue
        if gt_index is None:
            raise StrictVCFValidationError(
                f"Record inside a preceding <*> block must contain FORMAT/GT at line {line_no}, sample {sample_index}",
                code="VCF_GVCF_BLOCK_OVERLAP_INVALID",
            )
        sample_column = 8 + sample_index
        if sample_column >= len(fields):
            raise StrictVCFValidationError(
                f"Record inside a preceding <*> block is missing sample {sample_index} at line {line_no}",
                code="VCF_GVCF_BLOCK_OVERLAP_INVALID",
            )
        values = fields[sample_column].split(":")
        gt = values[gt_index] if gt_index < len(values) else "."
        if gt != ".":
            raise StrictVCFValidationError(
                f"Sample {sample_index} must have GT='.' inside its preceding <*> block at line {line_no}",
                code="VCF_GVCF_BLOCK_OVERLAP_INVALID",
            )
        for value_index, key in enumerate(format_keys):
            if key in {"GT", "LAA"}:
                continue
            value = values[value_index] if value_index < len(values) else "."
            if value not in {"", "."}:
                raise StrictVCFValidationError(
                    f"Sample {sample_index} must not provide FORMAT/{key} inside its preceding <*> block at line {line_no}",
                    code="VCF_GVCF_BLOCK_OVERLAP_INVALID",
                )


def _parse_field_definition(line: str, kind: str, line_no: int, fileformat: str | None = None) -> tuple[str, dict[str, str]]:
    """Parse INFO/FORMAT metadata without splitting commas inside quoted descriptions."""
    prefix = f"##{kind}=<"
    if not line.startswith(prefix) or not line.endswith(">"):
        raise StrictVCFValidationError(
            f"Malformed {kind} header definition at line {line_no}",
            code="VCF_HEADER_DEFINITION_INVALID",
        )
    body = line[len(prefix):-1]
    attributes: list[str] = []
    current: list[str] = []
    quoted = False
    escaped = False
    for char in body:
        if escaped:
            current.append(char)
            escaped = False
        elif char == chr(92) and quoted:
            current.append(char)
            escaped = True
        elif char == '"':
            current.append(char)
            quoted = not quoted
        elif char == "," and not quoted:
            attributes.append("".join(current))
            current = []
        else:
            current.append(char)
    if quoted or escaped:
        raise StrictVCFValidationError(
            f"Malformed quoted {kind} header value at line {line_no}",
            code="VCF_HEADER_DEFINITION_INVALID",
        )
    attributes.append("".join(current))

    parsed: dict[str, str] = {}
    for attribute in attributes:
        key, separator, value = attribute.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not key or not value or key in parsed:
            raise StrictVCFValidationError(
                f"Malformed or duplicate {kind} header attribute at line {line_no}",
                code="VCF_HEADER_DEFINITION_INVALID",
            )
        if key == "Description" and not (value.startswith('"') and value.endswith('"')):
            raise StrictVCFValidationError(
                f"{kind} Description must be quoted at line {line_no}",
                code="VCF_HEADER_DEFINITION_INVALID",
            )
        if value.startswith('"'):
            if len(value) < 2 or not value.endswith('"'):
                raise StrictVCFValidationError(
                    f"Malformed quoted {kind} header attribute at line {line_no}",
                    code="VCF_HEADER_DEFINITION_INVALID",
                )
            value = value[1:-1]
        elif '"' in value:
            raise StrictVCFValidationError(
                f"Malformed quoted {kind} header attribute at line {line_no}",
                code="VCF_HEADER_DEFINITION_INVALID",
            )
        parsed[key] = value

    required = {"ID", "Number", "Type", "Description"}
    if not required.issubset(parsed):
        raise StrictVCFValidationError(
            f"{kind} header definition lacks required attributes at line {line_no}",
            code="VCF_HEADER_DEFINITION_INVALID",
        )
    identifier = parsed["ID"]
    field_id_pattern = INFO_KEY_RE if kind == "INFO" else FORMAT_KEY_RE
    if not field_id_pattern.fullmatch(identifier):
        raise StrictVCFValidationError(
            f"Invalid {kind} field ID at line {line_no}: {identifier!r}",
            code="VCF_HEADER_DEFINITION_INVALID",
        )
    number = parsed["Number"]
    allowed_cardinality = {"A", "R", "G", "."}
    if fileformat in {"VCFv4.4", "VCFv4.5"} and kind == "FORMAT":
        # VCFv4.4 errata introduced Number=P for PSL/PSO/PSQ; VCFv4.5
        # retains it and adds local-allele and base-modification cardinalities.
        allowed_cardinality.add("P")
    if fileformat == "VCFv4.5" and kind == "FORMAT":
        allowed_cardinality.update({"LA", "LR", "LG", "M"})
    if number not in allowed_cardinality and not re.fullmatch(r"[0-9]+", number):
        raise StrictVCFValidationError(
            f"Invalid {kind} field Number at line {line_no}: {number!r}",
            code="VCF_HEADER_DEFINITION_INVALID",
        )
    if parsed["Type"] not in {"Integer", "Float", "Flag", "Character", "String"}:
        raise StrictVCFValidationError(
            f"Invalid {kind} field Type at line {line_no}: {parsed['Type']!r}",
            code="VCF_HEADER_DEFINITION_INVALID",
        )
    if (parsed["Type"] == "Flag") != (number == "0") or (kind == "FORMAT" and parsed["Type"] == "Flag"):
        raise StrictVCFValidationError(
            f"{kind} Flag fields require Number=0 and INFO scope at line {line_no}",
            code="VCF_HEADER_DEFINITION_INVALID",
        )
    if number == "M":
        if identifier[-1] not in "ACGTUN":
            raise StrictVCFValidationError(
                f"FORMAT/Number=M field ID must end with A, C, G, T, U, or N at line {line_no}",
                code="VCF_HEADER_DEFINITION_INVALID",
            )
        if parsed["Type"] not in {"Integer", "Float"}:
            raise StrictVCFValidationError(
                f"FORMAT/Number=M fields require Integer or Float Type at line {line_no}",
                code="VCF_HEADER_DEFINITION_INVALID",
            )
    # Validate typed declarations against version-specific reserved tables
    # at header-read time. This prevents an earlier record-level error from
    # masking a contradictory reserved-field declaration later in the file.
    if fileformat != "VCFv4.5":
        reserved_definition = (
            _reserved_info_definition_for_version(fileformat, identifier)
            if kind == "INFO"
            else _reserved_format_definition_for_version(fileformat, identifier)
        )
        if reserved_definition is not None:
            expected_type = reserved_definition["Type"]
            allowed_types = (
                {"Integer", "Float"}
                if expected_type == "Numeric"
                else {expected_type}
            )
            if number != reserved_definition["Number"] or parsed["Type"] not in allowed_types:
                expected_type_text = "Integer or Float" if expected_type == "Numeric" else expected_type
                raise StrictVCFValidationError(
                    f"Reserved {fileformat} {kind} field {identifier!r} requires "
                    f"Number={reserved_definition['Number']} and Type={expected_type_text} at line {line_no}",
                    code=(
                        "VCF_RESERVED_INFO_DEFINITION_MISMATCH"
                        if kind == "INFO"
                        else "VCF_RESERVED_FORMAT_DEFINITION_MISMATCH"
                    ),
                )
    reserved_vcf45_definition = None
    if fileformat == "VCFv4.5":
        if kind == "FORMAT":
            reserved_vcf45_definition = _reserved_vcf45_format_definition(identifier)
        elif kind == "INFO":
            reserved_vcf45_definition = _reserved_vcf45_info_definition(identifier)
    if reserved_vcf45_definition is not None and (
        number != reserved_vcf45_definition["Number"]
        or parsed["Type"] != reserved_vcf45_definition["Type"]
    ):
        raise StrictVCFValidationError(
            f"Reserved VCFv4.5 {kind} field {identifier!r} requires "
            f"Number={reserved_vcf45_definition['Number']} and "
            f"Type={reserved_vcf45_definition['Type']} at line {line_no}",
            code="VCF_HEADER_DEFINITION_INVALID",
        )
    reserved_vcf40_definition = (
        _reserved_vcf40_format_definition(identifier)
        if fileformat == "VCFv4.0" and kind == "FORMAT"
        else None
    )
    if reserved_vcf40_definition is not None:
        expected_type = reserved_vcf40_definition["Type"]
        allowed_types = (
            {"Integer", "Float"} if expected_type == "Numeric" else {expected_type}
        )
        if number != reserved_vcf40_definition["Number"] or parsed["Type"] not in allowed_types:
            expected_type_text = "Integer or Float" if expected_type == "Numeric" else expected_type
            raise StrictVCFValidationError(
                f"Reserved VCFv4.0 FORMAT field {identifier!r} requires "
                f"Number={reserved_vcf40_definition['Number']} and "
                f"Type={expected_type_text} at line {line_no}",
                code="VCF_HEADER_DEFINITION_INVALID",
            )
    return identifier, {"Number": number, "Type": parsed["Type"]}


def _structured_header_id(line: str, kind: str, line_no: int, *, require_id: bool = True) -> str:
    """Validate structured header attributes and return their unique ID."""
    prefix = f"##{kind}=<"
    if not line.startswith(prefix) or not line.endswith(">"):
        raise StrictVCFValidationError(
            f"Malformed {kind} structured header at line {line_no}",
            code="VCF_HEADER_DEFINITION_INVALID",
        )
    body = line[len(prefix):-1]
    attributes: list[str] = []
    current: list[str] = []
    quoted = False
    escaped = False
    square_bracket_depth = 0
    for char in body:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\\\" and quoted:
            current.append(char)
            escaped = True
        elif char == '"':
            current.append(char)
            quoted = not quoted
        elif not quoted and char == "[":
            square_bracket_depth += 1
            current.append(char)
        elif not quoted and char == "]":
            square_bracket_depth -= 1
            if square_bracket_depth < 0:
                raise StrictVCFValidationError(
                    f"Malformed list value in {kind} structured header at line {line_no}",
                    code="VCF_HEADER_DEFINITION_INVALID",
                )
            current.append(char)
        elif char == "," and not quoted and square_bracket_depth == 0:
            attributes.append("".join(current))
            current = []
        else:
            current.append(char)
    if quoted or escaped or square_bracket_depth != 0:
        raise StrictVCFValidationError(
            f"Malformed quoted or list value in {kind} structured header at line {line_no}",
            code="VCF_HEADER_DEFINITION_INVALID",
        )
    attributes.append("".join(current))

    identifiers: list[str] = []
    seen_attributes: set[str] = set()
    for attribute in attributes:
        key, separator, raw_value = attribute.partition("=")
        key, value = key.strip(), raw_value.strip()
        if not separator or not key or not value or key in seen_attributes:
            raise StrictVCFValidationError(
                f"Malformed or duplicate {kind} structured header attribute at line {line_no}",
                code="VCF_HEADER_DEFINITION_INVALID",
            )
        seen_attributes.add(key)
        if value.startswith('"'):
            if len(value) < 2 or not value.endswith('"'):
                raise StrictVCFValidationError(
                    f"Malformed quoted {kind} structured header attribute at line {line_no}",
                    code="VCF_HEADER_DEFINITION_INVALID",
                )
            value = value[1:-1]
        elif '"' in value:
            raise StrictVCFValidationError(
                f"Malformed quoted {kind} structured header attribute at line {line_no}",
                code="VCF_HEADER_DEFINITION_INVALID",
            )
        if key == "ID":
            identifiers.append(value)
    if (require_id and (len(identifiers) != 1 or not identifiers[0])) or len(identifiers) > 1:
        raise StrictVCFValidationError(
            f"{kind} structured header must contain exactly one non-empty ID at line {line_no}",
            code="VCF_HEADER_DEFINITION_INVALID",
        )
    return identifiers[0] if identifiers else ""


def _expected_cardinality(
    number: str,
    alternate_count: int,
    ploidy: int | None,
    local_allele_count: int | None = None,
) -> int | None:
    if number == ".":
        return None
    if number == "A":
        return alternate_count
    if number == "R":
        return alternate_count + 1
    if number == "G":
        if ploidy is None:
            return None
        # Number=G contains one value for each unordered genotype with
        # replacement from REF plus all ALT alleles.
        return comb(alternate_count + ploidy, ploidy)
    if number == "P":
        return ploidy
    if number == "M":
        return None
    if number == "LA":
        return max(0, local_allele_count - 1) if local_allele_count is not None else None
    if number == "LR":
        return local_allele_count if local_allele_count is not None else None
    if number == "LG":
        if ploidy is None or local_allele_count is None:
            return None
        return comb(local_allele_count + ploidy - 1, ploidy)
    return int(number)


def _genotype_order(allele_count: int, ploidy: int):
    """Yield VCF colexicographic genotype order for the given allele count."""
    def walk(max_allele: int, remaining: int):
        if remaining == 1:
            for allele in range(max_allele + 1):
                yield (allele,)
            return
        for last_allele in range(max_allele + 1):
            for prefix in walk(last_allele, remaining - 1):
                yield prefix + (last_allele,)

    if allele_count < 1 or ploidy < 1:
        return
    yield from walk(allele_count - 1, ploidy)


def _genotype_order_index(genotype: tuple[int, ...]) -> int:
    return sum(comb(allele + position - 1, position) for position, allele in enumerate(genotype, 1))


def _validate_local_field_equivalence(
    *,
    format_keys: list[str],
    sample_values: list[str],
    alternate_count: int,
    local_alt_indexes: list[int],
    ploidy: int | None,
    line_no: int,
    sample_index: int,
) -> None:
    """Verify standard and VCFv4.5 local-allele fields encode the same data."""
    local_pairs = (
        ("AD", "LAD"),
        ("ADF", "LADF"),
        ("ADR", "LADR"),
        ("EC", "LEC"),
        ("GL", "LGL"),
        ("GP", "LGP"),
        ("PL", "LPL"),
        ("PP", "LPP"),
    )
    for standard_key, local_key in local_pairs:
        if standard_key not in format_keys or local_key not in format_keys:
            continue
        standard_index = format_keys.index(standard_key)
        local_index = format_keys.index(local_key)
        standard_value = sample_values[standard_index] if standard_index < len(sample_values) else "."
        local_value = sample_values[local_index] if local_index < len(sample_values) else "."
        if standard_value in {"", "."} or local_value in {"", "."}:
            continue

        definition = _reserved_vcf45_format_definition(standard_key)
        if definition is None:
            continue
        number = definition["Number"]
        standard_values = standard_value.split(",")
        local_values = local_value.split(",")
        local_alleles = [0, *local_alt_indexes]

        if number == "A":
            source_indexes = [allele_index - 1 for allele_index in local_alt_indexes]
        elif number == "R":
            source_indexes = local_alleles
        elif number == "G":
            if ploidy is None:
                raise StrictVCFValidationError(
                    f"Cannot verify {standard_key}/{local_key} equivalence without a known sample ploidy at line {line_no}, sample {sample_index}",
                    code="VCF_LOCAL_FIELD_EQUIVALENCE_UNRESOLVED",
                )
            source_indexes = [
                _genotype_order_index(
                    tuple(sorted(local_alleles[local_allele] for local_allele in genotype))
                )
                for genotype in _genotype_order(len(local_alleles), ploidy)
            ]
        else:
            continue

        if any(index >= len(standard_values) for index in source_indexes):
            raise StrictVCFValidationError(
                f"Cannot project {standard_key} into {local_key} at line {line_no}, sample {sample_index}",
                code="VCF_LOCAL_FIELD_EQUIVALENCE_INVALID",
            )
        expected_values = [standard_values[index] for index in source_indexes]
        field_type = definition["Type"]
        for expected, observed in zip(expected_values, local_values):
            if expected == "." or observed == ".":
                equivalent = expected == observed
            elif field_type == "Integer":
                equivalent = int(expected) == int(observed)
            elif field_type == "Float":
                expected_float, observed_float = float(expected), float(observed)
                equivalent = expected_float == observed_float or (
                    isnan(expected_float) and isnan(observed_float)
                )
            else:
                equivalent = expected == observed
            if not equivalent:
                raise StrictVCFValidationError(
                    f"FORMAT/{standard_key} and FORMAT/{local_key} encode different values at line {line_no}, sample {sample_index}",
                    code="VCF_LOCAL_FIELD_EQUIVALENCE_INVALID",
                )


def _validate_declared_value(
    *,
    kind: str,
    key: str,
    value: str | None,
    definition: dict[str, str],
    alternate_count: int,
    line_no: int,
    ploidy: int | None = None,
    local_allele_count: int | None = None,
    base_modification_cardinality: int | None = None,
    allow_empty_values: bool = False,
) -> None:
    number = definition["Number"]
    field_type = definition["Type"]
    field_scope = "FORMAT" if kind.startswith("FORMAT") else kind
    if field_type == "Flag":
        if value is not None:
            raise StrictVCFValidationError(
                f"{kind}/{key} is a Flag and must not have a value at line {line_no}",
                code="VCF_FIELD_CARDINALITY_INVALID",
            )
        return
    if value is None:
        raise StrictVCFValidationError(
            f"{kind}/{key} requires a value at line {line_no}",
            code="VCF_FIELD_CARDINALITY_INVALID",
        )
    if value == ".":
        return
    expected = (
        base_modification_cardinality
        if number == "M"
        else _expected_cardinality(number, alternate_count, ploidy, local_allele_count)
    )
    observed = value.split(",")
    if not allow_empty_values and any(item == "" for item in observed):
        raise StrictVCFValidationError(
            f"{kind}/{key} contains an empty list value at line {line_no}",
            code="VCF_FIELD_CARDINALITY_INVALID",
        )
    if expected is not None and len(observed) != expected:
        raise StrictVCFValidationError(
            f"{kind}/{key} has {len(observed)} values but Number={number} requires {expected} at line {line_no}",
            code="VCF_FIELD_CARDINALITY_INVALID",
        )
    for item in observed:
        if item == ".":
            continue
        valid = True
        if field_type == "Integer":
            if not re.fullmatch(r"[+-]?[0-9]+", item):
                valid = False
            else:
                integer_value = int(item)
                valid = -(2**31) + 8 <= integer_value <= 2**31 - 1
                if (field_scope, key) in NONNEGATIVE_INTEGER_FIELDS:
                    valid = valid and integer_value >= 0
                if _base_modification_field_kind(key) == "depth":
                    valid = valid and integer_value >= 0
        elif field_type == "Float":
            valid = bool(
                re.fullmatch(
                    r"[-+]?(?:[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?|INF(?:INITY)?|NAN)",
                    item,
                    flags=re.IGNORECASE,
                )
            )
            if valid:
                numeric_value = float(item)
                if (field_scope, key) in PROBABILITY_FLOAT_FIELDS:
                    valid = 0.0 <= numeric_value <= 1.0
                if (field_scope, key) in NONNEGATIVE_FLOAT_FIELDS:
                    valid = numeric_value >= 0.0
                if _base_modification_field_kind(key) == "fraction":
                    valid = valid and 0.0 <= numeric_value <= 1.0
        elif field_type == "Numeric":
            valid = bool(
                re.fullmatch(
                    r"[-+]?(?:[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?|INF(?:INITY)?|NAN)",
                    item,
                    flags=re.IGNORECASE,
                )
            )
            if valid and (field_scope, key) in NONNEGATIVE_INTEGER_FIELDS:
                valid = float(item) >= 0.0
        elif field_type == "Character":
            valid = len(item) == 1 or bool(re.fullmatch(r"%[0-9A-F]{2}", item))
        if not valid:
            raise StrictVCFValidationError(
                f"{kind}/{key} value {item!r} does not conform to declared Type={field_type} at line {line_no}",
                code="VCF_FIELD_TYPE_INVALID",
            )


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


def _validate_vcf45_structural_info(
    info: dict[str, str | None],
    alts: list[str],
    line_no: int,
) -> None:
    """Validate VCFv4.5 reserved structural-variant INFO list semantics."""
    for key in ("CIPOS", "CIEND"):
        raw_value = info.get(key)
        if raw_value in {None, "."}:
            continue
        values = raw_value.split(",")
        if len(values) != 2 * len(alts):
            raise StrictVCFValidationError(
                f"INFO/{key} requires two offsets per ALT allele at line {line_no}",
                code="VCF_SV_INFO_CARDINALITY_INVALID",
            )
        for alt_index, alternate in enumerate(alts):
            lower, upper = values[2 * alt_index : 2 * alt_index + 2]
            if lower == "." or upper == ".":
                if lower != upper:
                    raise StrictVCFValidationError(
                        f"INFO/{key} interval must provide both offsets or both missing values at line {line_no}",
                        code=(
                            "VCF_BREAKEND_CIPOS_INVALID"
                            if key == "CIPOS" and _is_vcf45_breakend_alt(alternate)
                            else "VCF_SV_INFO_INTERVAL_INVALID"
                        ),
                    )
                continue
            lower_offset, upper_offset = int(lower), int(upper)
            if key == "CIPOS" and (lower_offset > 0 or upper_offset < 0):
                raise StrictVCFValidationError(
                    f"INFO/CIPOS interval must span zero at line {line_no}",
                    code=(
                        "VCF_BREAKEND_CIPOS_INVALID"
                        if _is_vcf45_breakend_alt(alternate)
                        else "VCF_SV_INFO_INTERVAL_INVALID"
                    ),
                )
            if key == "CIEND":
                symbolic_sv = bool(SYMBOLIC_RE.fullmatch(alternate)) and alternate not in {"<*>", "<NON_REF>"}
                if not symbolic_sv:
                    raise StrictVCFValidationError(
                        f"INFO/CIEND must be missing for non-symbolic structural alleles at line {line_no}",
                        code="VCF_SV_INFO_INTERVAL_INVALID",
                    )
                if lower_offset > 0 or upper_offset < 0:
                    raise StrictVCFValidationError(
                        f"INFO/CIEND interval must extend on both sides of zero at line {line_no}",
                        code="VCF_SV_INFO_INTERVAL_INVALID",
                    )

    # VCFv4.5: when IMPRECISE is present, symbolic SV alleles may omit
    # CIPOS to indicate an unspecified confidence interval. Any precise ALT
    # allele in the same record must nevertheless carry an explicit CIPOS pair,
    # including 0,0 when its position is exact.
    imprecise_flag = "IMPRECISE" in info and info.get("IMPRECISE") is None
    if imprecise_flag:
        cipos_value = info.get("CIPOS")
        cipos_entries = cipos_value.split(",") if cipos_value not in {None, "."} else []
        precise_alt_indexes = [
            index
            for index, alternate in enumerate(alts)
            if alternate not in {".", "*", "<*>", "<NON_REF>"}
            and not SYMBOLIC_RE.fullmatch(alternate)
            and not _is_vcf45_breakend_alt(alternate)
        ]
        for alt_index in precise_alt_indexes:
            pair = (
                cipos_entries[2 * alt_index : 2 * alt_index + 2]
                if len(cipos_entries) >= 2 * alt_index + 2
                else []
            )
            if len(pair) != 2 or pair == [".", "."]:
                raise StrictVCFValidationError(
                    f"INFO/IMPRECISE requires an explicit INFO/CIPOS interval for precise ALT allele {alt_index + 1} at line {line_no}",
                    code="VCF_SV_IMPRECISE_CIPOS_MISSING",
                )

    for key in ("MEINFO", "METRANS"):
        raw_value = info.get(key)
        if raw_value in {None, "."}:
            continue
        if len(raw_value.split(",")) != 4 * len(alts):
            raise StrictVCFValidationError(
                f"INFO/{key} requires four values per ALT allele at line {line_no}",
                code="VCF_SV_INFO_CARDINALITY_INVALID",
            )


def _deleted_reference_interval(pos: int, ref: str, alt: str) -> tuple[int, int] | None:
    # Only alleles shorter than REF can delete reference bases. Equal-length
    # substitutions (including MNVs) and insertions must never establish the
    # overlap context used to validate a VCF spanning-deletion "*" allele.
    if len(ref) <= len(alt):
        return None
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


def _gt_allele_tokens(gt: str, fileformat: str | None, line_no: int) -> list[str]:
    """Parse GT tokens, including VCFv4.4+ leading phasing separators."""
    value = gt
    if fileformat in {"VCFv4.4", "VCFv4.5"} and value[:1] in {"/", "|"}:
        value = value[1:]
    tokens = re.split(r"[/|]", value)
    if not value or any(token == "" for token in tokens):
        raise StrictVCFValidationError(
            f"Invalid GT separator/allele structure at line {line_no}: {gt!r}",
            code="VCF_GENOTYPE_INVALID",
        )
    return tokens


def _gt_alleles_with_phase(
    genotype: str,
    fileformat: str | None,
    line_no: int,
) -> list[tuple[str, str]]:
    """Return GT allele tokens with their preceding phase separator."""
    tokens = _gt_allele_tokens(genotype, fileformat, line_no)
    has_leading_phase = (
        fileformat in {"VCFv4.4", "VCFv4.5"}
        and genotype[:1] in {"/", "|"}
    )
    value = genotype[1:] if has_leading_phase else genotype
    separators = re.findall(r"[/|]", value)
    if len(separators) != len(tokens) - 1:
        raise StrictVCFValidationError(
            f"Invalid GT separator structure at line {line_no}: {genotype!r}",
            code="VCF_GENOTYPE_INVALID",
        )
    first_separator = genotype[0] if has_leading_phase else (
        "/" if "/" in separators else "|"
    )
    return [
        (token, first_separator if index == 0 else separators[index - 1])
        for index, token in enumerate(tokens)
    ]


def _base_modification_allele_slots(
    sequence: str,
    modified_base: str,
) -> list[tuple[int, str, str]]:
    """Enumerate VCFv4.5 Number=M slots as (zero-based offset, strand, base).

    Slots are emitted in allele sequence order. For a specific modified base,
    the matching base is the positive-strand slot and its complement is the
    negative-strand slot. N emits positive then negative slots at each
    sequence position. Ambiguous N sequence symbols do not match a specific
    base, but still have both slots for modified-base identifier N.
    """
    base = "T" if modified_base == "U" else modified_base
    if base == "N":
        return [
            (position, strand, nucleotide)
            for position, nucleotide in enumerate(sequence)
            for strand in ("+", "-")
        ]
    complement = {"A": "T", "T": "A", "C": "G", "G": "C"}[base]
    slots: list[tuple[int, str, str]] = []
    for position, nucleotide in enumerate(sequence):
        if nucleotide == base:
            slots.append((position, "+", nucleotide))
        elif nucleotide == complement:
            slots.append((position, "-", nucleotide))
    return slots


def _expected_base_modification_slots(
    genotype: str,
    reference: str,
    alternates: list[str],
    field_id: str,
    fileformat: str | None,
    line_no: int,
) -> list[tuple[int, int, str, str]]:
    """Map each Number=M vector position to (GT allele, sequence offset, strand, base).

    GT allele indexes remain global ALT indexes. Repeated identical unphased
    allele indexes contribute once at first occurrence; phased copies remain
    separate. Missing and non-sequence alleles contribute no slots.
    """
    seen_unphased_alleles: set[int] = set()
    slots: list[tuple[int, int, str, str]] = []
    modified_base = field_id[-1].upper()
    for allele_token, phase_separator in _gt_alleles_with_phase(
        genotype, fileformat, line_no
    ):
        if allele_token == ".":
            continue
        allele_index = int(allele_token)
        if phase_separator == "/":
            if allele_index in seen_unphased_alleles:
                continue
            seen_unphased_alleles.add(allele_index)
        allele_sequence = (
            reference if allele_index == 0 else alternates[allele_index - 1]
        )
        if not DNA_RE.fullmatch(allele_sequence):
            continue
        slots.extend(
            (allele_index, position, strand, sequence_base)
            for position, strand, sequence_base in _base_modification_allele_slots(
                allele_sequence, modified_base
            )
        )
    return slots


def _expected_base_modification_slots_with_haplotype(
    genotype: str,
    reference: str,
    alternates: list[str],
    field_id: str,
    fileformat: str | None,
    line_no: int,
) -> list[tuple[int, int, int, str, str]]:
    """Return (global allele, GT copy index, sequence offset, strand, base)."""
    seen_unphased_alleles: set[int] = set()
    slots: list[tuple[int, int, int, str, str]] = []
    modified_base = field_id[-1].upper()
    for copy_index, (allele_token, phase_separator) in enumerate(
        _gt_alleles_with_phase(genotype, fileformat, line_no)
    ):
        if allele_token == ".":
            continue
        allele_index = int(allele_token)
        if phase_separator == "/":
            if allele_index in seen_unphased_alleles:
                continue
            seen_unphased_alleles.add(allele_index)
        allele_sequence = reference if allele_index == 0 else alternates[allele_index - 1]
        if not DNA_RE.fullmatch(allele_sequence):
            continue
        slots.extend(
            (allele_index, copy_index, position, strand, sequence_base)
            for position, strand, sequence_base in _base_modification_allele_slots(
                allele_sequence, modified_base
            )
        )
    return slots


def _expected_base_modification_cardinality(
    genotype: str,
    reference: str,
    alternates: list[str],
    field_id: str,
    fileformat: str | None,
    line_no: int,
) -> int:
    """Return the number of sequence/strand slots defined by VCFv4.5 Number=M."""
    return len(
        _expected_base_modification_slots(
            genotype, reference, alternates, field_id, fileformat, line_no
        )
    )


def _validate_record(
    fields: list[str],
    line_no: int,
    reference_contigs: set[str] | None,
    fileformat: str | None = None,
    format_definitions: dict[str, dict[str, str]] | None = None,
) -> tuple[str, int, list[str]]:
    if len(fields) < 8:
        raise StrictVCFValidationError(f"Expected at least 8 VCF columns at line {line_no}", code="VCF_RECORD_INVALID")
    chrom, pos_text, identifier, ref, alt, qual, filt, info = fields[:8]

    if not chrom or chrom.startswith("#") or any(char.isspace() for char in chrom):
        raise StrictVCFValidationError(f"Invalid CHROM at line {line_no}", code="VCF_CHROM_INVALID")
    if fileformat in {"VCFv4.3", "VCFv4.4", "VCFv4.5"}:
        if re.fullmatch(r"<[^<>,\s]+>", chrom):
            raise StrictVCFValidationError(
                f"External assembly contig {chrom!r} is valid VCF syntax but is not supported by the configured reference-package contract at line {line_no}",
                code="VCF_EXTERNAL_ASSEMBLY_CONTIG_UNSUPPORTED",
            )
        if not VCF_CONTIG_NAME_RE.fullmatch(chrom):
            raise StrictVCFValidationError(
                f"CHROM {chrom!r} violates the VCFv4.3+ SAM reference-name grammar at line {line_no}",
                code="VCF_CHROM_INVALID",
            )
    if reference_contigs is not None:
        from backend.app.domain.reference import FastaReference, ReferenceError

        try:
            FastaReference.resolve_contig_name(chrom, reference_contigs)
        except ReferenceError as exc:
            raise StrictVCFValidationError(
                f"Contig {chrom!r} cannot be resolved in the selected reference package at line {line_no}",
                code="REFERENCE_CONTIG_MISMATCH",
            ) from exc

    try:
        pos = int(pos_text)
    except ValueError as exc:
        raise StrictVCFValidationError(f"Invalid POS at line {line_no}: {pos_text!r}", code="VCF_POS_INVALID") from exc
    if pos < 0:
        raise StrictVCFValidationError(f"POS must be non-negative at line {line_no}", code="VCF_POS_INVALID")

    if identifier == "":
        raise StrictVCFValidationError(f"ID is empty at line {line_no}", code="VCF_ID_INVALID")
    if identifier != ".":
        record_ids = identifier.split(";")
        if (
            any(not record_id or any(char.isspace() for char in record_id) for record_id in record_ids)
            or ("." in record_ids and record_ids != ["."])
        ):
            raise StrictVCFValidationError(f"Malformed ID at line {line_no}: {identifier!r}", code="VCF_ID_INVALID")

    ref = ref.upper()
    if not DNA_RE.fullmatch(ref):
        raise StrictVCFValidationError(f"REF must contain only A/C/G/T/N for Phase 1 at line {line_no}", code="VCF_REF_INVALID")

    raw_alts = alt.split(",")
    if not alt or ("." in raw_alts and raw_alts != ["."]):
        raise StrictVCFValidationError(
            f"ALT '.' must be the only allele when no alternate is present at line {line_no}",
            code="VCF_ALT_INVALID",
        )
    # Sequence allele bases are case-insensitive in VCF and can be canonicalized
    # to uppercase. Symbolic IDs and breakend mate-contig identifiers are
    # case-sensitive; uppercasing the complete ALT token corrupts their identity.
    alts = (
        []
        if raw_alts == ["."]
        else [
            allele.upper() if re.fullmatch(r"[ACGTNacgtn]+", allele) or SINGLE_BREAKEND_RE.fullmatch(allele) else allele
            for allele in raw_alts
        ]
    )
    if any(
        not DNA_RE.fullmatch(a) and not SYMBOLIC_RE.fullmatch(a) and not BREAKEND_RE.fullmatch(a) and not SINGLE_BREAKEND_RE.fullmatch(a) and a != "*"
        for a in alts
    ):
        raise StrictVCFValidationError(f"Malformed ALT at line {line_no}: {alt!r}", code="VCF_ALT_INVALID")

    alt_identity_keys = [_alt_identity_key(allele) for allele in alts]
    if fileformat == "VCFv4.5" and len(alt_identity_keys) != len(set(alt_identity_keys)):
        raise StrictVCFValidationError(
            f"ALT contains duplicate allele values at line {line_no}",
            code="VCF_ALT_DUPLICATE",
        )

    if qual != ".":
        try:
            q = float(qual)
        except ValueError as exc:
            raise StrictVCFValidationError(f"Invalid QUAL at line {line_no}: {qual!r}", code="VCF_QUAL_INVALID") from exc
        if q < 0:
            raise StrictVCFValidationError(f"QUAL must be non-negative at line {line_no}", code="VCF_QUAL_INVALID")

    if filt != ".":
        filter_ids = filt.split(";")
        if not filt or any(not value or any(char.isspace() for char in value) for value in filter_ids):
            raise StrictVCFValidationError(f"Malformed FILTER at line {line_no}: {filt!r}", code="VCF_FILTER_INVALID")
        if "0" in filter_ids:
            raise StrictVCFValidationError(
                f"FILTER value '0' is reserved and cannot be used at line {line_no}",
                code="VCF_FILTER_INVALID",
            )
        if len(filter_ids) != len(set(filter_ids)):
            raise StrictVCFValidationError(
                f"FILTER contains duplicate values at line {line_no}",
                code="VCF_FILTER_INVALID",
            )
        if "PASS" in filter_ids and filter_ids != ["PASS"]:
            raise StrictVCFValidationError(
                f"FILTER PASS cannot be combined with failing filters at line {line_no}",
                code="VCF_FILTER_INVALID",
            )

    _validate_info(info, line_no, fileformat)
    info_values = _info_values(info)
    for alt_index, alternate in enumerate(alts):
        _validate_structural_alt(
            alternate, alt_index=alt_index, alts=alts, info=info_values, pos=pos, line_no=line_no,
        )
    if alts and all(alt in {"<NON_REF>", "<*>"} for alt in alts):
        end_value = info_values.get("END")
        vcf45_wildcard_record = fileformat == "VCFv4.5"
        if end_value in {None, "."} and not vcf45_wildcard_record:
            raise StrictVCFValidationError(f"GVCF reference block requires END at line {line_no}", code="VCF_GVCF_BLOCK_INVALID")
        if end_value not in {None, "."}:
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
        if len(keys) != len(set(keys)) or any(not FORMAT_KEY_RE.fullmatch(k) for k in keys):
            raise StrictVCFValidationError(f"Malformed or duplicate FORMAT key at line {line_no}", code="VCF_FORMAT_INVALID")
        if fileformat == "VCFv4.0" and len(fields) > 9 and "GT" not in keys:
            raise StrictVCFValidationError(
                f"VCFv4.0 sample genotype data require FORMAT/GT at line {line_no}",
                code="VCF_FORMAT_INVALID",
            )
        if "GT" in keys and keys[0] != "GT":
            raise StrictVCFValidationError(
                f"GT must be the first FORMAT key when present at line {line_no}",
                code="VCF_FORMAT_INVALID",
            )
        base_modification_keys = [
            key
            for key in keys
            if (format_definitions or {}).get(key, {}).get("Number") == "M"
            or (
                fileformat == "VCFv4.5"
                and _reserved_base_modification_format_definition(key) is not None
            )
        ]
        if base_modification_keys and "GT" not in keys:
            raise StrictVCFValidationError(
                f"VCFv4.5 base-modification FORMAT fields require GT at line {line_no}",
                code="VCF_BASE_MODIFICATION_GT_MISSING",
            )
        if fileformat == "VCFv4.5" and (
            any((format_definitions or {}).get(key, {}).get("Number") in {"LA", "LR", "LG"} for key in keys)
            or any(key in {"LAA", "LAD", "LADF", "LADR", "LEC", "LGL", "LGP", "LPL", "LPP"} for key in keys)
        ):
            if "LAA" not in keys or keys.index("LAA") != (1 if "GT" in keys else 0):
                raise StrictVCFValidationError(
                    f"VCFv4.5 local-allele FORMAT fields require LAA immediately after GT (or first when GT is absent) at line {line_no}",
                    code="VCF_LOCAL_ALLELE_HEADER_INVALID",
                )
        for sample_index, sample in enumerate(fields[9:], start=1):
            values = sample.split(":")
            if not sample or len(values) > len(keys):
                raise StrictVCFValidationError(
                    f"Sample {sample_index} has malformed FORMAT values for {len(keys)} keys at line {line_no}",
                    code="VCF_SAMPLE_INVALID",
                )
            for value_index, value in enumerate(values):
                if value == "":
                    field_key = keys[value_index] if value_index < len(keys) else None
                    if field_key == "GT":
                        raise StrictVCFValidationError(
                            f"FORMAT/GT must contain an explicit genotype or missing-value token at line {line_no}, sample {sample_index}",
                            code="VCF_GENOTYPE_INVALID",
                        )
                    if fileformat == "VCFv4.5" and field_key == "LAA":
                        # VCFv4.5's REF-only local-allele example uses an
                        # empty text value; BCF represents this as MISSING.
                        continue
                    raise StrictVCFValidationError(
                        f"Sample {sample_index} has an empty FORMAT/{field_key or 'value'} field at line {line_no}; use '.' for a missing value",
                        code="VCF_SAMPLE_INVALID",
                    )
            # VCF permits trailing FORMAT fields to be omitted. A missing value
            # within the supplied values must still use the explicit '.' token.
            if "GT" in keys:
                gt = values[keys.index("GT")]
                if gt != ".":
                    for allele_index in _gt_allele_tokens(gt, fileformat, line_no):
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


def validate_vcf_strict(
    path: str | Path,
    *,
    reference_contigs: set[str] | None = None,
    include_base_modification_slot_assignments: bool = False,
    base_modification_strandedness: str | None = None,
) -> dict:
    if base_modification_strandedness not in (None, "stranded", "unstranded"):
        raise ValueError(
            "base_modification_strandedness must be None, 'stranded', or 'unstranded'"
        )
    source = Path(path)
    compression: dict[str, int | str | bool] = {"format": "NONE"}
    if source.name.lower().endswith((".vcf.gz", ".vcf.bgz")):
        compression = _verify_bgzf(source)
    fileformat: str | None = None
    chrom_header: list[str] | None = None
    found_header = False
    records = 0
    alternate_allele_count = 0
    multiallelic = 0
    reference_only = 0
    telomere_records = 0
    symbolic = 0
    breakends = 0
    gvcf_markers = 0
    unchecked_info_number_g_fields: set[str] = set()
    unchecked_format_number_g_fields: set[str] = set()
    base_modification_format_fields: set[str] = set()
    base_modification_slot_assignment_count = 0
    base_modification_slot_assignments: list[dict[str, object]] = []
    unstranded_base_modification_observations: list[dict[str, object]] = []
    unstranded_unphased_observation_count = 0
    vcf45_reference_span_records = 0
    vcf45_max_reference_end = 0
    vcf45_reference_block_sample_count = 0
    active_vcf45_reference_blocks: dict[int, tuple[str, int]] = {}
    structured_header_ids: dict[str, set[str]] = {}
    info_definitions: dict[str, dict[str, str]] = {}
    format_definitions: dict[str, dict[str, str]] = {}
    deletion_intervals: dict[str, list[tuple[int, int, set[int] | None]]] = {}
    spanning_deletion_records: list[tuple[str, int, int, int, set[int] | None]] = []
    unresolved_spanning_deletion_records: list[dict[str, int | str]] = []
    breakend_records_by_id: dict[str, dict] = {}
    breakend_links: list[tuple[str, str, int, int, str, tuple[str, int], int]] = []
    unresolved_breakend_coordinate_links: list[dict[str, object]] = []
    unresolved_breakend_adjacencies: list[dict[str, object]] = []
    breakend_adjacencies: list[dict[str, object]] = []
    breakend_adjacency_keys: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    breakend_phase_vectors_by_record: dict[str, dict[str, dict[str, list[str]]]] = {}
    phase_set_observations: dict[tuple[str, str], list[dict[str, object]]] = {}
    reciprocal_breakend_phase_endpoints: set[frozenset[tuple[int, int, int]]] = set()
    record_ids_seen: set[str] = set()
    current_chrom: str | None = None
    closed_chroms: set[str] = set()
    last_position_on_chrom: int | None = None
    contig_lengths = declared_vcf_contig_lengths(path)
    contig_md5s = declared_vcf_contig_md5s(path)

    with _open(path) as fh:
        for line_no, raw in enumerate(fh, 1):
            if FORBIDDEN_CONTROL_RE.search(raw):
                raise StrictVCFValidationError(
                    f"VCF contains a forbidden control character at line {line_no}",
                    code="VCF_CONTROL_CHARACTER_INVALID",
                )
            if raw and not raw.endswith("\n") and not raw.startswith("#"):
                raise StrictVCFValidationError(
                    f"VCF data line at line {line_no} is missing its required line separator",
                    code="VCF_RECORD_TERMINATOR_MISSING",
                )
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
                if found_header:
                    raise StrictVCFValidationError(
                        f"VCF meta-information appears after the #CHROM header at line {line_no}",
                        code="VCF_HEADER_ORDER_INVALID",
                    )
                header_key, separator, header_value = line[2:].partition("=")
                if separator and header_value.startswith("<") and (
                    header_key in {"INFO", "FORMAT", "FILTER", "ALT", "contig", "SAMPLE", "META"}
                    or fileformat == "VCFv4.5"
                ):
                    identifier = _structured_header_id(
                        line,
                        header_key,
                        line_no,
                        require_id=not (header_key == "PEDIGREE" and fileformat == "VCFv4.5"),
                    )
                    if (
                        header_key == "contig"
                        and fileformat in {"VCFv4.3", "VCFv4.4", "VCFv4.5"}
                        and not VCF_CONTIG_NAME_RE.fullmatch(identifier)
                    ):
                        raise StrictVCFValidationError(
                            f"Contig header ID {identifier!r} violates the VCFv4.3+ SAM reference-name grammar at line {line_no}",
                            code="VCF_CONTIG_HEADER_INVALID",
                        )
                    if identifier:
                        ids_for_type = structured_header_ids.setdefault(header_key, set())
                        if identifier in ids_for_type:
                            raise StrictVCFValidationError(
                                f"Duplicate {header_key} ID {identifier!r} at line {line_no}",
                                code="VCF_HEADER_DEFINITION_INVALID",
                            )
                        ids_for_type.add(identifier)
                if line.startswith("##fileformat="):
                    if fileformat is not None:
                        raise StrictVCFValidationError("Duplicate ##fileformat header", code="VCF_HEADER_INVALID")
                    fileformat = line.split("=", 1)[1]
                if line.startswith("##INFO="):
                    identifier, definition = _parse_field_definition(line, "INFO", line_no, fileformat)
                    if identifier in info_definitions:
                        raise StrictVCFValidationError(
                            f"Duplicate INFO definition for {identifier!r} at line {line_no}",
                            code="VCF_HEADER_DEFINITION_INVALID",
                        )
                    info_definitions[identifier] = definition
                elif line.startswith("##FORMAT="):
                    identifier, definition = _parse_field_definition(line, "FORMAT", line_no, fileformat)
                    if identifier in format_definitions:
                        raise StrictVCFValidationError(
                            f"Duplicate FORMAT definition for {identifier!r} at line {line_no}",
                            code="VCF_HEADER_DEFINITION_INVALID",
                        )
                    format_definitions[identifier] = definition
                    if definition["Number"] == "M":
                        base_modification_format_fields.add(identifier)
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
                if len(columns) == 9:
                    raise StrictVCFValidationError(
                        "FORMAT must be followed by at least one named sample; use exactly the eight fixed columns for a sites-only VCF",
                        code="VCF_HEADER_INVALID",
                    )
                if len(columns) > 9 and len(columns[9:]) != len(set(columns[9:])):
                    raise StrictVCFValidationError("Duplicate sample names are not allowed", code="VCF_SAMPLE_INVALID")
                chrom_header = columns
                found_header = True
                continue
            if line.startswith("#"):
                raise StrictVCFValidationError(
                    f"Unexpected single-hash line at line {line_no}; only #CHROM is a VCF header line",
                    code="VCF_HEADER_INVALID",
                )
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
            if fileformat == "VCFv4.5" and len(fields) > 8:
                for format_key in fields[8].split(":"):
                    if (
                        format_definitions.get(format_key, {}).get("Number") == "M"
                        or _reserved_base_modification_format_definition(format_key) is not None
                    ):
                        base_modification_format_fields.add(format_key)
            _chrom, _pos, alts = _validate_record(fields, line_no, reference_contigs, fileformat, format_definitions)
            if fileformat == "VCFv4.5" and _pos > 0:
                _validate_vcf45_reference_block_coverage(
                    fields,
                    chrom=_chrom,
                    pos=_pos,
                    active_blocks=active_vcf45_reference_blocks,
                    line_no=line_no,
                )
            if _chrom != current_chrom:
                if _chrom in closed_chroms:
                    raise StrictVCFValidationError(
                        f"Contig {_chrom!r} reappears after its VCF block ended at line {line_no}",
                        code="VCF_CHROM_BLOCK_NONCONTIGUOUS",
                    )
                if current_chrom is not None:
                    closed_chroms.add(current_chrom)
                current_chrom = _chrom
                last_position_on_chrom = _pos
            elif last_position_on_chrom is not None and _pos < last_position_on_chrom:
                raise StrictVCFValidationError(
                    f"POS {_pos} is lower than the preceding position {last_position_on_chrom} "
                    f"on contig {_chrom!r} at line {line_no}",
                    code="VCF_POS_ORDER_INVALID",
                )
            else:
                last_position_on_chrom = _pos
            if _pos == 0 or _pos == contig_lengths.get(_chrom, -2) + 1:
                # VCF permits POS=0 as a telomere sentinel. It is not a
                # sequence coordinate accepted by SIRALOOM's small-variant
                # normalizer, so preserve it for explicit review routing.
                telomere_records += 1
            if not alts:
                reference_only += 1
            else:
                alternate_allele_count += len(alts)
            if fields[2] != ".":
                record_ids = fields[2].split(";")
                if len(record_ids) != len(set(record_ids)):
                    raise StrictVCFValidationError(
                        f"Record ID list contains duplicates at line {line_no}",
                        code="VCF_ID_DUPLICATE",
                    )
                duplicate_ids = record_ids_seen.intersection(record_ids)
                if duplicate_ids:
                    duplicate_id = sorted(duplicate_ids)[0]
                    raise StrictVCFValidationError(
                        f"Record ID {duplicate_id!r} was already used before line {line_no}",
                        code="VCF_ID_DUPLICATE",
                    )
                record_ids_seen.update(record_ids)
            info_values = _info_values(fields[7])
            for key, value in info_values.items():
                definition = info_definitions.get(key)
                reserved_definition = _reserved_info_definition_for_version(fileformat, key)
                if reserved_definition is not None:
                    if definition is not None and (
                        definition.get("Number") != reserved_definition["Number"]
                        or definition.get("Type") != reserved_definition["Type"]
                    ):
                        raise StrictVCFValidationError(
                            f"INFO/{key} declaration conflicts with the reserved {fileformat} definition at line {line_no}",
                            code="VCF_RESERVED_INFO_DEFINITION_MISMATCH",
                        )
                    definition = reserved_definition
                if definition is None and not (
                    fileformat in {"VCFv4.1", "VCFv4.2"}
                    and key in VCF41_42_RESERVED_INFO_IDS
                ):
                    raise StrictVCFValidationError(
                        f"INFO/{key} is not reserved for {fileformat} and has no ##INFO declaration at line {line_no}",
                        code="VCF_INFO_UNDECLARED",
                    )
                if definition is not None:
                    # INFO/Number=G has no single sample ploidy to use when a
                    # record carries multiple samples; leave it unresolved here.
                    if definition["Number"] == "G" and value not in {None, "."}:
                        unchecked_info_number_g_fields.add(key)
                    _validate_declared_value(
                        kind="INFO",
                        key=key,
                        value=value,
                        definition=definition,
                        alternate_count=len(alts),
                        line_no=line_no,
                        allow_empty_values=(
                            fileformat == "VCFv4.5" and key in {"MEINFO", "METRANS"}
                        ),
                    )
            if fileformat == "VCFv4.5":
                _validate_vcf45_structural_info(info_values, alts, line_no)
            breakend_alt_indexes = [
                alt_index for alt_index, alt in enumerate(alts)
                if "[" in alt or "]" in alt
            ]
            breakend_alts = [alts[alt_index] for alt_index in breakend_alt_indexes]
            single_breakend_alt_indexes = [
                alt_index
                for alt_index, alt in enumerate(alts)
                if _is_vcf45_breakend_alt(alt) and alt_index not in breakend_alt_indexes
            ]
            for alt_index in single_breakend_alt_indexes:
                unresolved_breakend_adjacencies.append({
                    "record_id": fields[2],
                    "line_number": line_no,
                    "chrom": _chrom,
                    "pos": _pos,
                    "alt_index": alt_index + 1,
                    "alt": alts[alt_index],
                    "status": "UNRESOLVED",
                    "reason_code": "VCF_DERIVATIVE_SINGLE_BREAKEND_HAS_NO_MATE",
                })
            if breakend_alts:
                # Resolve remote loci and classify external assembly contigs before
                # legacy SVTYPE checks so valid-but-unresolvable syntax is not
                # misreported as an invalid BND record.
                remote_loci_by_alt: dict[int, tuple[str, int]] = {}
                orientation_by_alt: dict[int, dict[str, str]] = {}
                for alt_index, alt in zip(breakend_alt_indexes, breakend_alts):
                    match = re.search(r"([\[\]])([^:\[\]]+):([0-9]+)\1", alt)
                    if match is not None:
                        remote_loci_by_alt[alt_index] = (match.group(2), int(match.group(3)))
                        orientation = _breakend_orientation_details(alt)
                        if orientation is not None:
                            orientation_by_alt[alt_index] = orientation
                if fileformat in {"VCFv4.3", "VCFv4.4", "VCFv4.5"}:
                    for remote_contig, _remote_position in remote_loci_by_alt.values():
                        if re.fullmatch(r"<[^<>,\s]+>", remote_contig):
                            raise StrictVCFValidationError(
                                f"External assembly mate contig {remote_contig!r} is valid VCF syntax but unsupported by the configured reference-package contract at line {line_no}",
                                code="VCF_EXTERNAL_ASSEMBLY_CONTIG_UNSUPPORTED",
                            )
                        if not VCF_CONTIG_NAME_RE.fullmatch(remote_contig):
                            raise StrictVCFValidationError(
                                f"Breakend mate contig violates the VCFv4.3+ SAM reference-name grammar at line {line_no}",
                                code="VCF_BREAKEND_ALT_INVALID",
                            )
                # VCFv4.4/4.5 deprecates INFO/SVTYPE; breakpoint notation itself
                # identifies a BND. Earlier supported versions retain the
                # explicit SVTYPE=BND requirement used by earlier VCFv4.0–4.3 source contracts.
                declared_svtype = info_values.get("SVTYPE")
                if (
                    (fileformat not in {"VCFv4.4", "VCFv4.5"} and declared_svtype != "BND")
                    or (fileformat in {"VCFv4.4", "VCFv4.5"} and declared_svtype not in {None, "BND"})
                ):
                    raise StrictVCFValidationError(
                        f"Breakend ALT has an incompatible INFO/SVTYPE value at line {line_no}",
                        code="VCF_BREAKEND_SVTYPE_INVALID",
                    )
                record_ids = set() if fields[2] == "." else set(fields[2].split(";"))
                mate_value = info_values.get("MATEID")
                mate_entries = mate_value.split(",") if mate_value not in {None, ""} else []
                # MATEID is Number=A in VCFv4.4/4.5: preserve the positional
                # association between each ALT allele and its mate record ID.
                # Earlier VCF versions used other cardinality conventions, so
                # retain the legacy compact BND-only list interpretation there.
                if fileformat in {"VCFv4.4", "VCFv4.5"}:
                    if mate_entries and len(mate_entries) != len(alts):
                        raise StrictVCFValidationError(
                            f"VCFv4.4/4.5 MATEID cardinality must match all ALT alleles at line {line_no}",
                            code="VCF_BREAKEND_MATE_INVALID",
                        )
                    mate_entries_by_alt = {
                        alt_index: mate_entries[alt_index]
                        for alt_index in breakend_alt_indexes
                        if alt_index < len(mate_entries)
                    }
                elif len(mate_entries) == len(alts):
                    mate_entries_by_alt = {
                        alt_index: mate_entries[alt_index]
                        for alt_index in breakend_alt_indexes
                    }
                elif len(mate_entries) == len(breakend_alts):
                    mate_entries_by_alt = dict(zip(breakend_alt_indexes, mate_entries))
                elif mate_entries:
                    raise StrictVCFValidationError(
                        f"Breakend MATEID cardinality does not match breakend ALT alleles at line {line_no}",
                        code="VCF_BREAKEND_MATE_INVALID",
                    )
                else:
                    mate_entries_by_alt = {}


                if len(remote_loci_by_alt) != len(breakend_alts):
                    raise StrictVCFValidationError(
                        f"Breakend ALT does not contain one unambiguous mate locus at line {line_no}",
                        code="VCF_BREAKEND_ALT_INVALID",
                    )

                for alt_index in breakend_alt_indexes:
                    mate_id = mate_entries_by_alt.get(alt_index, ".")
                    if mate_id in {"", "."}:
                        unresolved_breakend_adjacencies.append({
                            "record_id": fields[2],
                            "line_number": line_no,
                            "chrom": _chrom,
                            "pos": _pos,
                            "alt_index": alt_index + 1,
                            "alt": alts[alt_index],
                            "remote_locus": {
                                "chrom": remote_loci_by_alt[alt_index][0],
                                "pos": remote_loci_by_alt[alt_index][1],
                            },
                            "orientation": orientation_by_alt.get(alt_index),
                            "status": "UNRESOLVED",
                            "reason_code": "VCF_BREAKEND_MATE_ID_MISSING",
                        })
                        continue
                    if not record_ids:
                        raise StrictVCFValidationError(
                            f"Breakend with INFO/MATEID requires a non-missing record ID at line {line_no}",
                            code="VCF_BREAKEND_MATE_INVALID",
                        )
                    breakend_links.append((
                        fields[2],
                        _chrom,
                        _pos,
                        alt_index,
                        mate_id,
                        remote_loci_by_alt[alt_index],
                        line_no,
                    ))

                for record_id in record_ids:
                    if record_id in breakend_records_by_id:
                        raise StrictVCFValidationError(
                            f"Breakend record ID {record_id!r} is not unique at line {line_no}",
                            code="VCF_BREAKEND_MATE_INVALID",
                        )
                    raw_cipos = info_values.get("CIPOS") if fileformat in {"VCFv4.4", "VCFv4.5"} else None
                    cipos_entries = raw_cipos.split(",") if raw_cipos not in {None, "."} else []
                    cipos_by_alt: dict[int, tuple[int, int] | None] = {}
                    if raw_cipos not in {None, "."} and len(cipos_entries) != 2 * len(alts):
                        raise StrictVCFValidationError(
                            f"VCFv4.4/4.5 CIPOS must contain exactly two offsets per ALT allele at line {line_no}",
                            code="VCF_BREAKEND_CIPOS_INVALID",
                        )
                    for alt_index in breakend_alt_indexes:
                        if raw_cipos is None:
                            # The specification supplies an implicit 0,0 only
                            # when IMPRECISE is also absent.
                            cipos_by_alt[alt_index] = (
                                None if "IMPRECISE" in info_values else (0, 0)
                            )
                            continue
                        if raw_cipos == ".":
                            cipos_by_alt[alt_index] = None
                            continue
                        lower, upper = cipos_entries[2 * alt_index : 2 * alt_index + 2]
                        if lower == "." or upper == ".":
                            cipos_by_alt[alt_index] = None
                            continue
                        lower_offset, upper_offset = int(lower), int(upper)
                        if lower_offset > 0 or upper_offset < 0:
                            raise StrictVCFValidationError(
                                f"VCFv4.4/4.5 CIPOS interval must span zero for ALT {alt_index + 1} at line {line_no}",
                                code="VCF_BREAKEND_CIPOS_INVALID",
                            )
                        cipos_by_alt[alt_index] = (lower_offset, upper_offset)
                    breakend_records_by_id[record_id] = {
                        "chrom": _chrom,
                        "pos": _pos,
                        "alts": alts,
                        "orientation_by_alt": orientation_by_alt,
                        "breakend_alt_indexes": breakend_alt_indexes,
                        "remote_loci_by_alt": remote_loci_by_alt,
                        "mate_entries_by_alt": mate_entries_by_alt,
                        "cipos_by_alt": cipos_by_alt,
                        "line_no": line_no,
                    }
            format_keys = fields[8].split(":") if len(fields) > 8 else []
            gt_index = format_keys.index("GT") if "GT" in format_keys else None
            for sample_index, sample in enumerate(fields[9:], start=1):
                sample_values = sample.split(":")
                if fileformat in {"VCFv4.4", "VCFv4.5"} and "PSL" in format_keys:
                    psl_index = format_keys.index("PSL")
                    psl_value = sample_values[psl_index] if psl_index < len(sample_values) else "."
                    gt_value = (
                        sample_values[format_keys.index("GT")]
                        if "GT" in format_keys and format_keys.index("GT") < len(sample_values)
                        else "."
                    )
                    if gt_value == "." and psl_value not in {"", "."}:
                        raise StrictVCFValidationError(
                            f"FORMAT/PSL cannot assign phase sets to a fully missing GT at line {line_no}, sample {sample_index}",
                            code="VCF_PHASE_SET_INVALID",
                        )
                    if "GT" not in format_keys and psl_value not in {"", "."}:
                        raise StrictVCFValidationError(
                            f"FORMAT/PSL requires FORMAT/GT at line {line_no}, sample {sample_index}",
                            code="VCF_PHASE_SET_INVALID",
                        )
                    if gt_value not in {"", "."} and psl_value not in {"", "."}:
                        psl_entries = psl_value.split(",")
                        allele_phase = _gt_alleles_with_phase(gt_value, fileformat, line_no)
                        if len(psl_entries) == len(allele_phase) and any(
                            separator != "|" and phase_set != "."
                            for (_allele, separator), phase_set in zip(allele_phase, psl_entries)
                        ):
                            raise StrictVCFValidationError(
                                f"FORMAT/PSL must use '.' for every unphased GT allele at line {line_no}, sample {sample_index}",
                                code="VCF_PHASE_SET_INVALID",
                            )
                    for dependent_key in ("PSO", "PSQ"):
                        if dependent_key not in format_keys:
                            continue
                        dependent_index = format_keys.index(dependent_key)
                        dependent_value = (
                            sample_values[dependent_index]
                            if dependent_index < len(sample_values)
                            else "."
                        )
                        if dependent_value in {"", "."}:
                            continue
                        if psl_value in {"", "."}:
                            raise StrictVCFValidationError(
                                f"FORMAT/{dependent_key} requires populated FORMAT/PSL at line {line_no}, sample {sample_index}",
                                code="VCF_PHASE_SET_INVALID",
                            )
                        dependent_entries = dependent_value.split(",")
                        psl_entries = psl_value.split(",")
                        if len(dependent_entries) == len(psl_entries) and any(
                            phase_set == "." and dependent_entry != "."
                            for phase_set, dependent_entry in zip(psl_entries, dependent_entries)
                        ):
                            raise StrictVCFValidationError(
                                f"FORMAT/{dependent_key} must use '.' where the corresponding PSL value is missing at line {line_no}, sample {sample_index}",
                                code="VCF_PHASE_SET_INVALID",
                            )
                elif fileformat in {"VCFv4.4", "VCFv4.5"} and any(
                    key in format_keys
                    and format_keys.index(key) < len(sample_values)
                    and sample_values[format_keys.index(key)] not in {"", "."}
                    for key in ("PSO", "PSQ")
                ):
                    raise StrictVCFValidationError(
                        f"FORMAT/PSO and FORMAT/PSQ require FORMAT/PSL at line {line_no}, sample {sample_index}",
                        code="VCF_PHASE_SET_INVALID",
                    )
                if fileformat in {"VCFv4.4", "VCFv4.5"} and "PS" in format_keys and "PSL" in format_keys:
                    ps_value = sample_values[format_keys.index("PS")] if format_keys.index("PS") < len(sample_values) else "."
                    psl_value = sample_values[format_keys.index("PSL")] if format_keys.index("PSL") < len(sample_values) else "."
                    if ps_value not in {"", "."} and psl_value not in {"", "."}:
                        raise StrictVCFValidationError(
                            f"FORMAT/PS and FORMAT/PSL cannot both be populated for one sample at line {line_no}",
                            code="VCF_PHASE_SET_INVALID",
                        )
                if gt_index is None:
                    # The VCF specification defines diploidy as the default
                    # when a Number=G FORMAT field is present without GT.
                    genotype_ploidy = 2
                elif gt_index >= len(sample_values) or sample_values[gt_index] == "":
                    raise StrictVCFValidationError(
                        f"FORMAT/GT must contain an explicit genotype or missing-value token at line {line_no}, sample {sample_index}",
                        code="VCF_GENOTYPE_INVALID",
                    )
                else:
                    # A missing GT value still carries ploidy: "." is haploid,
                    # "./." is diploid, and so on.
                    genotype_ploidy = len(_gt_allele_tokens(sample_values[gt_index], fileformat, line_no))
                if fileformat in {"VCFv4.4", "VCFv4.5"} and "PSL" in format_keys and gt_index is not None:
                    gt_for_phase = sample_values[gt_index]
                    if gt_for_phase not in {"", "."}:
                        allele_phase = _gt_alleles_with_phase(gt_for_phase, fileformat, line_no)
                        psl_raw = (
                            sample_values[format_keys.index("PSL")]
                            if format_keys.index("PSL") < len(sample_values)
                            else "."
                        )
                        psl_entries = psl_raw.split(",") if psl_raw not in {"", "."} else ["."] * len(allele_phase)
                        pso_raw = (
                            sample_values[format_keys.index("PSO")]
                            if "PSO" in format_keys and format_keys.index("PSO") < len(sample_values)
                            else "."
                        )
                        pso_entries = pso_raw.split(",") if pso_raw not in {"", "."} else ["."] * len(allele_phase)
                        sample_name = chrom_header[8 + sample_index] if chrom_header is not None and 8 + sample_index < len(chrom_header) else str(sample_index)
                        for allele_position, ((allele_token, _separator), phase_set) in enumerate(zip(allele_phase, psl_entries)):
                            if phase_set in {"", "."}:
                                continue
                            allele_is_sv_or_breakend = False
                            if allele_token != ".":
                                allele_number = int(allele_token)
                                if 0 < allele_number <= len(alts):
                                    allele_text = alts[allele_number - 1]
                                    allele_is_sv_or_breakend = _is_vcf44_plus_sv_or_breakend_alt(allele_text)
                            allele_number = int(allele_token) if allele_token != "." else None
                            allele_value = (
                                fields[3] if allele_number == 0
                                else alts[allele_number - 1] if allele_number is not None and 0 < allele_number <= len(alts)
                                else "."
                            )
                            phase_set_observations.setdefault((sample_name, phase_set), []).append({
                                "line_number": line_no,
                                "record_index": records + 1,
                                "record_id": fields[2],
                                "chrom": _chrom,
                                "pos": _pos,
                                "allele_position": allele_position,
                                "allele_index": allele_number,
                                "allele": allele_value,
                                "pso": pso_entries[allele_position] if allele_position < len(pso_entries) else ".",
                                "requires_pso": allele_is_sv_or_breakend,
                            })
                local_allele_count: int | None = None
                local_alt_indexes: list[int] = []
                if fileformat == "VCFv4.5" and "LAA" in format_keys and format_keys.index("LAA") < len(sample_values):
                    raw_laa = sample_values[format_keys.index("LAA")]
                    if raw_laa in {"", "."}:
                        # The VCFv4.5 local-allele example uses an empty
                        # LAA value for the REF-only local allele vector;
                        # BCF represents the same zero-length vector as MISSING.
                        local_allele_count = 1
                    else:
                        try:
                            local_alt_indexes = [int(item) for item in raw_laa.split(",")]
                        except ValueError as exc:
                            raise StrictVCFValidationError(
                                f"FORMAT/LAA contains a non-integer ALT index at line {line_no}",
                                code="VCF_LOCAL_ALLELE_INVALID",
                            ) from exc
                        if any(index < 1 or index > len(alts) for index in local_alt_indexes) or len(local_alt_indexes) != len(set(local_alt_indexes)):
                            raise StrictVCFValidationError(
                                f"FORMAT/LAA must contain distinct 1-based ALT indices at line {line_no}",
                                code="VCF_LOCAL_ALLELE_INVALID",
                            )
                        local_allele_count = len(local_alt_indexes) + 1
                    # LAA defines the ALT alleles in play for this sample.
                    # Every called non-reference GT allele must therefore be
                    # represented in LAA; LAA may additionally contain <*> for
                    # reference-block semantics or alleles used by likelihoods.
                    if gt_index is not None and gt_index < len(sample_values):
                        sample_gt = sample_values[gt_index]
                        if sample_gt not in {"", "."}:
                            called_alt_indexes = {
                                int(allele)
                                for allele in _gt_allele_tokens(sample_gt, fileformat, line_no)
                                if allele != "." and int(allele) > 0
                            }
                            if not called_alt_indexes.issubset(set(local_alt_indexes if raw_laa != "." else [])):
                                raise StrictVCFValidationError(
                                    f"FORMAT/LAA omits a called GT ALT allele at line {line_no}, sample {sample_index}",
                                    code="VCF_LOCAL_ALLELE_INVALID",
                                )
                for format_position, key in enumerate(format_keys):
                    value = sample_values[format_position] if format_position < len(sample_values) else "."
                    if fileformat == "VCFv4.5" and key == "LAA" and value == "":
                        # VCFv4.5's REF-only local-allele example uses an
                        # empty text value; BCF represents this as MISSING.
                        continue
                    definition = format_definitions.get(key)
                    reserved_definition = _reserved_format_definition_for_version(fileformat, key)
                    if fileformat in {"VCFv4.1", "VCFv4.2"} and key == "GLE":
                        if definition is None:
                            raise StrictVCFValidationError(
                                "VCFv4.1/4.2 FORMAT/GLE is reserved, but the source prose does not specify a Number cardinality; an explicit header definition is required.",
                                code="VCF_RESERVED_FORMAT_DEFINITION_UNRESOLVED",
                            )
                        if definition.get("Type") != "String":
                            raise StrictVCFValidationError(
                                "VCFv4.1/4.2 FORMAT/GLE must be declared as Type=String.",
                                code="VCF_RESERVED_FORMAT_DEFINITION_MISMATCH",
                            )
                    if reserved_definition is not None:
                        if definition is not None and (
                            definition.get("Number") != reserved_definition["Number"]
                            or (
                                definition.get("Type") != reserved_definition["Type"]
                                and not (
                                    reserved_definition["Type"] == "Numeric"
                                    and definition.get("Type") in {"Integer", "Float", "Numeric"}
                                )
                            )
                        ):
                            raise StrictVCFValidationError(
                                f"FORMAT/{key} declaration conflicts with the reserved {fileformat} definition at line {line_no}",
                                code="VCF_RESERVED_FORMAT_DEFINITION_MISMATCH",
                            )
                        definition = reserved_definition
                    if definition is None:
                        raise StrictVCFValidationError(
                            f"FORMAT/{key} is not reserved and has no ##FORMAT declaration at line {line_no}",
                            code="VCF_FORMAT_UNDECLARED",
                        )
                    if definition is not None:
                        if (
                            fileformat == "VCFv4.0"
                            and key == "GL"
                            and value not in {None, "."}
                            and len(alts) != 1
                        ):
                            raise StrictVCFValidationError(
                                f"VCFv4.0 FORMAT/GL is not applicable to multiallelic records at line {line_no}",
                                code="VCF_FIELD_CARDINALITY_INVALID",
                            )
                        if (
                            fileformat in {"VCFv4.4", "VCFv4.5"}
                            and definition["Number"] == "P"
                            and value not in {None, "."}
                            and gt_index is None
                        ):
                            raise StrictVCFValidationError(
                                f"Populated VCFv4.4/4.5 FORMAT Number=P field {key!r} requires GT to establish per-allele cardinality at line {line_no}, sample {sample_index}",
                                code="VCF_FIELD_CARDINALITY_INVALID",
                            )
                        if (
                            definition["Number"] == "G"
                            and genotype_ploidy is None
                            and value not in {None, "."}
                        ):
                            unchecked_format_number_g_fields.add(key)
                        base_modification_cardinality = None
                        base_modification_slots: list[tuple[int, int, str, str]] = []
                        if definition["Number"] == "M":
                            if gt_index is None or gt_index >= len(sample_values):
                                raise StrictVCFValidationError(
                                    f"VCFv4.5 base-modification field {key!r} has no sample GT at line {line_no}",
                                    code="VCF_BASE_MODIFICATION_GT_MISSING",
                                )
                            base_modification_slots = _expected_base_modification_slots(
                                sample_values[gt_index],
                                fields[3].upper(),
                                alts,
                                key,
                                fileformat,
                                line_no,
                            )
                            base_modification_cardinality = len(base_modification_slots)
                        _validate_declared_value(
                            kind=f"FORMAT sample {sample_index}",
                            key=key,
                            value=value,
                            definition=definition,
                            alternate_count=len(alts),
                            line_no=line_no,
                            ploidy=genotype_ploidy,
                            local_allele_count=local_allele_count,
                            base_modification_cardinality=base_modification_cardinality,
                        )
                        if definition["Number"] == "M" and value not in {None, "."}:
                            observed_modification_values = value.split(",")
                            base_modification_slot_assignment_count += len(base_modification_slots)
                        elif definition["Number"] == "M":
                            observed_modification_values = ["."] * len(base_modification_slots)
                        if (
                            definition["Number"] == "M"
                            and base_modification_strandedness == "unstranded"
                        ):
                            gt_for_modification = sample_values[gt_index]
                            gt_phase = _gt_alleles_with_phase(
                                gt_for_modification, fileformat, line_no
                            )
                            psl_for_modification = (
                                sample_values[format_keys.index("PSL")]
                                if "PSL" in format_keys and format_keys.index("PSL") < len(sample_values)
                                else None
                            )
                            ps_for_modification = (
                                sample_values[format_keys.index("PS")]
                                if "PS" in format_keys and format_keys.index("PS") < len(sample_values)
                                else None
                            )
                            psl_positions = (
                                psl_for_modification.split(",")
                                if psl_for_modification not in {None, "", "."}
                                else []
                            )
                            haplotype_slots = _expected_base_modification_slots_with_haplotype(
                                gt_for_modification,
                                fields[3].upper(),
                                alts,
                                key,
                                fileformat,
                                line_no,
                            )
                            for slot_index, (allele_index, copy_index, sequence_position, strand, sequence_base) in enumerate(haplotype_slots):
                                _allele_token, phase_separator = gt_phase[copy_index]
                                all_called_alleles = [
                                    token for token, _separator in gt_phase
                                ]
                                homozygous_unphased = (
                                    "|" not in gt_for_modification
                                    and all(token != "." for token in all_called_alleles)
                                    and len(set(all_called_alleles)) == 1
                                )
                                fully_phased = "|" in gt_for_modification and all(
                                    separator == "|" for _token, separator in gt_phase
                                )
                                if homozygous_unphased:
                                    phase_set = "__unphased_homozygous_set__"
                                elif not fully_phased:
                                    phase_set = f"__record_{records + 1}_allele_{allele_index}"
                                elif psl_positions:
                                    phase_set = psl_positions[copy_index] if copy_index < len(psl_positions) else "."
                                    if phase_set == ".":
                                        phase_set = f"__record_{records + 1}_allele_{allele_index}"
                                elif ps_for_modification not in {None, "", "."}:
                                    phase_set = f"PS:{ps_for_modification}"
                                else:
                                    # VCFv4.4/4.5 defines phased genotypes without
                                    # PS as belonging to the same implicit phase set.
                                    phase_set = "__implicit_phased_set__"
                                allele_sequence = (
                                    fields[3].upper()
                                    if allele_index == 0
                                    else alts[allele_index - 1]
                                )
                                if len(allele_sequence) != len(fields[3]):
                                    raise StrictVCFValidationError(
                                        f"Unstranded Number=M cross-record placement cannot be coordinate-mapped for length-changing allele {allele_index} at line {line_no}",
                                        code="VCF_BASE_MODIFICATION_UNSTRANDED_UNSUPPORTED",
                                    )
                                observed_value = (
                                    observed_modification_values[slot_index]
                                    if slot_index < len(observed_modification_values)
                                    else "."
                                )
                                if phase_set.startswith("__record_"):
                                    unstranded_unphased_observation_count += 1
                                unstranded_base_modification_observations.append({
                                    "sample": chrom_header[8 + sample_index] if chrom_header is not None and 8 + sample_index < len(chrom_header) else str(sample_index),
                                    "chrom": _chrom,
                                    "field_id": key,
                                    "coordinate": _pos + sequence_position,
                                    "record_index": records + 1,
                                    "line_number": line_no,
                                    "copy_index": copy_index,
                                    "phase_set": phase_set,
                                    "phase_known": True,
                                    "strand": strand,
                                    "base": sequence_base,
                                    "value": None if observed_value == "." else observed_value,
                                })
                        if definition["Number"] == "M" and include_base_modification_slot_assignments:
                            sample_name = (
                                chrom_header[8 + sample_index]
                                if chrom_header is not None and 8 + sample_index < len(chrom_header)
                                else None
                            )
                            for value_index, (slot, observed_value) in enumerate(
                                zip(base_modification_slots, observed_modification_values)
                            ):
                                allele_index, sequence_position, strand, sequence_base = slot
                                base_modification_slot_assignments.append({
                                    "record_index": records + 1,
                                    "line_number": line_no,
                                    "chrom": _chrom,
                                    "pos": _pos,
                                    "sample_index": sample_index,
                                    "sample_name": sample_name,
                                    "field_id": key,
                                    "value_index": value_index,
                                    "allele_index": allele_index,
                                    "allele_sequence_position": sequence_position,
                                    "sequence_base": sequence_base,
                                    "strand": strand,
                                    "value": None if observed_value == "." else observed_value,
                                })
                if fileformat in {"VCFv4.4", "VCFv4.5"} and breakend_alts and record_ids:
                    record_phase_vectors: dict[str, dict[str, list[str]]] = {}
                    sample_names = chrom_header[9:] if chrom_header is not None else []
                    for sample_offset, sample_name in enumerate(sample_names):
                        sample_values_for_phase = fields[9 + sample_offset].split(":")
                        gt_value = (
                            sample_values_for_phase[gt_index]
                            if gt_index is not None and gt_index < len(sample_values_for_phase)
                            else "."
                        )
                        gt_phase = (
                            _gt_alleles_with_phase(gt_value, fileformat, line_no)
                            if gt_value not in {"", "."}
                            else [(".", "|")]
                        )
                        psl_value = (
                            sample_values_for_phase[format_keys.index("PSL")]
                            if "PSL" in format_keys and format_keys.index("PSL") < len(sample_values_for_phase)
                            else "."
                        )
                        pso_value = (
                            sample_values_for_phase[format_keys.index("PSO")]
                            if "PSO" in format_keys and format_keys.index("PSO") < len(sample_values_for_phase)
                            else "."
                        )
                        psl_entries = (
                            psl_value.split(",")
                            if psl_value not in {"", "."}
                            else ["."] * len(gt_phase)
                        )
                        pso_entries = (
                            pso_value.split(",")
                            if pso_value not in {"", "."}
                            else ["."] * len(gt_phase)
                        )
                        record_phase_vectors[sample_name] = {
                            "alleles": [allele for allele, _separator in gt_phase],
                            "psl": psl_entries,
                            "pso": pso_entries,
                        }
                    for record_id in record_ids:
                        breakend_phase_vectors_by_record[record_id] = record_phase_vectors

                if fileformat == "VCFv4.5":
                    _validate_local_field_equivalence(
                        format_keys=format_keys,
                        sample_values=sample_values,
                        alternate_count=len(alts),
                        local_alt_indexes=local_alt_indexes,
                        ploidy=genotype_ploidy,
                        line_no=line_no,
                        sample_index=sample_index,
                    )

            if fileformat == "VCFv4.5" and _pos > 0:
                record_span = compute_vcf45_record_span(fields, line_no)
                if record_span is not None:
                    vcf45_reference_span_records += 1
                    vcf45_max_reference_end = max(vcf45_max_reference_end, record_span[0])
                    vcf45_reference_block_sample_count += len(record_span[1])
                    declared_contig_length = contig_lengths.get(_chrom)
                    if declared_contig_length is not None and record_span[0] > declared_contig_length:
                        raise StrictVCFValidationError(
                            f"Computed VCFv4.5 reference span END={record_span[0]} exceeds declared contig {_chrom} length {declared_contig_length} at line {line_no}",
                            code="VCF_REFERENCE_SPAN_OUT_OF_BOUNDS",
                        )
                    for sample_index, block_length in record_span[1]:
                        active_vcf45_reference_blocks[sample_index] = (
                            _chrom,
                            _pos + block_length - 1,
                        )

            def carriers(alt_index: int) -> set[int] | None:
                record_format_keys = fields[8].split(":") if len(fields) > 8 else []
                record_gt_index = (
                    record_format_keys.index("GT") if "GT" in record_format_keys else None
                )
                if len(fields) <= 9 or record_gt_index is None:
                    return None
                result: set[int] = set()
                for sample_index, sample in enumerate(fields[9:]):
                    values = sample.split(":")
                    if record_gt_index >= len(values):
                        continue
                    gt = values[record_gt_index]
                    if gt in {"", "."}:
                        continue
                    # GT syntax was already validated for this record above.
                    # Compare the validated allele tokens directly so a parse
                    # exception cannot silently erase a called '*' carrier.
                    called = _gt_allele_tokens(gt, fileformat, line_no)
                    if str(alt_index) in called:
                        result.add(sample_index)
                return result

            if _pos > 0 and "*" in alts:
                spanning_deletion_records.append((_chrom, _pos, line_no, records + 1, carriers(alts.index("*") + 1)))
            for alt_index, alternate in enumerate(alts, start=1):
                if _pos == 0:
                    continue
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
                if _is_vcf45_breakend_alt(alt):
                    breakends += 1
                if alt == "<NON_REF>":
                    gvcf_markers += 1

    if fileformat not in SUPPORTED_VCF_VERSIONS:
        raise StrictVCFValidationError(
            f"Unsupported or missing ##fileformat header: {fileformat!r}; supported standardized VCF versions are VCFv4.0 through VCFv4.5",
            code="VCF_FILEFORMAT_UNSUPPORTED",
        )
    if base_modification_strandedness is not None and fileformat != "VCFv4.5":
        raise StrictVCFValidationError(
            "The base-modification strandedness policy is defined here only for VCFv4.5 Number=M fields.",
            code="VCF_BASE_MODIFICATION_POLICY_UNSUPPORTED",
        )
    if not found_header or chrom_header is None:
        raise StrictVCFValidationError("VCF is missing the #CHROM header", code="VCF_HEADER_INVALID")
    if records == 0:
        raise StrictVCFValidationError("VCF contains no variant records", code="VCF_EMPTY")
    if fileformat == "VCFv4.5" and base_modification_strandedness == "unstranded":
        # Compare only observations on the same sample, phase set and phased
        # GT copy. Unphased alleles cannot be safely joined across records.
        phased_groups: dict[tuple[str, str, str, str, int], dict[int, list[dict[str, object]]]] = {}
        for observation in unstranded_base_modification_observations:
            if not observation["phase_known"]:
                continue
            group_key = (
                str(observation["sample"]),
                str(observation["chrom"]),
                str(observation["field_id"]),
                str(observation["phase_set"]),
                int(observation["copy_index"]),
            )
            phased_groups.setdefault(group_key, {}).setdefault(
                int(observation["coordinate"]), []
            ).append(observation)
        for group_key, by_coordinate in phased_groups.items():
            field_id = group_key[2]
            modified_base = field_id[-1].upper()
            if modified_base == "U":
                modified_base = "T"
            if modified_base == "N":
                for coordinate, observations in by_coordinate.items():
                    for observation in observations:
                        if observation["strand"] == "-" and observation["value"] is not None:
                            raise StrictVCFValidationError(
                                f"Unstranded N base-modification values must be MISSING on the negative strand at {group_key[1]}:{coordinate}, sample {group_key[0]}",
                                code="VCF_BASE_MODIFICATION_UNSTRANDED_PLACEMENT",
                            )
                continue
            complement = {"A": "T", "T": "A", "C": "G", "G": "C"}[modified_base]
            for coordinate, observations in by_coordinate.items():
                next_observations = by_coordinate.get(coordinate + 1, [])
                for lower in observations:
                    for upper in next_observations:
                        lower_positive = lower["base"] == modified_base and lower["strand"] == "+"
                        upper_negative = upper["base"] == complement and upper["strand"] == "-"
                        lower_negative = lower["base"] == complement and lower["strand"] == "-"
                        upper_positive = upper["base"] == modified_base and upper["strand"] == "+"
                        if lower_positive and upper_negative and upper["value"] is not None:
                            raise StrictVCFValidationError(
                                f"Unstranded complementary base-modification value must be MISSING at higher POS {group_key[1]}:{coordinate + 1}, sample {group_key[0]}",
                                code="VCF_BASE_MODIFICATION_UNSTRANDED_PLACEMENT",
                            )
                        if lower_negative and upper_positive and upper["value"] is not None:
                            raise StrictVCFValidationError(
                                f"Unstranded complementary base-modification value must be MISSING at higher POS {group_key[1]}:{coordinate + 1}, sample {group_key[0]}",
                                code="VCF_BASE_MODIFICATION_UNSTRANDED_PLACEMENT",
                            )

    if fileformat in {"VCFv4.4", "VCFv4.5"}:
        for (sample_name, phase_set), observations in phase_set_observations.items():
            phase_set_requires_pso = any(bool(item["requires_pso"]) for item in observations)
            if phase_set_requires_pso:
                missing = [item for item in observations if item["pso"] in {"", "."}]
                if missing:
                    first = missing[0]
                    raise StrictVCFValidationError(
                        f"FORMAT/PSO is required for sample {sample_name!r}, phase set {phase_set!r} because that phase set contains an SV or breakpoint allele; missing at line {first['line_number']}, allele position {first['allele_position'] + 1}",
                        code="VCF_PHASE_SET_PSO_REQUIRED",
                    )

    for (
        source_id,
        chrom,
        pos,
        source_alt_index,
        mate_id,
        remote_locus,
        line_no,
    ) in breakend_links:
        source_ids = set(source_id.split(";"))
        mate = breakend_records_by_id.get(mate_id)
        if mate is None:
            raise StrictVCFValidationError(
                f"Breakend MATEID {mate_id!r} has no corresponding record at line {line_no}",
                code="VCF_BREAKEND_MATE_MISSING",
            )
        source_record = breakend_records_by_id.get(source_id.split(";")[0])
        if source_record is None or mate["chrom"] != remote_locus[0]:
            raise StrictVCFValidationError(
                f"Breakend MATEID {mate_id!r} does not match the remote contig for ALT allele {source_alt_index + 1} at line {line_no}",
                code="VCF_BREAKEND_MATE_COORDINATE_MISMATCH",
            )

        reciprocal_id_alt_indexes = [
            mate_alt_index
            for mate_alt_index in mate["breakend_alt_indexes"]
            if mate["mate_entries_by_alt"].get(mate_alt_index, ".") in source_ids
        ]
        if not reciprocal_id_alt_indexes:
            raise StrictVCFValidationError(
                f"Breakend MATEID {mate_id!r} does not refer back to record {source_id!r} at line {line_no}",
                code="VCF_BREAKEND_MATE_NOT_RECIPROCAL",
            )
        reciprocal_alt_indexes = [
            mate_alt_index
            for mate_alt_index in reciprocal_id_alt_indexes
            if _breakend_remote_coordinate_within_cipos(remote_locus, mate, mate_alt_index)
            and _breakend_remote_coordinate_within_cipos(
                mate["remote_loci_by_alt"].get(mate_alt_index, ("", -1)),
                source_record,
                source_alt_index,
            )
        ]
        if not reciprocal_alt_indexes:
            raise StrictVCFValidationError(
                f"Breakend mate record {mate_id!r} does not point back to {chrom}:{pos} at line {line_no}",
                code="VCF_BREAKEND_MATE_COORDINATE_MISMATCH",
            )
        if len(reciprocal_alt_indexes) != 1:
            raise StrictVCFValidationError(
                f"Breakend MATEID {mate_id!r} has an ambiguous reciprocal ALT for record {source_id!r} at line {line_no}",
                code="VCF_BREAKEND_MATE_AMBIGUOUS",
            )

        mate_alt_index = reciprocal_alt_indexes[0]
        unresolved_ends = []
        if source_record["cipos_by_alt"].get(source_alt_index) is None:
            unresolved_ends.append("source")
        if mate["cipos_by_alt"].get(mate_alt_index) is None:
            unresolved_ends.append("mate")
        if unresolved_ends:
            unresolved_breakend_coordinate_links.append({
                "source_record_id": source_id,
                "source_alt_index": source_alt_index + 1,
                "mate_record_id": mate_id,
                "mate_alt_index": mate_alt_index + 1,
                "line_number": line_no,
                "unresolved_cipos_ends": unresolved_ends,
            })

        adjacency_key = tuple(sorted((
            (int(source_record["line_no"]), source_alt_index),
            (int(mate["line_no"]), mate_alt_index),
        )))
        adjacency = next(
            (item for item in breakend_adjacencies if item["key"] == adjacency_key),
            None,
        )
        if adjacency is None:
            source_orientation = source_record["orientation_by_alt"].get(source_alt_index)
            mate_orientation = mate["orientation_by_alt"].get(mate_alt_index)
            adjacency = {
                "key": adjacency_key,
                "adjacency_id": (
                    f"{source_record['line_no']}:{source_alt_index + 1}"
                    f"<->{mate['line_no']}:{mate_alt_index + 1}"
                ),
                "source": {
                    "record_id": source_id,
                    "line_number": source_record["line_no"],
                    "chrom": chrom,
                    "pos": pos,
                    "alt_index": source_alt_index + 1,
                    "alt": source_record["alts"][source_alt_index],
                    "orientation": source_orientation,
                },
                "mate": {
                    "record_id": mate_id,
                    "line_number": mate["line_no"],
                    "chrom": mate["chrom"],
                    "pos": mate["pos"],
                    "alt_index": mate_alt_index + 1,
                    "alt": mate["alts"][mate_alt_index],
                    "orientation": mate_orientation,
                },
                "coordinate_status": (
                    "UNRESOLVED_CIPOS" if unresolved_ends else "WITHIN_CIPOS_INTERVALS"
                ),
                "sample_phase_correspondence": {},
            }
            breakend_adjacencies.append(adjacency)
        if fileformat in {"VCFv4.4", "VCFv4.5"}:
            source_vectors = breakend_phase_vectors_by_record.get(source_id.split(";")[0], {})
            mate_vectors = breakend_phase_vectors_by_record.get(mate_id, {})
            source_allele_number = str(source_alt_index + 1)
            mate_allele_number = str(mate_alt_index + 1)
            for sample_name in set(source_vectors) | set(mate_vectors):
                source_sample = source_vectors.get(sample_name, {})
                mate_sample = mate_vectors.get(sample_name, {})
                source_psl = source_sample.get("psl", [])
                source_pso = source_sample.get("pso", [])
                mate_psl = mate_sample.get("psl", [])
                mate_pso = mate_sample.get("pso", [])
                source_positions = [
                    position
                    for position, allele in enumerate(source_sample.get("alleles", []))
                    if allele == source_allele_number
                ]
                mate_positions = [
                    position
                    for position, allele in enumerate(mate_sample.get("alleles", []))
                    if allele == mate_allele_number
                ]
                source_signature = [
                    (
                        source_psl[position] if position < len(source_psl) else ".",
                        source_pso[position] if position < len(source_pso) else ".",
                    )
                    for position in source_positions
                ]
                mate_signature = [
                    (
                        mate_psl[position] if position < len(mate_psl) else ".",
                        mate_pso[position] if position < len(mate_pso) else ".",
                    )
                    for position in mate_positions
                ]
                if source_signature != mate_signature:
                    raise StrictVCFValidationError(
                        f"Breakend ALT alleles {source_alt_index + 1} and {mate_alt_index + 1} in records {source_id!r} and {mate_id!r} must carry matching FORMAT/PSL and FORMAT/PSO value pairs for sample {sample_name!r}",
                        code="VCF_BREAKEND_PHASE_SET_MISMATCH",
                    )
                source_by_signature: dict[tuple[str, str], list[int]] = {}
                mate_by_signature: dict[tuple[str, str], list[int]] = {}
                for position in source_positions:
                    signature = (
                        source_psl[position] if position < len(source_psl) else ".",
                        source_pso[position] if position < len(source_pso) else ".",
                    )
                    source_by_signature.setdefault(signature, []).append(position)
                for position in mate_positions:
                    signature = (
                        mate_psl[position] if position < len(mate_psl) else ".",
                        mate_pso[position] if position < len(mate_pso) else ".",
                    )
                    mate_by_signature.setdefault(signature, []).append(position)
                paired_copy_count = 0
                ambiguous_copy_signatures = []
                for signature, source_signature_positions in source_by_signature.items():
                    mate_signature_positions = mate_by_signature.get(signature, [])
                    # A unique PSL/PSO pair identifies a corresponding phased
                    # copy even if it occupies a different GT vector position
                    # in the reciprocal record. Repeated identical pairs do
                    # not identify copy correspondence and remain unresolved.
                    if signature[0] in {"", "."} or signature[1] in {"", "."}:
                        continue
                    if len(source_signature_positions) != 1 or len(mate_signature_positions) != 1:
                        ambiguous_copy_signatures.append(signature)
                        continue
                    source_position = source_signature_positions[0]
                    mate_position = mate_signature_positions[0]
                    reciprocal_breakend_phase_endpoints.add(frozenset((
                        (
                            int(source_record["line_no"]),
                            source_position,
                            int(source_allele_number),
                        ),
                        (
                            int(mate["line_no"]),
                            mate_position,
                            int(mate_allele_number),
                        ),
                    )))
                    paired_copy_count += 1
                adjacency["sample_phase_correspondence"][sample_name] = {
                    "status": (
                        "UNRESOLVED_DUPLICATE_PHASE_COPY_IDENTIFIERS"
                        if ambiguous_copy_signatures
                        else "MATCHED"
                    ),
                    "paired_copy_count": paired_copy_count,
                    "ambiguous_phase_pairs": [
                        {"psl": item[0], "pso": item[1]}
                        for item in ambiguous_copy_signatures
                    ],
                }
    phase_set_traversal_orders: list[dict[str, object]] = []
    phase_set_traversal_warnings: list[dict[str, object]] = []
    if fileformat in {"VCFv4.4", "VCFv4.5"}:
        for (sample_name, phase_set), observations in phase_set_observations.items():
            by_ordinal: dict[int, list[dict[str, object]]] = {}
            for observation in observations:
                raw_ordinal = observation["pso"]
                # Preserve every populated PSL/PSO allele position, including
                # reference GT alleles used by the normative tandem-duplication
                # example. PSO is an ordering annotation, not an ALT-only field.
                if raw_ordinal in {"", "."}:
                    continue
                ordinal = int(str(raw_ordinal))
                by_ordinal.setdefault(ordinal, []).append(observation)
            ordered_events = []
            unresolved_ordinal_tie_count = 0
            for ordinal, ordinal_observations in sorted(by_ordinal.items()):
                endpoints = {
                    (
                        int(item["line_number"]),
                        int(item["allele_position"]),
                        int(item["allele_index"]),
                    )
                    for item in ordinal_observations
                    if item["allele_index"] is not None
                }
                matching_reciprocal_pairs = {
                    frozenset((endpoint, other))
                    for endpoint in endpoints
                    for other in endpoints
                    if endpoint != other
                    and frozenset((endpoint, other)) in reciprocal_breakend_phase_endpoints
                }
                is_reciprocal_pair = (
                    len(matching_reciprocal_pairs) == 1
                    and endpoints == set(next(iter(matching_reciprocal_pairs), ()))
                )
                has_ordinal_tie = len(endpoints) > 1 and not is_reciprocal_pair
                if has_ordinal_tie:
                    unresolved_ordinal_tie_count += 1
                    phase_set_traversal_warnings.append({
                        "code": "VCF_PHASE_SET_PSO_ORDINAL_TIE_UNRESOLVED",
                        "sample": sample_name,
                        "phase_set": phase_set,
                        "ordinal": ordinal,
                        "line_numbers": sorted({int(item["line_number"]) for item in ordinal_observations}),
                    })
                ordered_events.append({
                    "ordinal": ordinal,
                    "event_kind": (
                        "RECIPROCAL_BREAKEND_EVENT"
                        if is_reciprocal_pair
                        else "ORDINAL_TIE_UNRESOLVED"
                        if has_ordinal_tie
                        else "SINGLE_TRAVERSAL_EVENT"
                    ),
                    "occurrences": [
                        {
                            "record_index": item["record_index"],
                            "record_id": item["record_id"],
                            "line_number": item["line_number"],
                            "chrom": item["chrom"],
                            "pos": item["pos"],
                            "allele_position": item["allele_position"],
                            "allele_index": item["allele_index"],
                            "allele": item["allele"],
                            "phase_set": phase_set,
                            "pso": item["pso"],
                            "requires_pso": bool(item["requires_pso"]),
                        }
                        for item in ordinal_observations
                    ],
                })
            if ordered_events:
                phase_set_traversal_orders.append({
                    "sample": sample_name,
                    "phase_set": phase_set,
                    "traversal_status": (
                        "UNRESOLVED_ORDINAL_TIES"
                        if unresolved_ordinal_tie_count
                        else "ORDERED"
                    ),
                    "unresolved_ordinal_tie_count": unresolved_ordinal_tie_count,
                    "ordered_events": ordered_events,
                })

    unresolved_breakend_adjacencies_by_endpoint: dict[tuple[int, int], list[dict[str, object]]] = {}
    for unresolved_adjacency in unresolved_breakend_adjacencies:
        unresolved_endpoint_key = (
            int(unresolved_adjacency["line_number"]),
            int(unresolved_adjacency["alt_index"]),
        )
        unresolved_breakend_adjacencies_by_endpoint.setdefault(
            unresolved_endpoint_key, []
        ).append(unresolved_adjacency)

    breakend_adjacencies_by_endpoint: dict[tuple[int, int], list[dict[str, object]]] = {}
    for adjacency in breakend_adjacencies:
        for endpoint in (adjacency["source"], adjacency["mate"]):
            endpoint_key = (
                int(endpoint["line_number"]),
                int(endpoint["alt_index"]),
            )
            breakend_adjacencies_by_endpoint.setdefault(endpoint_key, []).append(adjacency)

    derivative_chromosome_traversals: list[dict[str, object]] = []
    for traversal in phase_set_traversal_orders:
        ordered_events = []
        unresolved_reason_codes: set[str] = set()
        unresolved_adjacency_count = 0
        observed_adjacency_ids: set[str] = set()
        for event in traversal["ordered_events"]:
            event_occurrences = []
            for occurrence in event["occurrences"]:
                allele_index = occurrence["allele_index"]
                allele = str(occurrence["allele"])
                matched_adjacencies = (
                    breakend_adjacencies_by_endpoint.get(
                        (int(occurrence["line_number"]), int(allele_index)),
                        [],
                    )
                    if allele_index is not None and int(allele_index) > 0
                    else []
                )
                if _is_vcf45_breakend_alt(allele) and allele_index is not None and int(allele_index) > 0:
                    if matched_adjacencies:
                        for adjacency in matched_adjacencies:
                            observed_adjacency_ids.add(str(adjacency["adjacency_id"]))
                    else:
                        unresolved_adjacency_count += 1
                        unresolved_entries = unresolved_breakend_adjacencies_by_endpoint.get(
                            (int(occurrence["line_number"]), int(allele_index)),
                            [],
                        )
                        if unresolved_entries:
                            unresolved_reason_codes.update(
                                str(item["reason_code"]) for item in unresolved_entries
                            )
                        else:
                            unresolved_reason_codes.add(
                                "VCF_DERIVATIVE_BREAKEND_ADJACENCY_UNRESOLVED"
                            )
                event_occurrences.append({
                    **occurrence,
                    "breakend_adjacency_ids": [
                        str(adjacency["adjacency_id"])
                        for adjacency in matched_adjacencies
                    ],
                })
            ordered_events.append({
                "ordinal": event["ordinal"],
                "event_kind": event["event_kind"],
                "occurrences": event_occurrences,
            })
            if event["event_kind"] == "ORDINAL_TIE_UNRESOLVED":
                unresolved_reason_codes.add("VCF_PHASE_SET_PSO_ORDINAL_TIE_UNRESOLVED")

        related_adjacencies = [
            {
                key: value
                for key, value in adjacency.items()
                if key != "key"
            }
            for adjacency in breakend_adjacencies
            if str(adjacency["adjacency_id"]) in observed_adjacency_ids
        ]
        if any(item["coordinate_status"] == "UNRESOLVED_CIPOS" for item in related_adjacencies):
            unresolved_reason_codes.add("VCF_BREAKEND_COORDINATE_UNCERTAINTY_UNRESOLVED")
        event_order_status = (
            "RECONSTRUCTED"
            if traversal["traversal_status"] == "ORDERED"
            else "UNRESOLVED"
        )
        derivative_chromosome_traversals.append({
            "sample": traversal["sample"],
            "phase_set": traversal["phase_set"],
            "event_order_status": event_order_status,
            "adjacency_status": (
                "COMPLETE_FOR_OBSERVED_PAIRED_BREAKENDS"
                if unresolved_adjacency_count == 0
                else "PARTIAL_OR_UNRESOLVED"
            ),
            "sequence_status": "UNRESOLVED_INSUFFICIENT_REFERENCE_SEGMENT_EVIDENCE",
            "unresolved_reason_codes": sorted(unresolved_reason_codes | {
                "VCF_DERIVATIVE_SEQUENCE_REQUIRES_REFERENCE_SEGMENT_AND_COPY_NUMBER_RECONSTRUCTION"
            }),
            "unresolved_adjacency_count": unresolved_adjacency_count,
            "ordered_events": ordered_events,
            "observed_breakend_adjacencies": related_adjacencies,
        })

    for chrom, pos, line_no, record_index, star_carriers in spanning_deletion_records:
        if star_carriers is not None and not star_carriers:
            continue
        overlaps = [
            deletion_carriers
            for start, end, deletion_carriers in deletion_intervals.get(chrom, ())
            if start <= pos <= end
        ]
        if star_carriers is None:
            # Site-only VCFs have no sample genotypes to reconcile. In a
            # sample-bearing VCF, missing GT cannot establish sample context.
            context_exists = len(chrom_header or []) == 8 and bool(overlaps)
        else:
            context_exists = any(
                deletion_carriers is not None
                and bool(star_carriers & deletion_carriers)
                for deletion_carriers in overlaps
            )
        if not overlaps or not context_exists:
            unresolved_spanning_deletion_records.append({
                "record_index": record_index,
                "line_number": line_no,
                "chrom": chrom,
                "pos": pos,
                "reason_code": "UNRESOLVED_SPANNING_DELETION_CONTEXT",
            })

    return {
        "fileformat": fileformat,
        "records": records,
        "alternate_allele_count": alternate_allele_count,
        "reference_only_records": reference_only,
        "telomere_records": telomere_records,
        "multiallelic_records": multiallelic,
        "symbolic_records": symbolic,
        "breakend_records": breakends,
        "phase_set_traversal_orders": phase_set_traversal_orders,
        "phase_set_traversal_warnings": phase_set_traversal_warnings,
        "phase_set_traversal_unresolved_count": len(phase_set_traversal_warnings),
        "derivative_chromosome_traversals": derivative_chromosome_traversals,
        "breakend_adjacencies": [
            {key: value for key, value in adjacency.items() if key != "key"}
            for adjacency in breakend_adjacencies
        ],
        "unresolved_breakend_adjacencies": unresolved_breakend_adjacencies,
        "unresolved_breakend_adjacency_count": len(unresolved_breakend_adjacencies),
        "unresolved_breakend_coordinate_count": len(unresolved_breakend_coordinate_links),
        "unresolved_breakend_coordinate_links": unresolved_breakend_coordinate_links,
        "gvcf_markers": gvcf_markers,
        "spanning_deletion_records": [
            {
                "record_index": record_index,
                "line_number": line_no,
                "chrom": chrom,
                "pos": pos,
                "called_sample_count": len(star_carriers) if star_carriers is not None else None,
            }
            for chrom, pos, line_no, record_index, star_carriers in spanning_deletion_records
        ],
        "unresolved_spanning_deletion_record_count": len(unresolved_spanning_deletion_records),
        "unresolved_spanning_deletion_records": unresolved_spanning_deletion_records,
        "unchecked_info_number_g_fields": sorted(unchecked_info_number_g_fields),
        "unchecked_format_number_g_fields": sorted(unchecked_format_number_g_fields),
        "base_modification_format_fields": sorted(base_modification_format_fields),
        "base_modification_slot_assignment_count": base_modification_slot_assignment_count,
        "base_modification_strandedness_policy": base_modification_strandedness,
        "unstranded_base_modification_observation_count": len(unstranded_base_modification_observations),
        "unstranded_base_modification_unresolved_phase_observation_count": unstranded_unphased_observation_count,
        **({"base_modification_slot_assignments": base_modification_slot_assignments} if include_base_modification_slot_assignments else {}),
        "vcf45_reference_span_records": vcf45_reference_span_records,
        "vcf45_max_reference_end": vcf45_max_reference_end,
        "vcf45_reference_block_sample_count": vcf45_reference_block_sample_count,
        "sample_count": max(0, len(chrom_header) - 9),
        "reference_contig_policy": "EXACT_OR_EXPLICIT_ALIAS" if reference_contigs is not None else "NOT_CHECKED",
        "declared_contig_md5s": contig_md5s,
        "compression": compression,
        "warning_codes": (
            (["VCF_BGZF_EOF_MARKER_MISSING"]
             if compression.get("format") == "BGZF" and not compression.get("eof_marker_present")
             else [])
            + (["VCF_SPANNING_DELETION_CONTEXT_UNRESOLVED"]
               if unresolved_spanning_deletion_records else [])
            + (["VCF_BASE_MODIFICATION_UNSTRANDED_PHASE_CONTEXT_UNRESOLVED"]
               if unstranded_unphased_observation_count else [])
            + (["VCF_BREAKEND_COORDINATE_UNCERTAINTY_UNRESOLVED"]
               if unresolved_breakend_coordinate_links else [])
        ),
    }


def validate_vcf_reference_alleles(path: str | Path, reference_fasta: str | Path) -> dict:
    """Check reference spans and disclose records that cannot be REF-checked.

    This deliberately includes records routed away from sequence normalization
    (GVCF blocks, symbolic SVs, breakends, and spanning-deletion records), so a
    successful partial analysis cannot conceal a selected-reference mismatch.
    """
    from backend.app.domain.reference import FastaReference, ReferenceError

    checked_records = 0
    checked_breakend_mates = 0
    telomere_records = 0
    declared_contig_lengths = declared_vcf_contig_lengths(path)
    declared_contig_md5s = declared_vcf_contig_md5s(path)
    try:
        with FastaReference(reference_fasta) as reference, _open(path) as handle:
            # Resolve only the deterministic aliases explicitly supported by
            # FastaReference (for example NC_012920.1 -> chrM). Unknown or
            # version-mismatched accessions remain hard failures; no network
            # lookup, assembly conversion, or heuristic contig substitution occurs.
            resolved_contigs: dict[str, str] = {}
            for contig, declared_length in declared_contig_lengths.items():
                try:
                    resolved_contig = FastaReference.resolve_contig_name(contig, reference.contigs)
                    reference_length = reference.contig_length(resolved_contig)
                except ReferenceError as exc:
                    raise StrictVCFValidationError(
                        f"Declared VCF contig {contig!r} cannot be resolved in the selected reference",
                        code="REFERENCE_CONTIG_MISMATCH",
                    ) from exc
                resolved_contigs[contig] = resolved_contig
                if declared_length != reference_length:
                    raise StrictVCFValidationError(
                        f"VCF declares contig {contig!r} length {declared_length}, but resolved selected-reference contig {resolved_contig!r} has length {reference_length}",
                        code="VCF_CONTIG_LENGTH_MISMATCH",
                    )
            for contig, expected_md5 in declared_contig_md5s.items():
                try:
                    resolved_contig = resolved_contigs.get(contig)
                    if resolved_contig is None:
                        resolved_contig = FastaReference.resolve_contig_name(contig, reference.contigs)
                        resolved_contigs[contig] = resolved_contig
                    reference_length = reference.contig_length(resolved_contig)
                except ReferenceError as exc:
                    raise StrictVCFValidationError(
                        f"VCF contig {contig!r} with an MD5 declaration cannot be resolved in the selected reference",
                        code="REFERENCE_CONTIG_MISMATCH",
                    ) from exc
                digest = hashlib.md5(usedforsecurity=False)
                for start in range(0, reference_length, 1_000_000):
                    sequence = reference.fetch(resolved_contig, start, min(start + 1_000_000, reference_length))
                    canonical_sequence = "".join(
                        character for character in sequence if 33 <= ord(character) <= 126
                    ).upper()
                    digest.update(canonical_sequence.encode("ascii"))
                if digest.hexdigest() != expected_md5:
                    raise StrictVCFValidationError(
                        f"VCF contig {contig!r} MD5 does not match the selected reference sequence",
                        code="VCF_CONTIG_MD5_MISMATCH",
                    )
            fileformat: str | None = None
            for line_no, raw in enumerate(handle, 1):
                if raw.startswith("##fileformat="):
                    fileformat = raw.rstrip("\r\n").split("=", 1)[1]
                    continue
                if not raw or raw.startswith("#"):
                    continue
                fields = raw.rstrip("\r\n").split("\t")
                if len(fields) < 8:
                    continue  # validate_vcf_strict reports the structural error first.
                chrom, pos_text, _identifier, ref, alt_text = fields[:5]
                pos = int(pos_text)
                try:
                    resolved_chrom = resolved_contigs.get(chrom)
                    if resolved_chrom is None:
                        resolved_chrom = FastaReference.resolve_contig_name(chrom, reference.contigs)
                        resolved_contigs[chrom] = resolved_chrom
                    contig_length = reference.contig_length(resolved_chrom)
                except ReferenceError as exc:
                    raise StrictVCFValidationError(
                        f"VCF contig {chrom!r} cannot be resolved in the selected reference at line {line_no}",
                        code="REFERENCE_CONTIG_MISMATCH",
                    ) from exc
                if pos == 0:
                    # POS=0 is a VCF telomere sentinel, not a 1-based FASTA
                    # interval. Preserve it for review routing without
                    # claiming that this record passed REF validation.
                    telomere_records += 1
                    continue
                if pos == contig_length + 1:
                    # The selected reference, not an untrusted VCF header,
                    # confirms the N+1 telomere sentinel.
                    telomere_records += 1
                    continue
                try:
                    observed = reference.fetch(resolved_chrom, pos - 1, pos - 1 + len(ref))
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
                info = _info_values(fields[7])
                if fileformat == "VCFv4.5":
                    span = compute_vcf45_record_span(fields, line_no)
                    end = span[0] if span is not None else pos + len(ref) - 1
                else:
                    end = int(info["END"]) if info.get("END") not in {None, "."} else None
                if end is not None and end > contig_length:
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
                        resolved_mate_contig = resolved_contigs.get(mate_contig)
                        if resolved_mate_contig is None:
                            resolved_mate_contig = FastaReference.resolve_contig_name(mate_contig, reference.contigs)
                            resolved_contigs[mate_contig] = resolved_mate_contig
                        mate_length = reference.contig_length(resolved_mate_contig)
                    except ReferenceError as exc:
                        raise StrictVCFValidationError(
                            f"Breakend mate contig {mate_contig!r} cannot be resolved in the selected reference at line {line_no}",
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
        "unvalidated_telomere_record_count": telomere_records,
        "reference_fasta": str(reference_fasta),
        "resolved_contig_aliases": {
            source: resolved
            for source, resolved in resolved_contigs.items()
            if source != resolved
        },
        "result": "PARTIAL" if telomere_records else "PASS",
    }
