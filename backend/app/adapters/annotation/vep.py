from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from backend.app.domain.resource_source_contract import ResourceExecutionContract
from backend.app.domain.schemas import CanonicalVariant


class VEPError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class VEPProvider:
    """Laboratory-local Ensembl VEP adapter using a governed offline cache."""

    provider_id = "VEP"
    provider_version = "112"
    supported_builds = {"GRCH37", "GRCH38"}

    def __init__(
        self,
        *,
        executable: str,
        cache_dir: str,
        provider_version: str,
        extra_args: tuple[str, ...] = (),
    ):
        self.executable = executable
        self.cache_dir = cache_dir
        self.provider_version = provider_version
        self.extra_args = extra_args

    @classmethod
    def from_execution_contract(cls, contract: ResourceExecutionContract) -> "VEPProvider":
        if contract.provider_id != cls.provider_id:
            raise VEPError(f"Execution provider {contract.provider_id!r} does not match VEP.")
        if not contract.provider_version:
            raise VEPError("VEP execution contract is missing provider_version.")
        if contract.access_method not in {"LOCAL", "FILE", "LOCAL_ONLY"}:
            raise VEPError(
                f"Laboratory VEP requires a local execution contract, got {contract.access_method!r}."
            )
        if not contract.location:
            raise VEPError("VEP execution contract does not contain the cache location.")

        toolchain = dict(contract.toolchain or {})
        executable = str(toolchain.get("executable") or "vep").strip()
        cache_dir = str(toolchain.get("cache_dir") or contract.location).strip()
        raw_extra_args = toolchain.get("extra_args") or ()
        if not isinstance(raw_extra_args, (list, tuple)) or not all(
            isinstance(item, str) and item.strip() for item in raw_extra_args
        ):
            raise VEPError("VEP execution contract toolchain.extra_args must be a list of strings.")
        return cls(
            executable=executable,
            cache_dir=cache_dir,
            provider_version=contract.provider_version,
            extra_args=tuple(raw_extra_args),
        )

    def capabilities(self) -> set[str]:
        return {"ANNOTATION"}

    def supports_build(self, genome_build: str) -> bool:
        return genome_build.upper() in self.supported_builds

    @staticmethod
    def _vcf_text(variants: list[CanonicalVariant]) -> str:
        lines = [
            "##fileformat=VCFv4.2",
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
        ]
        for variant in variants:
            lines.append(
                f"{variant.chromosome.removeprefix('chr')}\t{variant.position}\t.\t"
                f"{variant.reference}\t{variant.alternate}\t.\tPASS\t."
            )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _key(chromosome: str, position: int, reference: str, alternate: str) -> str:
        return "|".join(
            [str(chromosome).removeprefix("chr"), str(position), str(reference), str(alternate)]
        )

    def annotate(self, variants: list[CanonicalVariant], context: dict[str, Any]) -> list[dict]:
        if not variants:
            return []
        genome = str(context.get("genome") or "").strip().upper()
        build = {"HG38": "GRCh38", "HG19": "GRCh37", "GRCH38": "GRCh38", "GRCH37": "GRCh37"}.get(genome)
        if build is None:
            raise VEPError(f"VEP does not support analysis build {genome!r}.")

        with tempfile.TemporaryDirectory(prefix="siraloom-vep-") as tmp:
            root = Path(tmp)
            input_vcf = root / "input.vcf"
            output_json = root / "output.json"
            input_vcf.write_text(self._vcf_text(variants), encoding="utf-8")
            command = [
                self.executable, "--input_file", str(input_vcf),
                "--output_file", str(output_json), "--format", "vcf",
                "--json", "--cache", "--offline", "--dir_cache", self.cache_dir,
                "--assembly", build, "--force_overwrite", *self.extra_args,
            ]
            request_fingerprint = hashlib.sha256(
                json.dumps(
                    {"provider": self.provider_id, "version": self.provider_version,
                     "command": command, "genome": build},
                    sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            try:
                completed = subprocess.run(
                    command, check=False, capture_output=True, text=True,
                    timeout=int(context.get("timeout_seconds") or 3600),
                )
            except FileNotFoundError as exc:
                raise VEPError(f"VEP executable {self.executable!r} was not found.") from exc
            except subprocess.TimeoutExpired as exc:
                raise VEPError("VEP execution timed out.", retryable=True) from exc
            except OSError as exc:
                raise VEPError(f"VEP execution failed to start: {exc}", retryable=True) from exc
            if completed.returncode != 0:
                raise VEPError(
                    f"VEP exited with code {completed.returncode}: {(completed.stderr or '').strip()[-2000:]}"
                )
            if not output_json.is_file():
                raise VEPError("VEP completed without producing JSON output.")
            response_bytes = output_json.read_bytes()
            response_sha256 = hashlib.sha256(response_bytes).hexdigest()
            try:
                records = [
                    json.loads(line)
                    for line in response_bytes.decode("utf-8").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")
                ]
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise VEPError("VEP produced invalid JSON output.") from exc

        provenance = {
            "provider": self.provider_id, "provider_version": self.provider_version,
            "execution_mode": "LOCAL_OFFLINE_CACHE", "genome": build,
            "request_fingerprint": request_fingerprint, "response_sha256": response_sha256,
        }
        by_key: dict[str, dict] = {}
        for record in records:
            payload = self._record_to_payload(record, build=build, provenance=provenance)
            key = self._key(payload["chr"], payload["pos"], payload["ref"], payload["alt"])
            if key in by_key:
                raise VEPError(f"Duplicate VEP result for canonical variant {key}.")
            by_key[key] = payload

        expected = {
            self._key(v.chromosome, v.position, v.reference, v.alternate) for v in variants
        }
        missing, extra = expected - by_key.keys(), by_key.keys() - expected
        if missing or extra:
            raise VEPError(
                f"VEP result set does not match input batch; missing={len(missing)}, extra={len(extra)}."
            )
        return [by_key[self._key(v.chromosome, v.position, v.reference, v.alternate)] for v in variants]

    @classmethod
    def _record_to_payload(
        cls, record: dict[str, Any], *, build: str, provenance: dict[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise VEPError("VEP JSON record is not an object.")
        chromosome = record.get("seq_region_name")
        position = record.get("start")
        allele_string = str(record.get("allele_string") or "")
        alleles = allele_string.split("/")
        reference = alleles[0] if len(alleles) >= 2 else None
        alternate = alleles[-1] if len(alleles) >= 2 else None
        if not chromosome or position is None or not reference or not alternate:
            raw = str(record.get("input") or "").split()
            if len(raw) >= 5:
                chromosome, position, reference, alternate = raw[0], raw[1], raw[3], raw[4]
        try:
            position = int(position)
        except (TypeError, ValueError) as exc:
            raise VEPError("VEP JSON record has an invalid position.") from exc

        transcripts = record.get("transcript_consequences") or []
        if not isinstance(transcripts, list):
            transcripts = []
        consequences = []
        for transcript in transcripts:
            if not isinstance(transcript, dict):
                continue
            consequences.append({
                "consequence": transcript.get("consequence"),
                "gene_symbol": transcript.get("gene_symbol"),
                "gene_id": transcript.get("gene_id"),
                "transcript": transcript.get("transcript_id"),
                "hgvsc": transcript.get("hgvsc"),
                "hgvsp": transcript.get("hgvsp"),
                "biotype": transcript.get("biotype"),
                "canonical": transcript.get("canonical"),
                "mane_select": transcript.get("mane_select"),
                "impact": transcript.get("impact"),
            })
        primary = next(
            (item for item in consequences if item.get("mane_select") or item.get("canonical")),
            consequences[0] if consequences else {},
        )
        colocated = record.get("colocated_variants") or []
        dbsnp = colocated[0].get("id") if colocated and isinstance(colocated[0], dict) else None
        return {
            "genome": build, "chr": str(chromosome).removeprefix("chr"),
            "pos": position, "ref": str(reference), "alt": str(alternate),
            "gene_symbol": primary.get("gene_symbol"), "transcript": primary.get("transcript"),
            "effect": record.get("most_severe_consequence") or primary.get("consequence"),
            "dbsnp": dbsnp, "consequences": consequences,
            "frequency_reference_population": None,
            "computational_score_selected": None, "splice_score_selected": None,
            "_siraloom_annotation_provenance": provenance,
        }
