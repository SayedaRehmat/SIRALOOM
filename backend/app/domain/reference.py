```python
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
        for line_no, line in enumerate(
            self.fai_path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue

            fields = line.split("\t")
            if len(fields) < 5:
                raise ReferenceError(f"Malformed FASTA index at line {line_no}")

            try:
                name, length, offset, line_bases, line_width = fields[:5]
                entry = FaiEntry(
                    name,
                    int(length),
                    int(offset),
                    int(line_bases),
                    int(line_width),
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

        raise ReferenceError(f"Contig {contig!r} is not present in the reference")

    def fetch(self, contig: str, start0: int, end0: int) -> str:
        if start0 < 0 or end0 < start0:
            raise ReferenceError("Invalid zero-based reference interval")

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
            take = min(remaining, entry.line_bases - in_line)

            file_offset = (
                entry.offset
                + line_idx * entry.line_width
                + in_line
            )

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
            raise ReferenceError(
                "Reference coordinates are 1-based and must be positive"
            )

        return self.fetch(contig, pos1 - 1, pos1)

    def contig_length(self, contig: str) -> int:
        return self._entries[self.resolve_contig(contig)].length


class EnsemblReference:
    """Remote reference sequence provider backed by Ensembl REST.

    This provider is intended for development/integration environments where
    a local validated FASTA/FAI reference is not yet available.

    GRCh38 uses the current Ensembl REST service:
        https://rest.ensembl.org

    GRCh37 uses the dedicated Ensembl GRCh37 REST service:
        https://grch37.rest.ensembl.org

    The provider fetches a surrounding sequence window and caches it in
    memory so normalization does not issue one HTTP request for every base.

    Production clinical deployments should prefer a controlled, validated
    local/cloud FASTA/FAI resource rather than relying on a public REST
    service.
    """

    DEFAULT_ENDPOINTS = {
        "GRCh38": "https://rest.ensembl.org",
        "GRCh37": "https://grch37.rest.ensembl.org",
    }

    def __init__(
        self,
        genome_build: str,
        endpoint: str | None = None,
        timeout_seconds: float = 10.0,
        window_flank: int = 1000,
    ):
        normalized_build = self._normalize_build(genome_build)

        self.genome_build = normalized_build
        self.endpoint = (
            endpoint.rstrip("/")
            if endpoint
            else self.DEFAULT_ENDPOINTS[normalized_build]
        )
        self.timeout_seconds = timeout_seconds
        self.window_flank = max(0, int(window_flank))

        # Cache:
        # (resolved_contig, window_start0, window_end0) -> sequence
        self._cache: dict[tuple[str, int, int], str] = {}

    @staticmethod
    def _normalize_build(genome_build: str) -> str:
        normalized = genome_build.strip().upper().replace(".", "")

        aliases = {
            "GRCH37": "GRCh37",
            "HG19": "GRCh37",
            "GRCH38": "GRCh38",
            "HG38": "GRCh38",
        }

        try:
            return aliases[normalized]
        except KeyError as exc:
            raise ReferenceError(
                f"Unsupported remote reference build: {genome_build!r}. "
                "Supported builds are GRCh37 and GRCh38."
            ) from exc

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
            for candidate in ("MT", "M", "chrMT", "chrM"):
                if candidate not in aliases:
                    aliases.append(candidate)

        return aliases

    def resolve_contig(self, contig: str) -> str:
        """Return the Ensembl-compatible chromosome/contig name.

        Ensembl REST accepts standard human chromosome names such as 1..22,
        X, Y and MT. SIRALOOM commonly receives both chr1 and 1, so aliases
        are normalized before requests.
        """

        candidates = self._aliases(contig)

        for candidate in candidates:
            if candidate.startswith("chr"):
                continue
            return candidate

        raise ReferenceError(
            f"Unable to resolve reference contig: {contig!r}"
        )

    def _fetch_window(
        self,
        contig: str,
        start0: int,
        end0: int,
    ) -> str:
        if start0 < 0 or end0 < start0:
            raise ReferenceError("Invalid zero-based reference interval")

        if start0 == end0:
            return ""

        resolved = self.resolve_contig(contig)

        cache_key = (resolved, start0, end0)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Ensembl REST uses 1-based inclusive coordinates.
        start1 = start0 + 1
        end1 = end0

        url = (
            f"{self.endpoint}/sequence/region/human/"
            f"{resolved}:{start1}..{end1}:1"
        )

        request = Request(
            url,
            headers={
                "Accept": "text/plain",
                "User-Agent": "SIRALOOM/1.0",
            },
            method="GET",
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("ascii").strip()
        except HTTPError as exc:
            raise ReferenceError(
                f"Ensembl reference request failed with HTTP {exc.code}: "
                f"{resolved}:{start1}-{end1}"
            ) from exc
        except URLError as exc:
            raise ReferenceError(
                f"Unable to reach Ensembl reference service: {exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise ReferenceError(
                "Timed out while querying the Ensembl reference service"
            ) from exc
        except OSError as exc:
            raise ReferenceError(
                f"Unable to read Ensembl reference response: {exc}"
            ) from exc

        sequence = payload.upper()

        if not sequence:
            raise ReferenceError(
                f"Ensembl returned an empty reference sequence for "
                f"{resolved}:{start1}-{end1}"
            )

        expected_length = end0 - start0

        if len(sequence) != expected_length:
            raise ReferenceError(
                "Ensembl reference response length mismatch: "
                f"expected {expected_length}, received {len(sequence)}"
            )

        self._cache[cache_key] = sequence
        return sequence

    def fetch(self, contig: str, start0: int, end0: int) -> str:
        """Fetch a zero-based half-open reference interval."""

        if start0 < 0 or end0 < start0:
            raise ReferenceError("Invalid zero-based reference interval")

        if start0 == end0:
            return ""

        resolved = self.resolve_contig(contig)

        window_start = max(0, start0 - self.window_flank)
        window_end = end0 + self.window_flank

        sequence = self._fetch_window(
            resolved,
            window_start,
            window_end,
        )

        relative_start = start0 - window_start
        relative_end = relative_start + (end0 - start0)

        return sequence[relative_start:relative_end]

    def base(self, contig: str, pos1: int) -> str:
        """Return a single reference base using 1-based coordinates."""

        if pos1 <= 0:
            raise ReferenceError(
                "Reference coordinates are 1-based and must be positive"
            )

        return self.fetch(contig, pos1 - 1, pos1)

    def contig_length(self, contig: str) -> int:
        """Return chromosome length when available from Ensembl.

        This performs a lightweight Ensembl REST lookup. It is not cached
        because normalization normally needs sequence bases rather than
        chromosome lengths.
        """

        resolved = self.resolve_contig(contig)

        url = (
            f"{self.endpoint}/info/assembly/homo_sapiens/"
            f"{resolved}"
        )

        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "SIRALOOM/1.0",
            },
            method="GET",
        )

        try:
            import json

            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise ReferenceError(
                f"Ensembl assembly lookup failed with HTTP {exc.code}: "
                f"{resolved}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ReferenceError(
                f"Unable to query Ensembl assembly information: {exc}"
            ) from exc
        except ValueError as exc:
            raise ReferenceError(
                "Ensembl returned invalid assembly JSON"
            ) from exc

        length = payload.get("length")

        if not isinstance(length, int) or length <= 0:
            raise ReferenceError(
                f"Ensembl did not return a valid contig length for {resolved}"
            )

        return length
```
