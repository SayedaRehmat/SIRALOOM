from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
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
        self.extra_args = [str(x) for x in (toolchain.get("extra_args") or [])]
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
        if self.extra_args:
            forbidden = {"--input_file", "-i", "--output_file", "-o", "--cache_version", "--dir_cache"}
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
        build = str(request.payload.get("genome_build") or self.assembly or "GRCh38").upper()
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
            if self.assembly:
                cmd.extend(["--assembly", self.assembly])
            if self.fasta:
                cmd.extend(["--fasta", self.fasta])
            cmd.extend(self.extra_args)

            try:
                completed = subprocess.run(
                    cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            except FileNotFoundError as exc:
                raise VEPProviderError(
                    f"VEP executable was not found: {self.binary}",
                    retryable=False,
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise VEPProviderError("VEP execution timed out.", retryable=True) from exc

            if completed.returncode != 0:
                message = (completed.stderr or completed.stdout or "VEP failed").strip()[-4000:]
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
            selected = next(
                (
                    t for t in transcripts
                    if t.get("canonical") or t.get("mane_select")
                ),
                transcripts[0] if transcripts else {},
            )
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
                "_siraloom_annotation_provenance": {
                    "provider": self.provider_id,
                    "provider_version": self.contract.provider_version,
                    "observed_at": result.metadata.get("observed_at"),
                    "response_sha256": result.response_sha256,
                    "assembly": inputs.get("genome_build"),
                    "cache_version": self.cache_version,
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
        request = self.prepare_request(
            "annotate",
            {"variants": variants, "genome_build": context.get("genome_build") or context.get("genome")},
        )
        raw = self.execute(request)
        normalized = self.normalize_result(raw, inputs=request.payload)
        return list(normalized.observations)
