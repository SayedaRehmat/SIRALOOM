from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


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

    Phase 1 deliberately requires an indexed, uncompressed FASTA. This avoids
    loading a human reference genome into RAM and keeps coordinate lookups
    deterministic.
    """

    def __init__(self, fasta_path: str | Path, fai_path: str | Path | None = None):
        self.fasta_path = Path(fasta_path)
        self.fai_path = (
            Path(fai_path)
            if fai_path
            else Path(f"{self.fasta_path}.fai")
        )

        if not self.fasta_path.exists():
            raise ReferenceError(
                f"Reference FASTA not found: {self.fasta_path}"
            )

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

        for line_no, line in enumerate(
            self.fai_path.read_text(encoding="utf-8").splitlines(),
            1,
        ):
            if not line.strip():
                continue

            fields = line.split("\t")

            if len(fields) < 5:
                raise ReferenceError(
                    f"Malformed FASTA index at line {line_no}"
                )

            try:
                name, length, offset, line_bases, line_width = fields[:5]

                entry = FaiEntry(
                    name=name,
                    length=int(length),
                    offset=int(offset),
                    line_bases=int(line_bases),
                    line_width=int(line_width),
                )
            except ValueError as exc:
                raise ReferenceError(
                    f"Malformed numeric FASTA index field at line {line_no}"
                ) from exc

            if entry.line_bases <= 0 or entry.line_width < entry.line_bases:
                raise ReferenceError(
                    f"Invalid FASTA index geometry at line {line_no}"
                )

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

        raise ReferenceError(
            f"Contig {contig!r} is not present in the reference"
        )

    def fetch(
        self,
        contig: str,
        start0: int,
        end0: int,
    ) -> str:
        if start0 < 0 or end0 < start0:
            raise ReferenceError(
                "Invalid zero-based reference interval"
            )

        name = self.resolve_contig(contig)
        entry = self._entries[name]

        if end0 > entry.length:
            raise ReferenceError(
                f"Reference interval exceeds {name}: "
                f"{start0}-{end0}, length={entry.length}"
            )

        if start0 == end0:
            return ""

        out = bytearray()
        cursor = start0
        remaining = end0 - start0

        while remaining:
            line_idx = cursor // entry.line_bases
            in_line = cursor % entry.line_bases
            take = min(
                remaining,
                entry.line_bases - in_line,
            )

            file_offset = (
                entry.offset
                + line_idx * entry.line_width
                + in_line
            )

            self._handle.seek(file_offset)
            chunk = self._handle.read(take)

            if len(chunk) != take:
                raise ReferenceError(
                    "Unexpected EOF while reading reference"
                )

            out.extend(chunk)

            cursor += take
            remaining -= take

        return out.decode("ascii").upper()

    def base(self, contig: str, pos1: int) -> str:
        if pos1 <= 0:
            raise ReferenceError(
                "Reference coordinates are 1-based and must be positive"
            )

        return self.fetch(contig, pos1 - 1, pos1)

    def contig_length(self, contig: str) -> int:
        return self._entries[
            self.resolve_contig(contig)
        ].length


class EnsemblReference:
    """Reference sequence provider backed by the Ensembl REST API.

    This is intended for development/integration use when a local indexed
    FASTA is not available.

    GRCh38:
        https://rest.ensembl.org

    GRCh37:
        https://grch37.rest.ensembl.org

    The provider keeps a bounded in-memory window around the requested
    coordinate so normalization does not perform one HTTP request for every
    individual base.
    """

    def __init__(
        self,
        genome_build: str,
        *,
        grch38_endpoint: str = "https://rest.ensembl.org",
        grch37_endpoint: str = "https://grch37.rest.ensembl.org",
        timeout_seconds: float = 10.0,
        window_flank: int = 1000,
    ):
        build = genome_build.strip()

        if build not in {"GRCh37", "GRCh38"}:
            raise ReferenceError(
                f"Unsupported remote reference build: {genome_build}"
            )

        self.genome_build = build

        self.endpoint = (
            grch38_endpoint
            if build == "GRCh38"
            else grch37_endpoint
        ).rstrip("/")

        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.window_flank = max(0, int(window_flank))

        self._cache: dict[
            tuple[str, int, int],
            str,
        ] = {}

    @staticmethod
    def _aliases(contig: str) -> list[str]:
        c = contig.strip()

        if not c:
            raise ReferenceError("Reference contig cannot be empty")

        aliases = [c]

        bare = c.removeprefix("chr")

        if bare not in aliases:
            aliases.append(bare)

        if bare in {"M", "MT"}:
            for candidate in ("MT", "M"):
                if candidate not in aliases:
                    aliases.append(candidate)

        return aliases

    def resolve_contig(self, contig: str) -> str:
        # Ensembl accepts chromosome names without the "chr" prefix.
        # Prefer the bare representation.
        aliases = self._aliases(contig)

        for candidate in aliases:
            if candidate.startswith("chr"):
                continue
            return candidate

        return aliases[0]

    def _fetch_remote(
        self,
        contig: str,
        start1: int,
        end1: int,
    ) -> str:
        if start1 < 1 or end1 < start1:
            raise ReferenceError(
                "Invalid 1-based Ensembl reference interval"
            )

        sequence_contig = self.resolve_contig(contig)

        url = (
            f"{self.endpoint}/sequence/region/human/"
            f"{sequence_contig}:{start1}..{end1}:1"
        )

        request = Request(
            url,
            headers={
                "Accept": "text/plain",
                "User-Agent": "SIRALOOM/1.0",
            },
        )

        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                data = response.read().decode("utf-8").strip()

        except HTTPError as exc:
            raise ReferenceError(
                f"Ensembl reference request failed with HTTP "
                f"{exc.code}: {url}"
            ) from exc

        except URLError as exc:
            raise ReferenceError(
                f"Unable to reach Ensembl reference service: {exc}"
            ) from exc

        except TimeoutError as exc:
            raise ReferenceError(
                "Ensembl reference request timed out"
            ) from exc

        sequence = "".join(data.split()).upper()

        if not sequence:
            raise ReferenceError(
                f"Ensembl returned an empty sequence for {url}"
            )

        valid = set("ACGTN")

        if any(base not in valid for base in sequence):
            raise ReferenceError(
                "Ensembl returned unexpected reference sequence characters"
            )

        expected_length = end1 - start1 + 1

        if len(sequence) != expected_length:
            raise ReferenceError(
                f"Ensembl returned {len(sequence)} bases, "
                f"expected {expected_length}"
            )

        return sequence

    def _get_window(
        self,
        contig: str,
        start0: int,
        end0: int,
    ) -> tuple[int, str]:
        if start0 < 0 or end0 < start0:
            raise ReferenceError(
                "Invalid zero-based reference interval"
            )

        if start0 == end0:
            return start0, ""

        window_start0 = max(
            0,
            start0 - self.window_flank,
        )

        window_end0 = end0 + self.window_flank

        contig_name = self.resolve_contig(contig)

        cache_key = (
            contig_name,
            window_start0,
            window_end0,
        )

        cached = self._cache.get(cache_key)

        if cached is not None:
            return window_start0, cached

        sequence = self._fetch_remote(
            contig_name,
            window_start0 + 1,
            window_end0,
        )

        self._cache[cache_key] = sequence

        return window_start0, sequence

    def fetch(
        self,
        contig: str,
        start0: int,
        end0: int,
    ) -> str:
        if start0 < 0 or end0 < start0:
            raise ReferenceError(
                "Invalid zero-based reference interval"
            )

        if start0 == end0:
            return ""

        window_start0, sequence = self._get_window(
            contig,
            start0,
            end0,
        )

        relative_start = start0 - window_start0
        relative_end = end0 - window_start0

        if relative_start < 0 or relative_end > len(sequence):
            raise ReferenceError(
                "Remote reference cache window does not cover requested interval"
            )

        return sequence[
            relative_start:relative_end
        ]

    def base(
        self,
        contig: str,
        pos1: int,
    ) -> str:
        if pos1 <= 0:
            raise ReferenceError(
                "Reference coordinates are 1-based and must be positive"
            )

        return self.fetch(
            contig,
            pos1 - 1,
            pos1,
        )

    def contig_length(self, contig: str) -> int:
        # Ensembl's sequence endpoint can return a chromosome segment, but
        # SIRALOOM does not need the complete chromosome length for the
        # normalization operations currently performed.
        raise ReferenceError(
            "Remote Ensembl reference does not provide contig length "
            "through the local-reference interface"
        )


ReferenceProvider = FastaReference | EnsemblReference
