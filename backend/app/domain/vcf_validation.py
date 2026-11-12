from __future__ import annotations

import gzip
import hashlib
import re
import struct
import zlib
from contextlib import contextmanager
from math import comb, isnan
from pathlib import Path

from backend.app.domain.vcf_caller_profiles import inspect_caller_provenance

SUPPORTED_VCF_VERSIONS = frozenset({f"VCFv4.{minor}" for minor in range(0, 6)})
STANDARD_COLUMNS = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO"]
DNA_RE = re.compile(r"^[ACGTN]+$")
VCF_CONTIG_NAME_RE = re.compile(
    r"^[0-9A-Za-z!#$%&+./:;?@^_|~-][0-9A-Za-z!#$%&*+./:;=?@^_|~-]*$"
)
SYMBOLIC_RE = re.compile(r"^<[^<>,\s]+>$")
BREAKEND_RE = re.compile(
    r"^(?:[ACGTNacgtn.]+(?P<left>[\[\]])[^:\[\]\s]+:[1-9][0-9]*(?P=left)|"
    r"(?P<right>[\[\]])[^:\[\]\s]+:[1-9][0-9]*(?P=right)[ACGTNacgtn.]+)$"
)

def _alt_identity_key(allele: str) -> tuple[str, ...]:
    """Return VCF allele identity while respecting sequence and contig case rules."""
    if DNA_RE.fullmatch(allele):
        return ("SEQUENCE", allele.upper())
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
    ("FORMAT", "PP"), ("FORMAT", "PQ"), ("FORMAT", "PS"),
    ("FORMAT", "PSO"), ("FORMAT", "PSQ"),
})
PROBABILITY_FLOAT_FIELDS = frozenset({("INFO", "AF"), ("FORMAT", "GP")})
NONNEGATIVE_FLOAT_FIELDS = frozenset({("INFO", "BQ"), ("INFO", "MQ")})
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
    """Return the fixed VCFv4.0 reserved FORMAT definitions."""
    reserved = {
        "DP": ("1", "Integer"),
        "FT": ("1", "String"),
        "GL": ("3", "Float"),
        # VCFv4.0 describes GQ/HQ as numeric (not an integer-only type).
        # Float is the permissive implicit representation; explicit headers
        # may declare either Integer or Float.
        "GQ": ("1", "Float"),
        "HQ": ("2", "Float"),
    }
    definition = reserved.get(field_id)
    if definition is None:
        return None
    return {"Number": definition[0], "Type": definition[1]}


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
    }
    definition = reserved.get(field_id)
    if definition is not None:
        return {"Number": definition[0], "Type": definition[1]}
    return _reserved_base_modification_format_definition(field_id)


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
    if fileformat == "VCFv4.5" and kind == "FORMAT":
        allowed_cardinality.update({"LA", "LR", "LG", "P", "M"})
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
    reserved_vcf40_definition = None
    if fileformat == "VCFv4.0" and kind == "FORMAT":
        reserved_vcf40_definition = _reserved_vcf40_format_definition(identifier)
    reserved_vcf40_type_matches = (
        parsed["Type"] == reserved_vcf40_definition["Type"]
        if reserved_vcf40_definition is not None
        else True
    )
    if (
        fileformat == "VCFv4.0"
        and kind == "FORMAT"
        and identifier in {"GQ", "HQ"}
    ):
        reserved_vcf40_type_matches = parsed["Type"] in {"Integer", "Float"}
    if reserved_vcf40_definition is not None and (
        number != reserved_vcf40_definition["Number"]
        or not reserved_vcf40_type_matches
    ):
        raise StrictVCFValidationError(
            f"Reserved VCFv4.0 FORMAT field {identifier!r} requires "
            f"Number={reserved_vcf40_definition['Number']} and "
            f"Type={reserved_vcf40_definition['Type']} at line {line_no}",
            code="VCF_HEADER_DEFINITION_INVALID",
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
    caller_profile_id: str | None = None,
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
                if (field_scope, key) in PROBABILITY_FLOAT_FIELDS and not (
                    field_scope == "FORMAT"
                    and key == "GP"
                    and caller_profile_id == "dragen_snv_germline"
                ):
                    valid = 0.0 <= numeric_value <= 1.0
                if (field_scope, key) in NONNEGATIVE_FLOAT_FIELDS:
                    valid = numeric_value >= 0.0
                if _base_modification_field_kind(key) == "fraction":
                    valid = valid and 0.0 <= numeric_value <= 1.0
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
                        code="VCF_SV_INFO_INTERVAL_INVALID",
                    )
                continue
            lower_offset, upper_offset = int(lower), int(upper)
            if key == "CIPOS" and (lower_offset > 0 or upper_offset < 0):
                raise StrictVCFValidationError(
                    f"INFO/CIPOS interval must span zero at line {line_no}",
                    code="VCF_SV_INFO_INTERVAL_INVALID",
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


def _base_modification_allele_count(sequence: str, modified_base: str) -> int:
    """Count modifiable positions on both strands of one concrete allele."""
    base = "T" if modified_base == "U" else modified_base
    if base == "N":
        return 2 * len(sequence)
    complement = {"A": "T", "T": "A", "C": "G", "G": "C"}[base]
    return sum(1 for nucleotide in sequence if nucleotide in {base, complement})


def _expected_base_modification_cardinality(
    genotype: str,
    reference: str,
    alternates: list[str],
    field_id: str,
    fileformat: str | None,
    line_no: int,
) -> int:
    """Calculate VCFv4.5 Number=M cardinality from GT and allele sequences.

    Identical unphased allele values are aggregated at their first occurrence;
    phased copies remain distinct. Missing and symbolic alleles contribute no
    modifiable bases, as required by VCFv4.5.
    """
    seen_unphased_alleles: set[int] = set()
    expected = 0
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
        if DNA_RE.fullmatch(allele_sequence):
            expected += _base_modification_allele_count(
                allele_sequence, modified_base
            )
    return expected


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
            allele.upper() if re.fullmatch(r"[ACGTNacgtn]+", allele) else allele
            for allele in raw_alts
        ]
    )
    if any(
        not DNA_RE.fullmatch(a) and not SYMBOLIC_RE.fullmatch(a) and not BREAKEND_RE.fullmatch(a) and a != "*"
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
            or any(key in {"LAA", "LAD", "LADF", "LADR", "LGL", "LGP", "LPL", "LPP"} for key in keys)
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


def validate_vcf_strict(path: str | Path, *, reference_contigs: set[str] | None = None) -> dict:
    source = Path(path)
    compression: dict[str, int | str | bool] = {"format": "NONE"}
    if source.name.lower().endswith((".vcf.gz", ".vcf.bgz")):
        compression = _verify_bgzf(source)
    # Resolve only a narrowly supported caller-specific value convention
    # before record-level validation. Header metadata remains unverified.
    header_caller_provenance = inspect_caller_provenance(source)
    header_value_semantics_profile_id = (
        "dragen_snv_germline"
        if header_caller_provenance.get("dragen_gp_phred_semantics_applicable")
        else None
    )
    fileformat: str | None = None
    chrom_header: list[str] | None = None
    found_header = False
    records = 0
    sample_record_count = 0
    sample_records_without_gt = 0
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
    breakend_links: list[tuple[str, str, int, set[str], list[tuple[str, int]], int]] = []
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
            if len(fields) > 9:
                sample_record_count += 1
                record_format_keys = fields[8].split(":") if fields[8] not in {"", "."} else []
                if "GT" not in record_format_keys:
                    sample_records_without_gt += 1
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
            _chrom, _pos, alts = _validate_record(
                fields, line_no, reference_contigs, fileformat, format_definitions,
            )
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
                if definition is None and fileformat == "VCFv4.5":
                    definition = _reserved_vcf45_info_definition(key)
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
                        caller_profile_id=header_value_semantics_profile_id,
                    )
            if fileformat == "VCFv4.5":
                _validate_vcf45_structural_info(info_values, alts, line_no)
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
                if fileformat in {"VCFv4.3", "VCFv4.4", "VCFv4.5"} and any(
                    not VCF_CONTIG_NAME_RE.fullmatch(contig) for contig, _position in remote_loci
                ):
                    raise StrictVCFValidationError(
                        f"Breakend mate contig violates the VCFv4.3+ SAM reference-name grammar at line {line_no}",
                        code="VCF_BREAKEND_ALT_INVALID",
                    )
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
            if fileformat == "VCFv4.0" and "GL" in format_keys and len(alts) != 1:
                gl_index = format_keys.index("GL")
                for sample_index, sample in enumerate(fields[9:], start=1):
                    gl_values = sample.split(":")
                    gl_value = gl_values[gl_index] if gl_index < len(gl_values) else "."
                    if gl_value not in {"", "."}:
                        raise StrictVCFValidationError(
                            f"VCFv4.0 FORMAT/GL is defined only for biallelic records at line {line_no}, sample {sample_index}",
                            code="VCF_FIELD_CARDINALITY_INVALID",
                        )
            for sample_index, sample in enumerate(fields[9:], start=1):
                sample_values = sample.split(":")
                if "PSL" in format_keys:
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
                elif any(
                    key in format_keys
                    and format_keys.index(key) < len(sample_values)
                    and sample_values[format_keys.index(key)] not in {"", "."}
                    for key in ("PSO", "PSQ")
                ):
                    raise StrictVCFValidationError(
                        f"FORMAT/PSO and FORMAT/PSQ require FORMAT/PSL at line {line_no}, sample {sample_index}",
                        code="VCF_PHASE_SET_INVALID",
                    )
                if "PS" in format_keys and "PSL" in format_keys:
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
                local_allele_count: int | None = None
                local_alt_indexes: list[int] = []
                if fileformat == "VCFv4.5" and "LAA" in format_keys and format_keys.index("LAA") < len(sample_values):
                    raw_laa = sample_values[format_keys.index("LAA")]
                    if raw_laa == ".":
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
                for key, value in zip(format_keys, sample_values):
                    definition = format_definitions.get(key)
                    if definition is None and fileformat == "VCFv4.0":
                        definition = _reserved_vcf40_format_definition(key)
                    if definition is None and fileformat == "VCFv4.5":
                        definition = _reserved_vcf45_format_definition(key)
                    if definition is not None:
                        if (
                            definition["Number"] == "P"
                            and value not in {None, "."}
                            and gt_index is None
                        ):
                            raise StrictVCFValidationError(
                                f"Populated FORMAT/{key} with Number=P requires a sample GT at line {line_no}, sample {sample_index}",
                                code="VCF_FIELD_CARDINALITY_INVALID",
                            )
                        if (
                            definition["Number"] == "G"
                            and genotype_ploidy is None
                            and value not in {None, "."}
                        ):
                            unchecked_format_number_g_fields.add(key)
                        base_modification_cardinality = None
                        if definition["Number"] == "M":
                            if gt_index is None or gt_index >= len(sample_values):
                                raise StrictVCFValidationError(
                                    f"VCFv4.5 base-modification field {key!r} has no sample GT at line {line_no}",
                                    code="VCF_BASE_MODIFICATION_GT_MISSING",
                                )
                            base_modification_cardinality = (
                                _expected_base_modification_cardinality(
                                    sample_values[gt_index],
                                    fields[3].upper(),
                                    alts,
                                    key,
                                    fileformat,
                                    line_no,
                                )
                            )
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
                            caller_profile_id=header_value_semantics_profile_id,
                        )
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
                if "[" in alt or "]" in alt:
                    breakends += 1
                if alt == "<NON_REF>":
                    gvcf_markers += 1

    if fileformat not in SUPPORTED_VCF_VERSIONS:
        raise StrictVCFValidationError(
            f"Unsupported or missing ##fileformat header: {fileformat!r}; supported standardized VCF versions are VCFv4.0 through VCFv4.5",
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
        "caller_provenance": inspect_caller_provenance(
            path,
            fileformat=fileformat,
            gvcf_marker_count=gvcf_markers,
            sample_record_count=sample_record_count,
            sample_records_without_gt=sample_records_without_gt,
        ),
        "records": records,
        "alternate_allele_count": alternate_allele_count,
        "reference_only_records": reference_only,
        "telomere_records": telomere_records,
        "multiallelic_records": multiallelic,
        "symbolic_records": symbolic,
        "breakend_records": breakends,
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
