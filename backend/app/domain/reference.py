from __future__ import annotations
import json
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

class ReferenceError(ValueError):
    """Base class for every reference-lookup failure (local FASTA or remote).

    `code` is a short, stable machine-checkable category -- callers (the workflow layer)
    use it to choose an error_code for the step instead of lumping every failure under
    one generic "NORMALIZATION_FAILED", and it's what makes a timeout, a rate limit, a
    genuinely invalid region, and an unreachable service distinguishable in the audit log
    without parsing the free-text message.
    """
    def __init__(self, message: str, *, code: str = "REFERENCE_ERROR"):
        super().__init__(message)
        self.code = code

# Categories specific to the remote (Ensembl) provider. Each is still a ReferenceError,
# so every existing `except ReferenceError` / `except (NormalizationError, ReferenceError)`
# call site keeps working unchanged -- these just carry a more specific `.code`.
class EnsemblTimeoutError(ReferenceError):
    def __init__(self, message: str):
        super().__init__(message, code="ENSEMBL_TIMEOUT")

class EnsemblRateLimitedError(ReferenceError):
    def __init__(self, message: str):
        super().__init__(message, code="ENSEMBL_RATE_LIMITED")

class EnsemblServerError(ReferenceError):
    def __init__(self, message: str):
        super().__init__(message, code="ENSEMBL_SERVER_ERROR")

class EnsemblInvalidRegionError(ReferenceError):
    def __init__(self, message: str):
        super().__init__(message, code="ENSEMBL_INVALID_REGION")

class EnsemblUnavailableError(ReferenceError):
    def __init__(self, message: str):
        super().__init__(message, code="ENSEMBL_UNAVAILABLE")

@dataclass(frozen=True)
class FaiEntry:
    name: str
    length: int
    offset: int
    line_bases: int
    line_width: int

class FastaReference:
    """Random-access FASTA reader backed by a .fai index."""
    def __init__(self, fasta_path: str | Path, fai_path: str | Path | None = None):
        self.fasta_path = Path(fasta_path)
        self.fai_path = Path(fai_path) if fai_path else Path(f"{self.fasta_path}.fai")
        if not self.fasta_path.exists():
            raise ReferenceError(f"Reference FASTA not found: {self.fasta_path}")
        if not self.fai_path.exists():
            raise ReferenceError(f"Reference FASTA index (.fai) not found: {self.fai_path}. Run a validated faidx process before use.")
        self._entries = self._load_fai()
        self._handle = self.fasta_path.open("rb")

    def close(self) -> None:
        if not self._handle.closed:
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
                entry = FaiEntry(name=name, length=int(length), offset=int(offset), line_bases=int(line_bases), line_width=int(line_width))
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
            raise ReferenceError(f"Reference interval exceeds {name}: {start0}-{end0}, length={entry.length}")
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
        return out.decode("ascii").upper()

    def base(self, contig: str, pos1: int) -> str:
        if pos1 <= 0:
            raise ReferenceError("Reference coordinates are 1-based and must be positive")
        return self.fetch(contig, pos1 - 1, pos1)

    def contig_length(self, contig: str) -> int:
        return self._entries[self.resolve_contig(contig)].length

class EnsemblReference:
    """Reference sequence provider backed by the Ensembl REST API.

    Usage for a bulk job (many variants), matching the intended flow:

        with EnsemblReference("GRCh38") as reference:
            reference.preflight()                    # fail fast if unreachable
            reference.prefetch(scan_regions(vcf))     # batched POST, ~N/50 requests
            normalize_vcf_file(..., reference=reference)  # now mostly cache hits

    `fetch`/`base` still work standalone (they fall back to a single live GET for
    anything not already cached), so this remains a correct drop-in for FastaReference
    even without calling prefetch() first -- prefetch is a performance optimization,
    not a correctness requirement.
    """
    #: Ensembl's own stated batch ceiling for the sequence/region POST endpoint is much
    #: higher, but the endpoint's own documented guidance for *sequence* lookups (as
    #: opposed to ID/variant lookups) is to keep batches modest for reasonable response
    #: times; 50 matches that guidance.
    DEFAULT_BATCH_SIZE = 50

    def __init__(
        self,
        genome_build: str,
        *,
        endpoint: str | None = None,
        grch38_endpoint: str = "https://rest.ensembl.org",
        grch37_endpoint: str = "https://grch37.rest.ensembl.org",
        timeout_seconds: float = 10.0,
        window_flank: int = 1000,
        retry_attempts: int = 3,
        retry_backoff_seconds: float = 1.5,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ):
        build = genome_build.strip()
        if build not in {"GRCh37", "GRCh38"}:
            raise ReferenceError(f"Unsupported remote reference build: {genome_build}", code="ENSEMBL_INVALID_REGION")
        self.genome_build = build
        self.endpoint = (endpoint if endpoint else (grch38_endpoint if build == "GRCh38" else grch37_endpoint)).rstrip("/")
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.window_flank = max(0, int(window_flank))
        self.retry_attempts = max(1, int(retry_attempts))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self.batch_size = max(1, min(int(batch_size), 50))
        self._cache: dict[tuple[str, int, int], str] = {}
        self.stats = {"single_requests": 0, "batch_requests": 0, "cache_hits": 0, "prefetched_windows": 0}

    def close(self) -> None:
        self._cache.clear()

    def __enter__(self) -> "EnsemblReference":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @staticmethod
    def _aliases(contig: str) -> list[str]:
        c = contig.strip()
        if not c:
            raise ReferenceError("Reference contig cannot be empty", code="ENSEMBL_INVALID_REGION")
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
        aliases = self._aliases(contig)
        for candidate in aliases:
            if not candidate.startswith("chr"):
                return candidate
        return aliases[0]

    # -- low-level HTTP: shared retry/backoff/error-classification for GET and POST -----

    def _request(self, request: Request) -> bytes:
        """Issues `request` with retry-with-backoff, raising a categorized
        ReferenceError subclass if every attempt fails. Shared by the single-region GET
        path and the batched POST path so both get identical retry/timeout/rate-limit
        behavior."""
        last_error: ReferenceError | None = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    return response.read()
            except HTTPError as exc:
                body_snippet = ""
                try:
                    body_snippet = exc.read(300).decode("utf-8", errors="replace")
                except Exception:
                    pass
                if exc.code == 429:
                    last_error = EnsemblRateLimitedError(f"Ensembl rate-limited the request (HTTP 429): {request.full_url}")
                    retryable = True
                elif 500 <= exc.code <= 599:
                    last_error = EnsemblServerError(f"Ensembl returned a server error (HTTP {exc.code}): {request.full_url} {body_snippet}".strip())
                    retryable = True
                else:
                    # 400/404/etc.: the region or request itself is invalid. Retrying an
                    # identical request will never succeed, so fail immediately.
                    raise EnsemblInvalidRegionError(f"Ensembl rejected the request (HTTP {exc.code}): {request.full_url} {body_snippet}".strip()) from exc
                if not retryable or attempt == self.retry_attempts:
                    raise last_error from exc
            except (URLError, TimeoutError) as exc:
                is_timeout = isinstance(exc, TimeoutError) or "timed out" in str(exc).lower()
                if is_timeout:
                    last_error = EnsemblTimeoutError(f"Ensembl reference request timed out after {self.timeout_seconds}s: {request.full_url}")
                else:
                    last_error = EnsemblUnavailableError(f"Unable to reach Ensembl reference service ({exc}): {request.full_url}")
                if attempt == self.retry_attempts:
                    raise last_error from exc
            if attempt < self.retry_attempts:
                time.sleep(self.retry_backoff_seconds * attempt)
        raise last_error or EnsemblUnavailableError(f"Ensembl reference request failed: {request.full_url}")

    def preflight(self) -> None:
        """Cheap reachability check (a single 1-base lookup) to run before committing to
        a potentially long batch job. Raises a categorized ReferenceError immediately if
        Ensembl is unreachable, instead of discovering that partway through a 1000-variant
        normalization run."""
        probe_contig = "21" if self.genome_build == "GRCh38" else "21"
        self._fetch_remote(probe_contig, 1, 1)
        self.stats["single_requests"] -= 1  # the probe isn't part of real work; don't count it

    # -- single-region GET: used by preflight() and as a self-healing fallback for any
    #    position `fetch()` needs that wasn't covered by an earlier prefetch() window ----

    def _fetch_remote(self, contig: str, start1: int, end1: int) -> str:
        if start1 < 1 or end1 < start1:
            raise ReferenceError("Invalid 1-based Ensembl reference interval", code="ENSEMBL_INVALID_REGION")
        sequence_contig = self.resolve_contig(contig)
        url = f"{self.endpoint}/sequence/region/human/{sequence_contig}:{start1}..{end1}:1"
        request = Request(url, headers={"Accept": "text/plain", "User-Agent": "SIRALOOM/1.0"})
        raw = self._request(request)
        self.stats["single_requests"] += 1
        sequence = "".join(raw.decode("utf-8").split()).upper()
        self._validate_sequence(sequence, expected_length=end1 - start1 + 1, url=url)
        return sequence

    @staticmethod
    def _validate_sequence(sequence: str, *, expected_length: int, url: str) -> None:
        if not sequence:
            raise EnsemblUnavailableError(f"Ensembl returned an empty sequence for {url}")
        if any(base not in "ACGTN" for base in sequence):
            raise EnsemblUnavailableError(f"Ensembl returned unexpected reference sequence characters for {url}")
        if len(sequence) != expected_length:
            raise EnsemblUnavailableError(f"Ensembl returned {len(sequence)} bases, expected {expected_length}, for {url}")

    # -- batched POST: the bulk-normalization path -------------------------------------

    def _fetch_remote_batch(self, regions: list[tuple[str, int, int]]) -> dict[tuple[str, int, int], str]:
        """regions: list of (contig_name_already_resolved, start1, end1). Returns a dict
        keyed by the same tuples. Issues one POST per up-to-`batch_size` regions."""
        results: dict[tuple[str, int, int], str] = {}
        for i in range(0, len(regions), self.batch_size):
            chunk = regions[i:i + self.batch_size]
            region_strings = [f"{contig}:{start1}..{end1}:1" for contig, start1, end1 in chunk]
            url = f"{self.endpoint}/sequence/region/human"
            body = json.dumps({"regions": region_strings}).encode("utf-8")
            request = Request(
                url, data=body, method="POST",
                headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "SIRALOOM/1.0"},
            )
            raw = self._request(request)
            self.stats["batch_requests"] += 1
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise EnsemblUnavailableError(f"Ensembl returned a non-JSON batch response for {url}") from exc
            if not isinstance(payload, list) or len(payload) != len(chunk):
                raise EnsemblUnavailableError(
                    f"Ensembl batch response shape mismatch: expected {len(chunk)} entries, got "
                    f"{len(payload) if isinstance(payload, list) else type(payload).__name__} for {url}"
                )
            for (contig, start1, end1), item in zip(chunk, payload):
                if not isinstance(item, dict) or "error" in item:
                    reason = item.get("error") if isinstance(item, dict) else "malformed batch entry"
                    raise EnsemblInvalidRegionError(f"Ensembl rejected region {contig}:{start1}..{end1}: {reason}")
                sequence = "".join(str(item.get("seq", "")).split()).upper()
                self._validate_sequence(sequence, expected_length=end1 - start1 + 1, url=f"{url} ({contig}:{start1}..{end1})")
                results[(contig, start1, end1)] = sequence
        return results

    def prefetch(self, windows) -> None:
        """windows: iterable of (contig, start0, end0) zero-based intervals the caller
        expects to need (typically one per VCF record, from a cheap pre-scan). Expands
        each to its padded window, deduplicates, and fills the cache via batched POST
        requests -- so the subsequent normalization pass hits cache almost every time
        instead of making one live HTTP round-trip per variant.
        """
        pending: dict[tuple[str, int, int], None] = {}
        for contig, start0, end0 in windows:
            if start0 == end0:
                continue
            contig_name = self.resolve_contig(contig)
            window_start0 = max(0, start0 - self.window_flank)
            window_end0 = end0 + self.window_flank
            cache_key = (contig_name, window_start0, window_end0)
            if cache_key not in self._cache:
                pending[cache_key] = None
        if not pending:
            return
        regions = [(contig, start0 + 1, end0) for (contig, start0, end0) in pending.keys()]
        fetched = self._fetch_remote_batch(regions)
        for (contig, start0, end0) in pending.keys():
            sequence = fetched.get((contig, start0 + 1, end0))
            if sequence is not None:
                self._cache[(contig, start0, end0)] = sequence
                self.stats["prefetched_windows"] += 1

    def _get_window(self, contig: str, start0: int, end0: int) -> tuple[int, str]:
        if start0 < 0 or end0 < start0:
            raise ReferenceError("Invalid zero-based reference interval", code="ENSEMBL_INVALID_REGION")
        if start0 == end0:
            return start0, ""
        window_start0 = max(0, start0 - self.window_flank)
        window_end0 = end0 + self.window_flank
        contig_name = self.resolve_contig(contig)
        cache_key = (contig_name, window_start0, window_end0)
        cached = self._cache.get(cache_key)
        if cached is not None:
            self.stats["cache_hits"] += 1
            return window_start0, cached
        # Self-healing fallback: not everything is guaranteed to be covered by an earlier
        # prefetch() (e.g. a left-shift walked further than window_flank in a long repeat
        # region). A single live GET here is slower but keeps `fetch()` always correct.
        sequence = self._fetch_remote(contig_name, window_start0 + 1, window_end0)
        self._cache[cache_key] = sequence
        return window_start0, sequence

    def fetch(self, contig: str, start0: int, end0: int) -> str:
        if start0 < 0 or end0 < start0:
            raise ReferenceError("Invalid zero-based reference interval", code="ENSEMBL_INVALID_REGION")
        if start0 == end0:
            return ""
        window_start0, sequence = self._get_window(contig, start0, end0)
        relative_start = start0 - window_start0
        relative_end = end0 - window_start0
        if relative_start < 0 or relative_end > len(sequence):
            raise ReferenceError("Remote reference cache window does not cover requested interval", code="ENSEMBL_INVALID_REGION")
        return sequence[relative_start:relative_end]

    def base(self, contig: str, pos1: int) -> str:
        if pos1 <= 0:
            raise ReferenceError("Reference coordinates are 1-based and must be positive", code="ENSEMBL_INVALID_REGION")
        return self.fetch(contig, pos1 - 1, pos1)

    def contig_length(self, contig: str) -> int:
        raise ReferenceError(
            "Remote Ensembl reference does not provide contig length through the local-reference interface",
            code="ENSEMBL_UNAVAILABLE",
        )

ReferenceProvider = FastaReference | EnsemblReference
