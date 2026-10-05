from __future__ import annotations

import subprocess
from dataclasses import dataclass

from backend.app.domain.resource_source_contract import ResourceExecutionContract


class SecondaryPopulationProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class SecondaryPopulationObservation:
    population_level: str
    population_code: str
    population_label: str
    allele_count: int | None
    allele_number: int | None
    allele_frequency: float | None
    homozygote_count: int | None = None
    availability: str = "AVAILABLE"
    quality_status: str = "PROVIDER_DERIVED"
    source_record_id: str | None = None


class LocalTabixSecondaryPopulationProvider:
    """Governed tabix VCF adapter; dataset-specific INFO mappings are contract-bound."""

    supported_providers = frozenset({"1000GENOMES", "TOPMED", "MIDDLE_EAST", "INTERNAL_LAB_POPULATION"})

    def __init__(self, provider_id, vcf_path, info_fields, population_code, population_label, executable="tabix", contig_policy="EXACT"):
        self.provider_id = provider_id
        self.vcf_path = vcf_path
        self.info_fields = dict(info_fields)
        self.population_code = population_code
        self.population_label = population_label
        self.executable = executable
        self.contig_policy = contig_policy

    @classmethod
    def from_execution_contract(cls, contract: ResourceExecutionContract):
        provider = str(contract.provider_id or "").upper()
        if provider not in cls.supported_providers:
            raise SecondaryPopulationProviderError(f"Unsupported secondary population provider {contract.provider_id!r}.")
        if not contract.provider_version:
            raise SecondaryPopulationProviderError(f"{provider} execution contract must declare a dataset version.")
        if contract.access_method not in {"LOCAL", "FILE", "LOCAL_ONLY"}:
            raise SecondaryPopulationProviderError(f"{provider} secondary population requires LOCAL/FILE execution.")
        if not contract.location:
            raise SecondaryPopulationProviderError(f"{provider} secondary population has no VCF location.")
        toolchain = dict(contract.toolchain or {})
        fields = toolchain.get("info_fields")
        if not isinstance(fields, dict):
            raise SecondaryPopulationProviderError(f"{provider} execution contract must declare toolchain.info_fields.")
        fields = {str(k): str(v) for k, v in fields.items() if v not in (None, "")}
        contig_policy = str(toolchain.get("contig_policy") or "EXACT").upper()
        if contig_policy not in {"EXACT", "CHR_PREFIX"}:
            raise SecondaryPopulationProviderError(
                f"{provider} execution contract declares unsupported contig_policy {contig_policy!r}."
            )
        if not fields.get("AF") and not (fields.get("AC") and fields.get("AN")):
            raise SecondaryPopulationProviderError(f"{provider} execution contract must map AF or both AC and AN.")
        return cls(
            provider,
            contract.location,
            fields,
            str(toolchain.get("population_code") or "GLOBAL"),
            str(toolchain.get("population_label") or provider),
            str(toolchain.get("tabix_executable") or "tabix"),
            contig_policy,
        )

    def query_variant(self, variant):
        region = f"{variant.chromosome}:{variant.position}-{variant.position}"
        try:
            proc = subprocess.run([self.executable, self.vcf_path, region], check=False,
                                  capture_output=True, text=True, timeout=30)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise SecondaryPopulationProviderError(f"{self.provider_id} tabix execution unavailable or timed out.") from exc
        if proc.returncode not in (0, 1):
            raise SecondaryPopulationProviderError(proc.stderr.strip() or f"{self.provider_id} tabix failed.")
        for line in proc.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) < 8:
                continue
            chrom, pos, record_id, ref, alt = fields[:5]
            if not _contigs_match(chrom, variant.chromosome, self.contig_policy) or ref.upper() != variant.reference.upper():
                continue
            try:
                if int(pos) != variant.position:
                    continue
            except ValueError:
                continue
            alts = alt.split(",")
            if variant.alternate.upper() not in [x.upper() for x in alts]:
                continue
            index = [x.upper() for x in alts].index(variant.alternate.upper())
            info = _parse_info(fields[7])
            ac = _array_int(info.get(self.info_fields.get("AC", "")), index)
            an = _scalar_int(info.get(self.info_fields.get("AN", "")))
            af = _array_float(info.get(self.info_fields.get("AF", "")), index)
            hom = _array_int(info.get(self.info_fields.get("HOM_ALT", "")), index)
            if af is None and ac is not None and an not in (None, 0):
                af = ac / an
            return [SecondaryPopulationObservation(
                "SECONDARY", self.population_code, self.population_label, ac, an, af, hom,
                "AVAILABLE" if any(x is not None for x in (ac, an, af, hom)) else "NOT_AVAILABLE",
                "PROVIDER_DERIVED", record_id or f"{chrom}:{pos}:{ref}:{alt}")]
        return []


def _parse_info(value):
    result = {}
    for item in value.split(";"):
        key, sep, val = item.partition("=")
        result[key] = val if sep else None
    return result


def _array_int(value, index):
    if value in (None, "", "."):
        return None
    parts = value.split(",")
    if index >= len(parts) or parts[index] in ("", "."):
        return None
    try:
        return int(parts[index])
    except ValueError:
        return None


def _array_float(value, index):
    if value in (None, "", "."):
        return None
    parts = value.split(",")
    if index >= len(parts) or parts[index] in ("", "."):
        return None
    try:
        return float(parts[index])
    except ValueError:
        return None


def _scalar_int(value):
    if value in (None, "", "."):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _contigs_match(resource_contig, variant_contig, policy):
    if policy == "EXACT":
        return resource_contig == variant_contig
    if policy == "CHR_PREFIX":
        def canonical(value):
            return value[3:] if value.lower().startswith("chr") else value
        return canonical(resource_contig) == canonical(variant_contig)
    raise SecondaryPopulationProviderError(f"Unsupported contig policy {policy!r}.")
