from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

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
from backend.app.domain.tool_execution import (
    InputArtifact,
    LocalProcessToolExecutor,
    OutputArtifact,
    ScientificResourceBinding,
    ToolExecutionContractError,
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutor,
    ToolIdentity,
)
from backend.app.config import settings


class VEPProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        execution_provenance: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.execution_provenance = execution_provenance


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

    def __init__(
        self,
        contract: ResourceExecutionContract,
        *,
        executor: ToolExecutor | None = None,
    ):
        self.contract = contract
        self.executor = executor or LocalProcessToolExecutor()
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
        self.toolchain_fasta_sha256 = str(toolchain.get("fasta_sha256") or "").strip().lower()
        self.vep_version = str(toolchain.get("vep_version") or "").strip()
        self.tool_profile_id = str(toolchain.get("tool_profile_id") or "").strip()
        self.platform = str(toolchain.get("platform") or "").strip()
        self.qualification_status = str(toolchain.get("qualification_status") or "").strip()
        self.runtime_image_digest = str(toolchain.get("runtime_image_digest") or "").strip().lower()
        self.runtime_path = tuple(str(x) for x in (toolchain.get("runtime_path") or ()))
        self.runtime_environment = {
            str(key): str(value)
            for key, value in (toolchain.get("runtime_environment") or {}).items()
        }
        self.execution_timeout_seconds = int(toolchain.get("execution_timeout_seconds") or 1800)
        self.max_output_bytes = int(toolchain.get("max_output_bytes") or 65536)
        self.scratch_root = str(settings.worker_scratch_root)
        configured_scratch_root = str(toolchain.get("scratch_root") or self.scratch_root)
        if Path(configured_scratch_root).resolve(strict=False) != Path(self.scratch_root).resolve(strict=False):
            raise VEPProviderError("VEP tool profile scratch_root must match the governed worker scratch root.")
        self.extra_args = [str(x) for x in (toolchain.get("extra_args") or [])]
        self._runtime_checks: dict[str, dict[str, Any]] = {}
        self._tool_identity_cache: ToolIdentity | None = None
        self._validate_toolchain()

    @classmethod
    def from_execution_contract(
        cls,
        contract: ResourceExecutionContract,
        *,
        executor: ToolExecutor | None = None,
    ) -> "VEPProvider":
        if contract.provider_id != cls.provider_id:
            raise VEPProviderError(
                f"Execution provider {contract.provider_id!r} does not match VEP."
            )
        if contract.access_method.upper() not in {"LOCAL", "FILE", "LOCAL_ONLY"}:
            raise VEPProviderError(
                f"VEP laboratory execution requires LOCAL/FILE/LOCAL_ONLY access, got {contract.access_method!r}."
            )
        return cls(contract, executor=executor)

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
        if not self.fasta or not Path(self.fasta).is_absolute():
            raise VEPProviderError("VEP execution contract must pin an absolute assembly-matched FASTA path.")
        if not re.fullmatch(r"[0-9a-f]{64}", self.toolchain_fasta_sha256):
            raise VEPProviderError("VEP execution contract must pin the FASTA SHA-256 digest.")
        if not re.fullmatch(r"\d+\.\d+", self.vep_version):
            raise VEPProviderError("VEP execution contract must pin the exact VEP release, e.g. 115.2.")
        if not self.tool_profile_id:
            raise VEPProviderError("VEP execution contract must declare tool_profile_id.")
        if not self.platform:
            raise VEPProviderError("VEP execution contract must pin the worker platform.")
        if self.qualification_status != "SOFTWARE_QUALIFIED":
            raise VEPProviderError("VEP execution requires a SOFTWARE_QUALIFIED tool profile.")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.runtime_image_digest):
            raise VEPProviderError("VEP execution contract must pin the runtime image SHA-256 digest.")
        if not self.runtime_path or any(not Path(item).is_absolute() for item in self.runtime_path):
            raise VEPProviderError("VEP execution contract must pin absolute runtime PATH directories.")
        if "PERL5LIB" not in self.runtime_environment:
            raise VEPProviderError("VEP runtime environment must explicitly pin PERL5LIB.")
        if not 1 <= self.execution_timeout_seconds <= 86400:
            raise VEPProviderError("VEP execution timeout must be between 1 and 86400 seconds.")
        if not 1024 <= self.max_output_bytes <= 10485760:
            raise VEPProviderError("VEP diagnostic output limit must be between 1 KiB and 10 MiB.")
        if not Path(self.scratch_root).is_absolute():
            raise VEPProviderError("VEP scratch_root must be an absolute path.")
        if _version_release(self.vep_version) != self.cache_version:
            raise VEPProviderError("VEP executable release and cache_version must match exactly.")
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
                "--symbol", "--transcript_version", "--hgvs", "--hgvsg",
                "--mane_select",
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
        reference_package = inputs.get("reference_package")
        if not isinstance(reference_package, dict):
            raise VEPProviderError("VEP annotate requires the validated normalization reference package.")
        return ProviderRequest(
            operation="annotate",
            payload={
                "variants": variants,
                "genome_build": inputs.get("genome_build"),
                "reference_package": reference_package,
                "organization_id": inputs.get("organization_id"),
                "workflow_id": inputs.get("workflow_id"),
                "execution_id": inputs.get("execution_id"),
                "workspace": inputs.get("workspace"),
            },
            metadata={
                "provider": self.provider_id,
                "provider_version": self.provider_version,
                "tool_profile_id": self.tool_profile_id,
                "reference_package_checksum": reference_package.get("package_checksum"),
            },
        )

    def execute(self, request: ProviderRequest) -> ProviderRawResult:
        variants = request.payload["variants"]
        build = _canonical_assembly(request.payload.get("genome_build") or self.assembly)
        reference_package = request.payload.get("reference_package")
        if not build:
            raise VEPProviderError("VEP execution requires an explicit GRCh37/GRCh38 assembly.")
        if not isinstance(reference_package, dict):
            raise VEPProviderError("VEP execution requires the validated reference package.")

        scratch_root = Path(self.scratch_root).resolve(strict=True)
        workspace_value = request.payload.get("workspace")
        if workspace_value:
            workspace = Path(str(workspace_value))
            if not workspace.is_absolute():
                raise VEPProviderError("VEP execution workspace must be an absolute path.")
            resolved_workspace = workspace.resolve(strict=False)
            if resolved_workspace != scratch_root and scratch_root not in resolved_workspace.parents:
                raise VEPProviderError("VEP execution workspace must be contained within the governed scratch root.")
            workspace.mkdir(parents=True, exist_ok=True)
        else:
            workspace = Path(tempfile.mkdtemp(prefix="siraloom-vep-", dir=scratch_root))
        if workspace.is_symlink() or not workspace.is_dir():
            raise VEPProviderError("VEP execution workspace must be a regular directory.")
        input_vcf = workspace / "input.vcf"
        output_json = workspace / "output.json"
        input_vcf.unlink(missing_ok=True)
        output_json.unlink(missing_ok=True)

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
        input_sha256 = _sha256_file(input_vcf)

        fasta_path = str(reference_package["fasta_path"])
        argv = [
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
            "--assembly", build,
            "--fasta", fasta_path,
            "--check_ref",
            "--hgvs",
            "--hgvsg",
            "--canonical",
            "--symbol",
            "--transcript_version",
        ]
        annotation_options = [
            "--offline", "--cache", "--format", "vcf", "--json",
            "--check_ref", "--hgvs", "--hgvsg",
            "--canonical", "--symbol", "--transcript_version",
        ]
        if build == "GRCh38":
            # Ensembl documents MANE annotations for human GRCh38 only.
            argv.append("--mane")
            annotation_options.append("--mane")
        argv.extend(self.extra_args)

        execution_id = str(request.payload.get("execution_id") or uuid4())
        organization_id = str(request.payload.get("organization_id") or "").strip()
        workflow_id = str(request.payload.get("workflow_id") or "").strip()
        if not organization_id or not workflow_id:
            raise VEPProviderError("VEP execution requires organization and workflow identity for provenance.")

        execution_request = ToolExecutionRequest(
            execution_id=execution_id,
            organization_id=organization_id,
            workflow_id=workflow_id,
            operation="annotate",
            argv=tuple(argv),
            workspace=str(workspace),
            inputs=(
                InputArtifact(
                    name="normalized-variant-batch",
                    path=str(input_vcf),
                    sha256=input_sha256,
                ),
            ),
            outputs=(OutputArtifact(name="vep-json-response", path=str(output_json)),),
            timeout_seconds=self.execution_timeout_seconds,
            max_output_bytes=self.max_output_bytes,
            resources=(
                ScientificResourceBinding(
                    resource_id=f"vep-cache-manifest:{self.species}",
                    version=self.cache_version,
                    sha256=self.cache_manifest_sha256,
                    assembly=build,
                    path=self.cache_manifest,
                ),
            ),
        )
        try:
            execution_result = self.executor.execute(self._tool_identity(), execution_request)
        except ToolExecutionError as exc:
            failure_provenance = asdict(exc.provenance) if exc.provenance else {}
            failure_provenance.update({
                "workspace_path": str(workspace),
                "raw_response_path": str(output_json) if output_json.is_file() and not output_json.is_symlink() else None,
                "raw_response_sha256": _sha256_file(output_json) if output_json.is_file() and not output_json.is_symlink() else None,
            })
            raise VEPProviderError(
                f"VEP execution failed: {exc}",
                retryable=exc.retryable,
                execution_provenance=failure_provenance,
            ) from exc
        except ToolExecutionContractError as exc:
            raise VEPProviderError(
                f"VEP execution contract rejected the request: {exc}",
                execution_provenance={
                    "tool_profile_id": self.tool_profile_id,
                    "vep_version": self.vep_version,
                    "vep_binary_sha256": self.expected_binary_sha256,
                    "runtime_image_digest": self.runtime_image_digest,
                    "platform": self.platform,
                    "workspace_path": str(workspace),
                    "preflight_error": str(exc),
                },
            ) from exc

        try:
            raw_text = output_json.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise VEPProviderError(
                "VEP output artifact could not be read after successful process execution.",
                execution_provenance=asdict(execution_result.provenance),
            ) from exc
        response_sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        declared_output = next(
            (item["sha256"] for item in execution_result.provenance.output_sha256
             if item["name"] == "vep-json-response"),
            None,
        )
        if declared_output != response_sha256:
            raise VEPProviderError(
                "VEP response bytes changed after executor output verification.",
                execution_provenance=asdict(execution_result.provenance),
            )

        records: list[dict[str, Any]] = []
        try:
            for line in raw_text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise VEPProviderError(
                "VEP returned a non-JSON record in JSON mode.",
                execution_provenance=asdict(execution_result.provenance),
            ) from exc

        return ProviderRawResult(
            operation="annotate",
            payload=records,
            response_sha256=response_sha256,
            metadata={
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "command_provider": self.provider_id,
                "assembly": build,
                "cache_version": self.cache_version,
                "annotation_options": annotation_options,
                "input_sha256": input_sha256,
                "raw_response_path": str(output_json),
                "workspace_path": str(workspace),
                "tool_execution_provenance": asdict(execution_result.provenance),
                "reference_package_checksum": reference_package.get("package_checksum"),
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
        if len(by_key) != len(variants):
            raise VEPProviderError(
                "VEP input batch contains duplicate normalized allele identities."
            )

        seen_keys: set[str] = set()
        for record in result.payload:
            start = record.get("start")
            seq_region = record.get("seq_region_name")
            allele_string = str(record.get("allele_string") or "")
            ref = allele_string.split("/", 1)[0] if "/" in allele_string else None
            alt = allele_string.split("/", 1)[1] if "/" in allele_string else None
            key = f"{seq_region}:{start}:{ref}:{alt}" if ref and alt else None
            if key is None or key not in by_key:
                raise VEPProviderError(
                    "VEP returned an annotation for an allele outside the requested batch."
                )
            if key in seen_keys:
                raise VEPProviderError(
                    f"VEP returned more than one annotation record for allele {key}."
                )
            seen_keys.add(key)
            original = by_key[key]

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
                "most_severe_consequence": record.get("most_severe_consequence"),
                "consequences": transcripts,
                "intergenic_consequences": record.get("intergenic_consequences") or [],
                "regulatory_feature_consequences": record.get("regulatory_feature_consequences") or [],
                "motif_feature_consequences": record.get("motif_feature_consequences") or [],
                "colocated_variants": record.get("colocated_variants") or [],
                "variant_class": record.get("variant_class"),
                "assembly_name": record.get("assembly_name"),
                "selected_transcript": selected or None,
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
                    "provider_version": self.provider_version,
                    "observed_at": result.metadata.get("observed_at"),
                    "response_sha256": result.response_sha256,
                    "raw_response_sha256": result.response_sha256,
                    "assembly": inputs.get("genome_build"),
                    "cache_version": self.cache_version,
                    "annotation_options": result.metadata.get("annotation_options", []),
                    "runtime_check": result.metadata.get("runtime_check"),
                    "tool_execution_provenance": result.metadata.get("tool_execution_provenance"),
                    "raw_response_path": result.metadata.get("raw_response_path"),
                    "workspace_path": result.metadata.get("workspace_path"),
                    "reference_package_checksum": result.metadata.get("reference_package_checksum"),
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

    def _tool_identity(self) -> ToolIdentity:
        if self._tool_identity_cache is None:
            self._tool_identity_cache = ToolIdentity(
                tool_id="ensembl-vep",
                version=self.vep_version,
                profile_id=self.tool_profile_id,
                executable=self.binary,
                executable_sha256=self.expected_binary_sha256,
                platform=self.platform,
                qualification_status=self.qualification_status,
                version_args=("--version",),
                version_output_contains=f"ensembl-vep {self.vep_version}",
                supported_operations=("annotate", "verify_cache"),
                runtime_image_digest=self.runtime_image_digest,
                runtime_path=self.runtime_path,
                runtime_environment=self.runtime_environment,
            )
        return self._tool_identity_cache

    def _verify_runtime_image(self) -> None:
        observed = os.environ.get("SIRALOOM_RUNTIME_IMAGE_DIGEST", "").strip().lower()
        if observed != self.runtime_image_digest:
            raise VEPProviderError(
                "Running worker image digest does not match the organization-approved VEP tool profile.",
                execution_provenance={
                    "tool_profile_id": self.tool_profile_id,
                    "expected_runtime_image_digest": self.runtime_image_digest,
                    "observed_runtime_image_digest": observed or None,
                    "platform": self.platform,
                },
            )

    @staticmethod
    def _require_read_only_mount(path: Path, *, label: str) -> None:
        try:
            flags = os.statvfs(path).f_flag
        except OSError as exc:
            raise VEPProviderError(f"{label} resource mount cannot be inspected.") from exc
        read_only_flag = getattr(os, "ST_RDONLY", 1)
        if not flags & read_only_flag:
            raise VEPProviderError(
                f"{label} resource must be mounted read-only for reproducible VEP execution."
            )

    def _reference_resource_bindings(
        self,
        reference_package: dict[str, Any],
        assembly: str,
    ) -> tuple[ScientificResourceBinding, ...]:
        if not isinstance(reference_package, dict):
            raise VEPProviderError("VEP requires the validated reference package from the normalization stage.")
        package_assembly = _canonical_assembly(str(reference_package.get("assembly_name") or ""))
        if package_assembly != assembly:
            raise VEPProviderError(
                "VEP reference package assembly does not match the normalized analysis assembly."
            )
        package_checksum = str(reference_package.get("package_checksum") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", package_checksum):
            raise VEPProviderError("Validated reference package is missing its SHA-256 package checksum.")

        resource_id = str(reference_package.get("resource_id") or "").strip()
        resource_version = str(reference_package.get("version") or "").strip()
        if not resource_id or not resource_version:
            raise VEPProviderError("Validated reference package identity is incomplete.")

        fasta_path = Path(str(reference_package.get("fasta_path") or ""))
        fai_path = Path(str(reference_package.get("fai_path") or ""))
        fasta_sha256 = str(reference_package.get("fasta_sha256") or "").lower()
        fai_sha256 = str(reference_package.get("fai_sha256") or "").lower()
        if (
            not fasta_path.is_absolute()
            or not fai_path.is_absolute()
            or not re.fullmatch(r"[0-9a-f]{64}", fasta_sha256)
            or not re.fullmatch(r"[0-9a-f]{64}", fai_sha256)
        ):
            raise VEPProviderError("Validated reference package must pin absolute FASTA/FAI paths and SHA-256 digests.")

        if self.fasta and Path(self.fasta).resolve(strict=False) != fasta_path.resolve(strict=False):
            raise VEPProviderError("VEP FASTA path differs from the reference package used by normalization.")
        if self.toolchain_fasta_sha256 and self.toolchain_fasta_sha256 != fasta_sha256:
            raise VEPProviderError("VEP FASTA digest differs from the organization-approved reference package.")

        self._require_read_only_mount(fasta_path, label="Reference FASTA")
        self._require_read_only_mount(fai_path, label="Reference FAI")
        bindings = [
            ScientificResourceBinding(
                resource_id=f"{resource_id}:FASTA",
                version=resource_version,
                sha256=fasta_sha256,
                assembly=assembly,
                path=str(fasta_path),
            ),
            ScientificResourceBinding(
                resource_id=f"{resource_id}:FAI",
                version=resource_version,
                sha256=fai_sha256,
                assembly=assembly,
                path=str(fai_path),
            ),
        ]
        gzi_path_value = reference_package.get("gzi_path")
        gzi_sha256 = str(reference_package.get("gzi_sha256") or "").lower()
        if gzi_path_value:
            gzi_path = Path(str(gzi_path_value))
            if not gzi_path.is_absolute() or not re.fullmatch(r"[0-9a-f]{64}", gzi_sha256):
                raise VEPProviderError("Reference GZI index path or digest is invalid.")
            self._require_read_only_mount(gzi_path, label="Reference GZI")
            bindings.append(ScientificResourceBinding(
                resource_id=f"{resource_id}:GZI",
                version=resource_version,
                sha256=gzi_sha256,
                assembly=assembly,
                path=str(gzi_path),
            ))
        return tuple(bindings)

    def annotate(self, variants: list[CanonicalVariant], context: dict[str, Any]) -> list[dict[str, Any]]:
        genome_build = _canonical_assembly(context.get("genome_build") or context.get("genome"))
        if not genome_build:
            raise VEPProviderError("VEP annotation requires an explicit GRCh37/GRCh38 assembly.")
        reference_package = context.get("reference_package")
        runtime_check = self.verify_local_runtime(
            genome_build,
            reference_package=reference_package,
            context=context,
        )
        request = self.prepare_request(
            "annotate",
            {
                "variants": variants,
                "genome_build": genome_build,
                "reference_package": reference_package,
                "organization_id": context.get("organization_id"),
                "workflow_id": context.get("workflow_id"),
            },
        )
        raw = self.execute(request)
        raw.metadata["runtime_check"] = runtime_check
        try:
            normalized = self.normalize_result(raw, inputs=request.payload)
        except VEPProviderError as exc:
            failure_provenance = dict(exc.execution_provenance or {})
            failure_provenance.update({
                "raw_response_path": raw.metadata.get("raw_response_path"),
                "workspace_path": raw.metadata.get("workspace_path"),
                "raw_response_sha256": raw.response_sha256,
                "tool_execution_provenance": raw.metadata.get("tool_execution_provenance"),
            })
            exc.execution_provenance = failure_provenance
            raise
        return list(normalized.observations)

    def verify_local_runtime(
        self,
        genome_build: str | None,
        *,
        reference_package: dict[str, Any] | None,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Verify the exact VEP executable, offline cache and normalization reference."""
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
        package_checksum = str((reference_package or {}).get("package_checksum") or "").lower()
        runtime_key = f"{assembly}:{package_checksum}"
        if runtime_key in self._runtime_checks:
            return dict(self._runtime_checks[runtime_key])

        self._verify_runtime_image()
        reference_bindings = self._reference_resource_bindings(reference_package or {}, assembly)
        cache_manifest_check = self._verify_cache_manifest(assembly)
        self._require_read_only_mount(Path(self.cache_dir), label="VEP cache")
        self._require_read_only_mount(Path(self.cache_manifest), label="VEP cache manifest")
        cache_binding = ScientificResourceBinding(
            resource_id=f"vep-cache-manifest:{self.species}",
            version=self.cache_version,
            sha256=self.cache_manifest_sha256,
            assembly=assembly,
            path=self.cache_manifest,
        )
        scratch_root = Path(self.scratch_root).resolve(strict=True)
        if not scratch_root.is_dir():
            raise VEPProviderError("VEP scratch root is not a directory.")

        organization_id = str(context.get("organization_id") or "").strip()
        workflow_id = str(context.get("workflow_id") or "").strip()
        if not organization_id or not workflow_id:
            raise VEPProviderError("VEP execution requires organization and workflow identity for provenance.")

        with TemporaryDirectory(prefix="siraloom-vep-preflight-", dir=scratch_root) as workspace:
            request = ToolExecutionRequest(
                execution_id=str(uuid4()),
                organization_id=organization_id,
                workflow_id=workflow_id,
                operation="verify_cache",
                argv=(
                    "--offline", "--cache",
                    "--species", self.species,
                    "--cache_version", self.cache_version,
                    "--dir_cache", self.cache_dir,
                    "--assembly", assembly,
                    "--show_cache_info",
                ),
                workspace=workspace,
                timeout_seconds=120,
                max_output_bytes=self.max_output_bytes,
                resources=(cache_binding, *reference_bindings),
            )
            try:
                result = self.executor.execute(self._tool_identity(), request)
            except ToolExecutionError as exc:
                raise VEPProviderError(
                    f"VEP offline cache verification failed: {exc}",
                    retryable=exc.retryable,
                    execution_provenance=asdict(exc.provenance) if exc.provenance else None,
                ) from exc
            except ToolExecutionContractError as exc:
                raise VEPProviderError(
                    f"VEP execution preflight contract failed: {exc}",
                    execution_provenance={
                        "tool_profile_id": self.tool_profile_id,
                        "vep_version": self.vep_version,
                        "vep_binary_sha256": self.expected_binary_sha256,
                        "runtime_image_digest": self.runtime_image_digest,
                        "platform": self.platform,
                        "preflight_error": str(exc),
                    },
                ) from exc

        cache_output = "\n".join((result.stdout or "", result.stderr or "")).strip()
        if not cache_output:
            raise VEPProviderError(
                "VEP offline cache verification returned no cache information.",
                execution_provenance=asdict(result.provenance),
            )

        runtime_check = {
            "status": "VERIFIED",
            "assembly": assembly,
            "vep_version": self.vep_version,
            "expected_vep_version": self.vep_version,
            "tool_profile_id": self.tool_profile_id,
            "platform": self.platform,
            "runtime_image_digest": self.runtime_image_digest,
            "vep_binary_sha256": self.expected_binary_sha256,
            "cache_version": self.cache_version,
            "cache_manifest_sha256": cache_manifest_check["manifest_sha256"],
            "cache_tree_sha256": cache_manifest_check["tree_sha256"],
            "cache_artifact_sha256": cache_manifest_check["source_artifact_sha256"],
            "cache_info_sha256": hashlib.sha256(cache_output.encode("utf-8")).hexdigest(),
            "reference_package": {
                "resource_id": reference_package["resource_id"],
                "version": reference_package["version"],
                "package_checksum": package_checksum,
                "assembly_name": reference_package["assembly_name"],
                "fasta_sha256": reference_package["fasta_sha256"],
                "fai_sha256": reference_package["fai_sha256"],
                "gzi_sha256": reference_package.get("gzi_sha256"),
            },
            "tool_execution_provenance": asdict(result.provenance),
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
        self._runtime_checks[runtime_key] = runtime_check
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
