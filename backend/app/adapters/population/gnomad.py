from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Iterable

import httpx

from backend.app.domain.schemas import CanonicalVariant


class GnomADProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class PopulationObservationData:
    population_level: str
    population_code: str
    population_label: str
    allele_count: int | None
    allele_number: int | None
    allele_frequency: float | None
    homozygote_count: int | None
    availability: str = "AVAILABLE"
    quality_status: str = "PASS"
    source_record_id: str | None = None


class GnomADGraphQLProvider:
    """Development/reference provider for targeted gnomAD ancestry lookups.

    gnomAD's public browser API is intended for targeted variant/gene/region use,
    not bulk VCF annotation. Therefore this provider is deliberately bounded and
    configurable. Production bulk annotation should use a validated local indexed
    resource where available.
    """

    provider_id = "gnomad-graphql"
    provider_version = "graphql"
    default_endpoint = "https://gnomad.broadinstitute.org/api"

    def __init__(self, endpoint: str = default_endpoint, dataset_id: str = "gnomad_r4", delay_seconds: float = 0.0):
        self.endpoint = endpoint
        self.dataset_id = dataset_id
        self.delay_seconds = max(0.0, delay_seconds)

    def query_variant(self, variant: CanonicalVariant) -> list[PopulationObservationData]:
        variant_id = f"{variant.chromosome.removeprefix('chr')}:{variant.position}:{variant.reference}:{variant.alternate}"
        query = """
        query Variant($variantId: String!, $dataset: DatasetId!) {
          variant(variantId: $variantId, dataset: $dataset) {
            variantId
            ac
            an
            populations {
              id
              ac
              an
              ac_hom
              ac_hemi
            }
            exome {
              ac
              an
              populations { id ac an ac_hom ac_hemi }
            }
            genome {
              ac
              an
              populations { id ac an ac_hom ac_hemi }
            }
          }
        }
        """
        variables = {"variantId": variant_id, "dataset": self.dataset_id}
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(self.endpoint, json={"query": query, "variables": variables})
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GnomADProviderError(f"gnoMAD GraphQL request failed: {exc}") from exc

        if body.get("errors"):
            raise GnomADProviderError(f"gnoMAD GraphQL errors: {body['errors']}")
        details = (body.get("data") or {}).get("variant")
        if details is None:
            return []

        observations: list[PopulationObservationData] = []
        for pop in details.get("populations") or []:
            if pop.get("id") == "mid":
                ac = _int_or_none(pop.get("ac"))
                an = _int_or_none(pop.get("an"))
                observations.append(
                    PopulationObservationData(
                        population_level="ANCESTRY",
                        population_code="MID",
                        population_label="Middle Eastern",
                        allele_count=ac,
                        allele_number=an,
                        allele_frequency=_af(ac, an),
                        homozygote_count=_int_or_none(pop.get("ac_hom")),
                        source_record_id=details.get("variantId"),
                    )
                )

        # Global joint observation, when present in the API response.
        ac = _int_or_none(details.get("ac"))
        an = _int_or_none(details.get("an"))
        if ac is not None or an is not None:
            observations.insert(
                0,
                PopulationObservationData(
                    population_level="GLOBAL",
                    population_code="GLOBAL",
                    population_label="Global",
                    allele_count=ac,
                    allele_number=an,
                    allele_frequency=_af(ac, an),
                    homozygote_count=None,
                    source_record_id=details.get("variantId"),
                ),
            )
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        return observations


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _af(ac: int | None, an: int | None) -> float | None:
    if ac is None or an in (None, 0):
        return None
    return ac / an


class LocalGnomADTabixProvider:
    """Query a bgzip+tabix indexed gnomAD VCF by exact locus.

    Designed for on-premise laboratory deployment. It uses the tabix executable
    rather than loading a multi-hundred-GB release into Python memory.
    """

    provider_id = "gnomad-local-tabix"
    provider_version = "vcf-tabix"

    def __init__(self, vcf_path: str):
        self.vcf_path = vcf_path

    def query_variant(self, variant: CanonicalVariant) -> list[PopulationObservationData]:
        chrom = variant.chromosome
        region = f"{chrom}:{variant.position}-{variant.position}"
        try:
            proc = subprocess.run(
                ["tabix", self.vcf_path, region],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise GnomADProviderError("tabix is not available or timed out") from exc
        if proc.returncode not in (0, 1):
            raise GnomADProviderError(proc.stderr.strip() or f"tabix failed with code {proc.returncode}")

        best: dict[str, Any] | None = None
        for line in proc.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) < 8:
                continue
            record_chrom, pos_s, _vid, ref, alt, _qual, _flt, info_s = fields[:8]
            if record_chrom.removeprefix("chr") != variant.chromosome.removeprefix("chr"):
                continue
            if int(pos_s) != variant.position or ref.upper() != variant.reference.upper():
                continue
            alts = alt.split(",")
            if variant.alternate.upper() not in [a.upper() for a in alts]:
                continue
            alt_index = [a.upper() for a in alts].index(variant.alternate.upper())
            info = _parse_info(info_s)
            best = {"info": info, "alt_index": alt_index, "variant_id": f"{record_chrom}:{pos_s}:{ref}:{alt}"}
            break

        if best is None:
            return []

        observations: list[PopulationObservationData] = []
        info = best["info"]
        for code, label in (("GLOBAL", "Global"), ("MID", "Middle Eastern")):
            suffix = "" if code == "GLOBAL" else "_mid"
            ac = _array_value(info.get(f"AC{suffix}"), best["alt_index"])
            an = _scalar_int(info.get(f"AN{suffix}"))
            af = _array_float(info.get(f"AF{suffix}"), best["alt_index"])
            hom = _array_value(info.get(f"nhomalt{suffix}"), best["alt_index"])
            if af is None:
                af = _af(ac, an)
            availability = "AVAILABLE" if any(v is not None for v in (ac, an, af, hom)) else "NOT_AVAILABLE"
            observations.append(
                PopulationObservationData(
                    population_level="GLOBAL" if code == "GLOBAL" else "ANCESTRY",
                    population_code=code,
                    population_label=label,
                    allele_count=ac,
                    allele_number=an,
                    allele_frequency=af,
                    homozygote_count=hom,
                    availability=availability,
                    source_record_id=best["variant_id"],
                )
            )
        return observations


def _parse_info(info: str) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for item in info.split(";"):
        if "=" not in item:
            result[item] = None
            continue
        key, value = item.split("=", 1)
        result[key] = value
    return result


def _array_value(value: str | None, index: int) -> int | None:
    if value is None:
        return None
    parts = value.split(",")
    if index >= len(parts) or parts[index] in {"", "."}:
        return None
    return _int_or_none(parts[index])


def _array_float(value: str | None, index: int) -> float | None:
    if value is None:
        return None
    parts = value.split(",")
    if index >= len(parts) or parts[index] in {"", "."}:
        return None
    return _float_or_none(parts[index])


def _scalar_int(value: str | None) -> int | None:
    return _int_or_none(value)
