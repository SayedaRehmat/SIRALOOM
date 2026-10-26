from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from backend.app.domain.provider_contract import (
    ProviderEvidenceResult,
    ProviderNormalizedResult,
    ProviderRawResult,
    ProviderRequest,
    ScientificResourceProvider,
)
from backend.app.domain.resource_capabilities import ResourceCapability
from backend.app.domain.resource_source_contract import ResourceExecutionContract
from backend.app.domain.schemas import CanonicalVariant


class VEPProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class VEPProvider(ScientificResourceProvider):
    """Laboratory VEP execution provider.

    The execution contract supplies the qualified VEP binary/cache location.
    SIRALOOM never downloads a cache or silently substitutes a VEP version.

    VEP is run in local/offline cache mode for laboratory execution. Ensembl
    documents --offline + --cache as the appropriate no-network mode and
    recommends matching cache and VEP versions.
    """

    provider_id = "VEP"
    provider_version = "CLI"
    capabilities = frozenset({ResourceCapability.ANNOTATION})
    supported_builds = frozenset({"GRCh37", "GRCh38"})

    def __init__(self, contract: ResourceExecutionContract):
        self.contract = contract
        toolchain = dict(contract.toolchain or {})
        self.binary = str(toolchain.get("vep_binary") or contract.location or "vep")
        self.cache_dir = str(toolchain.get("cache_dir") or "").strip()
        self.fasta = str(toolchain.get("fasta") or "").strip()
        self.species = str(toolchain.get("species") or "homo_sapiens")
        self.cache_version = str(toolchain.get("cache_version") or "").strip()
        self.assembly = str(toolchain.get("assembly") or "").strip()
        self.cache_manifest = str(toolchain.get("cache_manifest") or "").strip()
        self.cache_manifest_sha256 = str(toolchain.get("cache_manifest_sha256") or "").strip().lower()
        self.cache_artifact_sha256 = str(toolchain.get("cache_artifact_sha256") or "").strip().lower()
        self.expected_binary_sha256 = str(toolchain.get("vep_binary_sha256") or "").strip().lower()
        self.extra_args = [str(x) for x in (toolchain.get("extra_args") or [])]
        self._runtime_checks: dict[str, dict[str, Any]] = {}
        self._validate_toolchain()

    @classmethod
    def from_execution_contract(cls, contract: ResourceExecutionContract) -> "VEPProvider":
        if contract.provider_id != cls.provider_id:
            raise VEPProviderError(
                f"Execution provider {contract.provider_id!r} does not match VEP."
            )
        if contract.access_method.upper() not in {"LOCAL", "FILE", "LOCAL_ONLY"}:
            raise VEPProviderError(
                f"VEP laboratory execution requires LOCAL/FILE/LOCAL_ONLY access, got {contract.access_method!r}."
            )
        return cls(contract)

    def _validate_toolchain(self) -> None:
        if not self.cache_dir:
            raise VEPProviderError("VEP execution contract must declare cache_dir.")
        if not self.cache_version:
            raise VEPProviderError(
                "VEP execution contract must declare cache_version so the tool/cache pairing is explicit."
            )
        if not Path(self.binary).is_absolute():
            raise VEPProviderError("VEP execution contract must declare an absolute vep_binary path.")
        if not Path(self.cache_dir).is_absolute():
            raise VEPProviderError("VEP execution contract must declare an absolute cache_dir path.")
        if _canonical_assembly(self.assembly) is None:
            raise VEPProviderError("VEP execution contract must pin assembly to GRCh37 or GRCh38.")
        if not Path(self.cache_manifest).is_absolute():
            raise VEPProviderError("VEP execution contract must declare an absolute cache_manifest path.")
        for name, digest in (
            ("cache_manifest_sha256", self.cache_manifest_sha256),
            ("cache_artifact_sha256", self.cache_artifact_sha256),
            ("vep_binary_sha256", self.expected_binary_sha256),
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise VEPProviderError(f"VEP execution contract must pin {name} as a SHA-256 digest.")
        if self.extra_args:
            forbidden = {
                "--input_file", "-i", "--output_file", "-o", "--cache_version",
                "--dir_cache", "--cache", "--offline", "--species", "--assembly", "--fasta",
                "--help", "-h", "--version", "--show_cache_info", "--config", "--plugin", "--custom",
                "--refseq", "--merged", "--everything", "--canonical", "--mane",
            }
            if any(arg.split("=", 1)[0] in forbidden for arg in self.extra_args):
                raise VEPProviderError(
                    "VEP extra_args may not override governed input/output/cache arguments."
                )

    def validate_execution_contract(self, contract: ResourceExecutionContract) -> None:
        if contract.provider_id != self.provider_id:
            raise VEPProviderError("VEP provider identity mismatch.")
        if contract.access_method.upper() not in {"LOCAL", "FILE", "LOCAL_ONLY"}:
            raise VEPProviderError("VEP requires local execution.")
        if not contract.toolchain:
            raise VEPProviderError("VEP toolchain is missing from the governed execution contract.")

    def prepare_request(self, operation: str, inputs: dict[str, Any]) -> ProviderRequest:
        if operation != "annotate":
            raise VEPProviderError(f"Unsupported VEP operation: {operation}")
        variants = inputs.get("variants")
        if not isinstance(variants, list) or not variants:
            raise VEPProviderError("VEP annotate requires a non-empty variants list.")
        return ProviderRequest(
            operation="annotate",
            payload={"variants": variants, "genome_build": inputs.get("genome_build")},
            metadata={"provider": self.provider_id, "provider_version": self.contract.provider_version},
        )

    def execute(self, request: ProviderRequest) -> ProviderRawResult:
        variants = request.payload["variants"]
        build = _canonical_assembly(request.payload.get("genome_build") or self.assembly)
        if not build:
            raise VEPProviderError("VEP execution requires an explicit GRCh37/GRCh38 assembly.")
        with tempfile.TemporaryDirectory(prefix="siraloom-vep-") as tmp:
            input_vcf = Path(tmp) / "input.vcf"
            output_json = Path(tmp) / "output.json"
            lines = [
                "##fileformat=VCFv4.2",
                f"##reference={build}",
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
            ]
            for index, variant in enumerate(variants):
                lines.append(
                    f"{variant.chromosome}\t{variant.position}\tSIRALOOM_{index}\t"
                    f"{variant.reference}\t{variant.alternate}\t.\tPASS\t."
                )
            input_vcf.write_text("\n".join(lines) + "\n", encoding="utf-8")

            cmd = [
                self.binary,
                "--offline",
                "--cache",
                "--format", "vcf",
                "--json",
                "--force_overwrite",
                "--species", self.species,
                "--cache_version", self.cache_version,
                "--dir_cache", self.cache_dir,
                "--input_file", str(input_vcf),
                "--output_file", str(output_json),
            ]
            cmd.extend(["--assembly", build])
            if self.fasta:
                cmd.extend(["--fasta", self.fasta])
            cmd.extend(self.extra_args)

            try:
                # Start VEP in its own process group so a timeout can terminate
                # the entire local toolchain, not merely the immediate process.
                # This prevents an expired workflow lease from leaving a child VEP
                # process running indefinitely after SIRALOOM has abandoned it.
                completed = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                )
                try:
                    stdout, stderr = completed.communicate(timeout=300)
                except subprocess.TimeoutExpired as exc:
                    try:
                        os.killpg(completed.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    completed.wait()
                    raise VEPProviderError("VEP execution timed out and its process group was terminated.", retryable=True) from exc
            except FileNotFoundError as exc:
                raise VEPProviderError(
                    f"VEP executable was not found: {self.binary}",
                    retryable=False,
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise VEPProviderError("VEP execution timed out.", retryable=True) from exc

            if completed.returncode != 0:
                message = (stderr or stdout or "VEP failed").strip()[-4000:]
                raise VEPProviderError(
                    f"VEP exited with code {completed.returncode}: {message}",
                    retryable=completed.returncode in {137, 143},
                )

            if not output_json.exists():
                raise VEPProviderError("VEP completed without producing its governed JSON output.")

            raw_text = output_json.read_text(encoding="utf-8")
            response_sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
            records: list[dict[str, Any]] = []
            for line in raw_text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise VEPProviderError("VEP returned a non-JSON record in JSON mode.") from exc

            return ProviderRawResult(
                operation="annotate",
                payload=records,
                response_sha256=response_sha256,
                metadata={
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "command_provider": self.provider_id,
                    "assembly": build,
                    "cache_version": self.cache_version,
                },
            )

    def validate_response(self, result: ProviderRawResult) -> None:
        if not isinstance(result.payload, list):
            raise VEPProviderError("VEP JSON response must be a list of records.")
        for record in result.payload:
            if not isinstance(record, dict):
                raise VEPProviderError("VEP JSON response contains a non-object record.")
            transcript_consequences = record.get("transcript_consequences")
            if transcript_consequences is not None and (
                not isinstance(transcript_consequences, list)
                or any(not isinstance(item, dict) for item in transcript_consequences)
            ):
                raise VEPProviderError(
                    "VEP transcript_consequences must be a list of objects when present."
                )

    def normalize_result(
        self,
        result: ProviderRawResult,
        *,
        inputs: dict[str, Any],
    ) -> ProviderNormalizedResult:
        self.validate_response(result)
        variants = inputs["variants"]
        normalized: list[dict[str, Any]] = []
        by_key = {
            f"{v.chromosome}:{v.position}:{v.reference}:{v.alternate}": v
            for v in variants
        }
        for record in result.payload:
            start = record.get("start")
            seq_region = record.get("seq_region_name")
            allele_string = str(record.get("allele_string") or "")
            ref = allele_string.split("/", 1)[0] if "/" in allele_string else None
            alt = allele_string.split("/", 1)[1] if "/" in allele_string else None
            key = f"{seq_region}:{start}:{ref}:{alt}" if ref and alt else None
            original = by_key.get(key) if key else None
            if original is None:
                continue

            transcripts = record.get("transcript_consequences") or []
            selected, selection_status = self._select_display_transcript(transcripts)
            normalized.append({
                "chr": original.chromosome,
                "pos": original.position,
                "ref": original.reference,
                "alt": original.alternate,
                "genome": original.genome_build,
                "gene_symbol": selected.get("gene_symbol") or selected.get("symbol"),
                "gene": selected.get("gene_id"),
                "transcript": selected.get("transcript_id"),
                "effect": ",".join(selected.get("consequence_terms") or []),
                "consequences": transcripts,
                "hgvsc": selected.get("hgvsc"),
                "hgvsp": selected.get("hgvsp"),
                "canonical": bool(selected.get("canonical")),
                "mane_select": selected.get("mane_select"),
                "transcript_selection": {
                    "status": selection_status,
                    "policy": "UNIQUE_MANE_SELECT_THEN_UNIQUE_CANONICAL",
                    "selected_transcript_id": selected.get("transcript_id"),
                },
                "_siraloom_annotation_provenance": {
                    "provider": self.provider_id,
                    "provider_version": self.contract.provider_version,
                    "observed_at": result.metadata.get("observed_at"),
                    "response_sha256": result.response_sha256,
                    "assembly": inputs.get("genome_build"),
                    "cache_version": self.cache_version,
                    "runtime_check": result.metadata.get("runtime_check"),
                },
            })

        expected = {
            f"{v.chromosome}:{v.position}:{v.reference}:{v.alternate}"
            for v in variants
        }
        observed = {
            f"{r['chr']}:{r['pos']}:{r['ref']}:{r['alt']}"
            for r in normalized
        }
        if observed != expected:
            raise VEPProviderError(
                f"VEP result set does not match the requested batch; "
                f"missing={len(expected - observed)}, extra={len(observed - expected)}"
            )
        return ProviderNormalizedResult("annotate", tuple(normalized), result.metadata)

    @staticmethod
    def _select_display_transcript(transcripts: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
        mane_select = [item for item in transcripts if item.get("mane_select")]
        if len(mane_select) == 1:
            return mane_select[0], "SELECTED_MANE_SELECT"
        if len(mane_select) > 1:
            return {}, "AMBIGUOUS_MANE_SELECT"

        canonical = [item for item in transcripts if item.get("canonical")]
        if len(canonical) == 1:
            return canonical[0], "SELECTED_CANONICAL"
        if len(canonical) > 1:
            return {}, "AMBIGUOUS_CANONICAL"
        return {}, "NO_PREFERRED_TRANSCRIPT"

    def to_evidence(
        self,
        normalized: ProviderNormalizedResult,
        *,
        inputs: dict[str, Any],
    ) -> ProviderEvidenceResult:
        return ProviderEvidenceResult(
            evidence=tuple({
                "type": "CONSEQUENCE",
                "observation": item,
                "source": self.provider_id,
                "source_version": self.contract.provider_version,
            } for item in normalized.observations),
        )

    def annotate(self, variants: list[CanonicalVariant], context: dict[str, Any]) -> list[dict[str, Any]]:
        genome_build = _canonical_assembly(context.get("genome_build") or context.get("genome"))
        if not genome_build:
            raise VEPProviderError("VEP annotation requires an explicit GRCh37/GRCh38 assembly.")
        runtime_check = self.verify_local_runtime(genome_build)
        request = self.prepare_request(
            "annotate",
            {"variants": variants, "genome_build": context.get("genome_build") or context.get("genome")},
        )
        raw = self.execute(request)
        raw.metadata["runtime_check"] = runtime_check
        normalized = self.normalize_result(raw, inputs=request.payload)
        return list(normalized.observations)

    def verify_local_runtime(self, genome_build: str | None) -> dict[str, Any]:
        """Verify the configured VEP binary and cache before scientific execution.

        This check is intentionally performed by the real annotation entry point,
        not inferred from a registered path or a resource's declared version.
        """
        assembly = _canonical_assembly(genome_build or self.assembly)
        if not assembly:
            raise VEPProviderError("VEP runtime verification requires an explicit GRCh37/GRCh38 assembly.")
        if assembly not in self.supported_builds:
            raise VEPProviderError(f"VEP does not support assembly {assembly!r}.")
        configured_assembly = _canonical_assembly(self.assembly)
        if configured_assembly and configured_assembly != assembly:
            raise VEPProviderError(
                f"VEP resource assembly {configured_assembly} does not match analysis assembly {assembly}."
            )
        if assembly in self._runtime_checks:
            return dict(self._runtime_checks[assembly])

        cache_manifest_check = self._verify_cache_manifest(assembly)
        try:
            binary_sha256_before = _sha256_file(Path(self.binary))
        except OSError as exc:
            raise VEPProviderError(f"VEP executable is unavailable for checksum verification: {self.binary}") from exc
        if binary_sha256_before != self.expected_binary_sha256:
            raise VEPProviderError("VEP binary SHA-256 does not match the governed execution contract.")

        try:
            version_result = subprocess.run(
                [self.binary, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            raise VEPProviderError("VEP version check timed out.", retryable=True) from exc
        except OSError as exc:
            raise VEPProviderError(f"VEP executable is unavailable: {self.binary}") from exc
        if version_result.returncode != 0:
            raise VEPProviderError(
                "VEP version check failed: "
                + (version_result.stderr or version_result.stdout or "no diagnostic").strip()[-2000:]
            )
        version_output = "\n".join((version_result.stdout or "", version_result.stderr or "")).strip()
        actual_version = _extract_vep_version(version_output)
        expected_version = str(
            (self.contract.toolchain or {}).get("vep_version")
            or self.contract.provider_version
        ).strip()
        expected_release = _version_release(expected_version)
        if expected_release is None:
            raise VEPProviderError(
                "VEP execution contract must pin a parseable tool version in provider_version or toolchain.vep_version."
            )
        if actual_version is None:
            raise VEPProviderError("VEP --version returned output without a parseable release version.")
        expected_full_version = _extract_vep_version(expected_version)
        version_matches = (
            actual_version == expected_full_version
            if expected_full_version and "." in expected_full_version
            else _version_release(actual_version) == expected_release
        )
        if not version_matches:
            raise VEPProviderError(
                f"VEP binary release {actual_version} does not match governed release {expected_version}."
            )

        cache_command = [
            self.binary,
            "--offline",
            "--cache",
            "--species",
            self.species,
            "--cache_version",
            self.cache_version,
            "--dir_cache",
            self.cache_dir,
            "--assembly",
            assembly,
            "--show_cache_info",
        ]
        try:
            cache_result = subprocess.run(
                cache_command,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            raise VEPProviderError(
                "VEP offline cache verification timed out.", retryable=True
            ) from exc
        except OSError as exc:
            raise VEPProviderError(f"VEP cache verification could not start: {self.binary}") from exc
        cache_output = "\n".join((cache_result.stdout or "", cache_result.stderr or "")).strip()
        if cache_result.returncode != 0 or not cache_output:
            raise VEPProviderError(
                "VEP could not load the governed cache offline: "
                + (cache_output or "no cache information was returned")[-2000:]
            )
        try:
            binary_sha256_after = _sha256_file(Path(self.binary))
        except OSError as exc:
            raise VEPProviderError("VEP binary could not be checksummed after runtime verification.") from exc
        if binary_sha256_after != binary_sha256_before:
            raise VEPProviderError("VEP executable changed during runtime verification.")

        runtime_check = {
            "status": "VERIFIED",
            "assembly": assembly,
            "vep_version": actual_version,
            "expected_vep_version": expected_version,
            "cache_version": self.cache_version,
            "vep_binary_sha256": binary_sha256_after,
            "cache_manifest_sha256": cache_manifest_check["manifest_sha256"],
            "cache_tree_sha256": cache_manifest_check["tree_sha256"],
            "cache_artifact_sha256": cache_manifest_check["source_artifact_sha256"],
            "cache_info_sha256": hashlib.sha256(cache_output.encode("utf-8")).hexdigest(),
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
        self._runtime_checks[assembly] = runtime_check
        return dict(runtime_check)

    def _verify_cache_manifest(self, assembly: str) -> dict[str, str]:
        manifest_path = Path(self.cache_manifest)
        cache_root = Path(self.cache_dir)
        if cache_root.is_symlink():
            raise VEPProviderError("VEP cache directory cannot be a symlink.")
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise VEPProviderError("VEP cache manifest is missing or is not a regular file.")
        try:
            resolved_root = cache_root.resolve(strict=True)
            resolved_manifest = manifest_path.resolve(strict=True)
        except OSError as exc:
            raise VEPProviderError("VEP cache or manifest path is unavailable.") from exc
        if not resolved_root.is_dir() or resolved_manifest.is_relative_to(resolved_root):
            raise VEPProviderError("VEP cache manifest must be a file outside the cache directory.")
        try:
            manifest_sha256 = _sha256_file(resolved_manifest)
            if manifest_sha256 != self.cache_manifest_sha256:
                raise VEPProviderError("VEP cache manifest SHA-256 does not match the governed contract.")
            document = json.loads(resolved_manifest.read_text(encoding="utf-8"))
        except VEPProviderError:
            raise
        except (OSError, UnicodeError, ValueError) as exc:
            raise VEPProviderError("VEP cache manifest is unreadable or invalid JSON.") from exc
        if not isinstance(document, dict) or document.get("schema") != "siraloom.vep-cache-manifest.v1":
            raise VEPProviderError("VEP cache manifest has an unsupported schema.")
        if str(document.get("cache_version") or "") != self.cache_version:
            raise VEPProviderError("VEP cache manifest release does not match the execution contract.")
        if str(document.get("species") or "") != self.species:
            raise VEPProviderError("VEP cache manifest species does not match the execution contract.")
        if _canonical_assembly(str(document.get("assembly") or "")) != assembly:
            raise VEPProviderError("VEP cache manifest assembly does not match the analysis assembly.")
        source_artifact_sha256 = str(document.get("source_artifact_sha256") or "").lower()
        if source_artifact_sha256 != self.cache_artifact_sha256:
            raise VEPProviderError("VEP cache manifest does not identify the governed cache artifact digest.")
        entries = document.get("files")
        if not isinstance(entries, list) or not entries:
            raise VEPProviderError("VEP cache manifest must list at least one cache file.")

        expected: dict[str, tuple[str, int]] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise VEPProviderError("VEP cache manifest file entries must be objects.")
            relative = str(entry.get("path") or "")
            parsed = PurePosixPath(relative)
            digest = str(entry.get("sha256") or "").lower()
            size = entry.get("size_bytes")
            if (
                not relative
                or parsed.is_absolute()
                or any(part in {"", ".", ".."} for part in parsed.parts)
                or parsed.as_posix() != relative
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size < 0
                or relative in expected
            ):
                raise VEPProviderError("VEP cache manifest contains an invalid or duplicate file entry.")
            expected[relative] = (digest, size)

        actual_paths: set[str] = set()
        actual_entries: list[dict[str, Any]] = []
        try:
            for path in resolved_root.rglob("*"):
                if path.is_symlink():
                    raise VEPProviderError("VEP cache contains a symlink, which is not permitted by its manifest.")
                mode = path.stat(follow_symlinks=False).st_mode
                if stat.S_ISDIR(mode):
                    continue
                if not stat.S_ISREG(mode):
                    raise VEPProviderError("VEP cache contains a non-regular filesystem entry.")
                relative = path.relative_to(resolved_root).as_posix()
                actual_paths.add(relative)
                if relative not in expected:
                    raise VEPProviderError(f"VEP cache contains an unlisted file: {relative}")
                digest = _sha256_file(path)
                size = path.stat().st_size
                actual_entries.append({"path": relative, "sha256": digest, "size_bytes": size})
                if expected.get(relative) != (digest, size):
                    raise VEPProviderError(f"VEP cache file does not match its manifest: {relative}")
        except VEPProviderError:
            raise
        except OSError as exc:
            raise VEPProviderError("VEP cache could not be read for manifest verification.") from exc
        if actual_paths != set(expected):
            raise VEPProviderError(
                "VEP cache file set does not match its manifest "
                f"(missing={len(set(expected) - actual_paths)}, extra={len(actual_paths - set(expected))})."
            )
        canonical = json.dumps(
            {
                "schema": "siraloom.vep-cache-manifest.v1",
                "cache_version": self.cache_version,
                "species": self.species,
                "assembly": assembly,
                "source_artifact_sha256": source_artifact_sha256,
                "files": sorted(actual_entries, key=lambda item: item["path"]),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return {
            "manifest_sha256": manifest_sha256,
            "tree_sha256": hashlib.sha256(canonical).hexdigest(),
            "source_artifact_sha256": source_artifact_sha256,
        }


def _canonical_assembly(value: str | None) -> str | None:
    normalized = str(value or "").strip().casefold()
    if normalized in {"grch37", "hg19"}:
        return "GRCh37"
    if normalized in {"grch38", "hg38"}:
        return "GRCh38"
    return None


def _extract_vep_version(value: str) -> str | None:
    match = re.search(
        r"(?:ensembl[- ]vep|\bvep)(?:\s+version)?\s*[/=:v-]?\s*(\d+(?:\.\d+)*)",
        value,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1)
    match = re.search(r"\b(\d+(?:\.\d+)*)\b", value)
    return match.group(1) if match else None


def _version_release(value: str) -> str | None:
    match = re.search(r"\d+", value)
    return match.group(0) if match else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
