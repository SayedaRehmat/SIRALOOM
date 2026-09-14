from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class ReferenceError(ValueError):
    pass


@dataclass(frozen=True)
class FaiEntry:
    name: str
    length: int
    offset: int
    line_bases: int
    line_width: int


class FastaReference:
    """Random-access FASTA reader backed by a .fai index.

    Phase 1 deliberately requires an indexed, uncompressed FASTA.  This avoids
    loading a human reference genome into RAM and keeps coordinate lookups
    deterministic. BGZF/FASTA indexing can be added behind the same interface.
    """

    def __init__(self, fasta_path: str | Path, fai_path: str | Path | None = None):
        self.fasta_path = Path(fasta_path)
        self.fai_path = Path(fai_path) if fai_path else Path(f"{self.fasta_path}.fai")
        if not self.fasta_path.exists():
            raise ReferenceError(f"Reference FASTA not found: {self.fasta_path}")
        if not self.fai_path.exists():
            raise ReferenceError(
                f"Reference FASTA index (.fai) not found: {self.fai_path}. "
                "Run a validated faidx process before use."
            )
        self._entries = self._load_fai()
        self._handle = self.fasta_path.open("rb")

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> "FastaReference":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _load_fai(self) -> dict[str, FaiEntry]:
        entries: dict[str, FaiEntry] = {}
        for line_no, line in enumerate(self.fai_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            fields = line.split("\t")
            if len(fields) < 5:
                raise ReferenceError(f"Malformed FASTA index at line {line_no}")
            try:
                name, length, offset, line_bases, line_width = fields[:5]
                entry = FaiEntry(name, int(length), int(offset), int(line_bases), int(line_width))
            except ValueError as exc:
                raise ReferenceError(f"Malformed numeric FASTA index field at line {line_no}") from exc
            if entry.line_bases <= 0 or entry.line_width < entry.line_bases:
                raise ReferenceError(f"Invalid FASTA index geometry at line {line_no}")
            entries[name] = entry
        if not entries:
            raise ReferenceError("FASTA index contains no sequences")
        return entries

    @staticmethod
    def _aliases(contig: str) -> list[str]:
        c = contig.strip()
        aliases = [c]
        bare = c.removeprefix("chr")
        prefixed = f"chr{bare}"
        if bare not in aliases:
            aliases.append(bare)
        if prefixed not in aliases:
            aliases.append(prefixed)
        if bare.upper() in {"M", "MT"}:
            for candidate in ("M", "MT", "chrM", "chrMT"):
                if candidate not in aliases:
                    aliases.append(candidate)
        return aliases

    def resolve_contig(self, contig: str) -> str:
        for candidate in self._aliases(contig):
            if candidate in self._entries:
                return candidate
        raise ReferenceError(f"Contig {contig!r} is not present in the reference")

    def fetch(self, contig: str, start0: int, end0: int) -> str:
        if start0 < 0 or end0 < start0:
            raise ReferenceError("Invalid zero-based reference interval")
        name = self.resolve_contig(contig)
        entry = self._entries[name]
        if end0 > entry.length:
            raise ReferenceError(
                f"Reference interval exceeds {name}: {start0}-{end0}, length={entry.length}"
            )
        if start0 == end0:
            return ""

        out = bytearray()
        cursor = start0
        remaining = end0 - start0
        while remaining:
            line_idx = cursor // entry.line_bases
            in_line = cursor % entry.line_bases
            take = min(remaining, entry.line_bases - in_line)
            file_offset = entry.offset + line_idx * entry.line_width + in_line
            self._handle.seek(file_offset)
            chunk = self._handle.read(take)
            if len(chunk) != take:
                raise ReferenceError("Unexpected EOF while reading reference")
            out.extend(chunk)
            cursor += take
            remaining -= take
            if remaining:
                # Newline bytes are skipped implicitly by the next calculated offset.
                continue
        return out.decode("ascii").upper()

    def base(self, contig: str, pos1: int) -> str:
        if pos1 <= 0:
            raise ReferenceError("Reference coordinates are 1-based and must be positive")
        return self.fetch(contig, pos1 - 1, pos1)

    def contig_length(self, contig: str) -> int:
        return self._entries[self.resolve_contig(contig)].length
