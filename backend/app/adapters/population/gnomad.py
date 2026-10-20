from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Iterable

import httpx

from backend.app.domain.schemas import CanonicalVariant
from backend.app.domain.resource_source_contract import ResourceExecutionContract


class GnomADProviderError(RuntimeError):
    """Provider failure with explicit transient/permanent retry semantics."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = bool(retryable)


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
    request_fingerprint: str | None = None
    response_sha256: str | None = None
    request_metadata: dict[str, Any] | None = None
    observed_at: str | None = None


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

    def __init__(self, endpoint: str | None = None, dataset_id: str = "gnomad_r4", delay_seconds: float = 0.0):
        self.endpoint = endpoint or self.default_endpoint
        self.dataset_id = dataset_id
        self.delay_seconds = max(0.0, delay_seconds)
        self.execution_scope = "UNSPECIFIED"

    @classmethod
    def from_execution_contract(
        cls,
        contract: ResourceExecutionContract,
        *,
        delay_seconds: float = 0.0,
    ) -> "GnomADGraphQLProvider":
        if contract.provider_id != "gnomAD":
            raise GnomADProviderError(
                f"Execution provider {contract.provider_id!r} does not match gnomAD."
            )
        if contract.provider_version != cls.provider_version:
            raise GnomADProviderError(
                f"Execution provider version {contract.provider_version!r} does not match gnomAD {cls.provider_version!r}."
            )
        if contract.access_method not in {"API", "HTTPS", "HTTP", "GRAPHQL"}:
            raise GnomADProviderError(
                f"gNOMAD requires an API/HTTP execution contract, got {contract.access_method!r}."
            )
        if not contract.endpoint:
            raise GnomADProviderError("gNOMAD execution contract does not contain an endpoint.")
        if not contract.dataset:
            raise GnomADProviderError("gNOMAD execution contract does not contain a dataset.")
        provider = cls(endpoint=contract.endpoint, dataset_id=contract.dataset, delay_seconds=delay_seconds)
        provider.execution_scope = contract.execution_scope
        return provider

    def query_variant(self, variant: CanonicalVariant) -> list[PopulationObservationData]:
        variant_id = f"{variant.chromosome.removeprefix('chr')}:{variant.position}:{variant.reference}:{variant.alternate}"
        query = """
        query Variant($variantId: String!, $dataset: DatasetId!) {
          variant(variantId: $variantId, dataset: $dataset) {
            joint {
              ac
              an
              homozygote_count
              populations { id ac an homozygote_count }
            }
            exome {
              ac
              an
              homozygote_count
              populations { id ac an homozygote_count }
            }
            genome {
              ac
              an
              homozygote_count
              populations { id ac an homozygote_count }
            }
          }
        }
        """
        variables = {"variantId": variant_id, "dataset": self.dataset_id}
        request_metadata = {
            "provider": self.provider_id,
            "provider_version": self.provider_version,
            "endpoint": self.endpoint,
            "dataset_selector": self.dataset_id,
            "variant_id": variant_id,
            "genome_build": variant.genome_build,
            "execution_scope": self.execution_scope,
        }
        request_fingerprint = hashlib.sha256(
            json.dumps(
                {"query": query, "variables": variables},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        from datetime import datetime, timezone
        observed_at = datetime.now(timezone.utc).isoformat()
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(self.endpoint, json={"query": query, "variables": variables})
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retryable = status == 429 or 500 <= status <= 599
            raise GnomADProviderError(
                f"gnoMAD GraphQL request failed with HTTP {status}: {exc}",
                retryable=retryable,
            ) from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise GnomADProviderError(
                f"gnoMAD GraphQL transport failure: {exc}",
                retryable=True,
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise GnomADProviderError(
                f"gnoMAD GraphQL request failed: {exc}",
                retryable=False,
            ) from exc

        response_sha256 = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if not isinstance(body, dict):
            raise GnomADProviderError("gnoMAD GraphQL response must be a JSON object")
        data = body.get("data")
        if not isinstance(data, dict) or "variant" not in data:
            raise GnomADProviderError("gnoMAD GraphQL response is missing data.variant")
        details = data["variant"]
        if details is not None and not isinstance(details, dict):
            raise GnomADProviderError("gnoMAD GraphQL data.variant must be an object or null")
        errors = body.get("errors") or []
        if not isinstance(errors, list):
            raise GnomADProviderError("gnoMAD GraphQL errors field must be a list")
        if errors:
            if any(not isinstance(item, dict) or not isinstance(item.get("message"), str) for item in errors):
                raise GnomADProviderError("gnoMAD GraphQL response contains malformed errors")
            messages = [item["message"] for item in errors]
            is_not_found = details is None and messages and all(
                message.strip().casefold() == "variant not found" for message in messages
            )
            if not is_not_found:
                raise GnomADProviderError(f"gnoMAD GraphQL errors: {errors}")
        if details is None:
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            return [
                PopulationObservationData(
                    population_level=level,
                    population_code=code,
                    population_label=label,
                    allele_count=None,
                    allele_number=None,
                    allele_frequency=None,
                    homozygote_count=None,
                    availability="NOT_FOUND",
                    quality_status="NO_MATCH",
                    request_fingerprint=request_fingerprint,
                    response_sha256=response_sha256,
                    request_metadata=request_metadata,
                    observed_at=observed_at,
                )
                for level, code, label in (
                    ("GLOBAL", "GLOBAL", "gnomAD joint"),
                    ("ANCESTRY", "MID", "Middle Eastern (joint)"),
                    ("GLOBAL", "GLOBAL_EXOMES", "gnomAD exomes"),
                    ("GLOBAL", "GLOBAL_GENOMES", "gnomAD genomes"),
                    ("ANCESTRY", "MID_EXOMES", "Middle Eastern (exomes)"),
                    ("ANCESTRY", "MID_GENOMES", "Middle Eastern (genomes)"),
                )
            ]

        observations: list[PopulationObservationData] = []
        source_record_id = variant_id.replace(":", "-")
        joint_details = details.get("joint")
        if joint_details is None:
            joint_details = {}
        elif not isinstance(joint_details, dict):
            raise GnomADProviderError("gnoMAD GraphQL joint result must be an object or null")
        joint_ac = _int_or_none(joint_details.get("ac"))
        joint_an = _int_or_none(joint_details.get("an"))
        joint_hom = _int_or_none(joint_details.get("homozygote_count"))
        joint_values_available = any(value is not None for value in (joint_ac, joint_an, joint_hom))
        observations.append(
            PopulationObservationData(
                population_level="GLOBAL",
                population_code="GLOBAL",
                population_label="gnomAD joint",
                allele_count=joint_ac,
                allele_number=joint_an,
                allele_frequency=_af(joint_ac, joint_an),
                homozygote_count=joint_hom,
                availability="AVAILABLE" if joint_values_available else "NOT_AVAILABLE",
                quality_status="PASS" if joint_values_available else "NO_OBSERVATION",
                source_record_id=source_record_id,
                request_fingerprint=request_fingerprint,
                response_sha256=response_sha256,
                request_metadata=request_metadata,
                observed_at=observed_at,
            )
        )
        joint_populations = joint_details.get("populations") or []
        if not isinstance(joint_populations, list) or any(not isinstance(pop, dict) for pop in joint_populations):
            raise GnomADProviderError("gnoMAD GraphQL joint.populations must be a list of objects")
        mid_joint = next(
            (pop for pop in joint_populations if str(pop.get("id", "")).casefold() == "mid"),
            None,
        )
        if mid_joint is not None:
            mid_ac = _int_or_none(mid_joint.get("ac"))
            mid_an = _int_or_none(mid_joint.get("an"))
            mid_hom = _int_or_none(mid_joint.get("homozygote_count"))
        else:
            mid_ac = mid_an = mid_hom = None
        mid_joint_available = any(value is not None for value in (mid_ac, mid_an, mid_hom))
        observations.append(
            PopulationObservationData(
                population_level="ANCESTRY",
                population_code="MID",
                population_label="Middle Eastern (joint)",
                allele_count=mid_ac,
                allele_number=mid_an,
                allele_frequency=_af(mid_ac, mid_an),
                homozygote_count=mid_hom,
                availability="AVAILABLE" if mid_joint_available else "NOT_AVAILABLE",
                quality_status="PASS" if mid_joint_available else "NO_ANCESTRY_OBSERVATION",
                source_record_id=source_record_id,
                request_fingerprint=request_fingerprint,
                response_sha256=response_sha256,
                request_metadata=request_metadata,
                observed_at=observed_at,
            )
        )
        for cohort in ("exome", "genome"):
            cohort_details = details.get(cohort)
            if cohort_details is None:
                cohort_details = {}
            elif not isinstance(cohort_details, dict):
                raise GnomADProviderError(f"gnoMAD GraphQL {cohort} result must be an object or null")
            cohort_code = f"{cohort.upper()}S"
            global_ac = _int_or_none(cohort_details.get("ac"))
            global_an = _int_or_none(cohort_details.get("an"))
            global_hom = _int_or_none(cohort_details.get("homozygote_count"))
            observations.append(
                PopulationObservationData(
                    population_level="GLOBAL",
                    population_code=f"GLOBAL_{cohort_code}",
                    population_label=f"gnomAD {cohort}s",
                    allele_count=global_ac,
                    allele_number=global_an,
                    allele_frequency=_af(global_ac, global_an),
                    homozygote_count=global_hom,
                    availability=("AVAILABLE" if any(value is not None for value in (global_ac, global_an, global_hom)) else "NOT_AVAILABLE"),
                    quality_status=("PASS" if any(value is not None for value in (global_ac, global_an, global_hom)) else "NO_OBSERVATION"),
                    source_record_id=source_record_id,
                    request_fingerprint=request_fingerprint,
                    response_sha256=response_sha256,
                    request_metadata=request_metadata,
                    observed_at=observed_at,
                )
            )
            populations = cohort_details.get("populations") or []
            if not isinstance(populations, list) or any(not isinstance(pop, dict) for pop in populations):
                raise GnomADProviderError(f"gnoMAD GraphQL {cohort}.populations must be a list of objects")
            mid_pop = next(
                (
                    pop for pop in populations
                    if str(pop.get("id", "")).casefold() == "mid"
                ),
                None,
            )
            if mid_pop is not None:
                ac = _int_or_none(mid_pop.get("ac"))
                an = _int_or_none(mid_pop.get("an"))
                hom = _int_or_none(mid_pop.get("homozygote_count"))
            else:
                ac = an = hom = None
            observations.append(
                PopulationObservationData(
                    population_level="ANCESTRY",
                    population_code=f"MID_{cohort_code}",
                    population_label=f"Middle Eastern ({cohort}s)",
                    allele_count=ac,
                    allele_number=an,
                    allele_frequency=_af(ac, an),
                    homozygote_count=hom,
                    availability=("AVAILABLE" if any(value is not None for value in (ac, an, hom)) else "NOT_AVAILABLE"),
                    quality_status=("PASS" if any(value is not None for value in (ac, an, hom)) else "NO_ANCESTRY_OBSERVATION"),
                    source_record_id=source_record_id,
                    request_fingerprint=request_fingerprint,
                    response_sha256=response_sha256,
                    request_metadata=request_metadata,
                    observed_at=observed_at,
                )
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
        self.execution_scope = "UNSPECIFIED"

    @classmethod
    def from_execution_contract(cls, contract: ResourceExecutionContract) -> "LocalGnomADTabixProvider":
        if contract.provider_id != cls.provider_id:
            raise GnomADProviderError(
                f"Execution provider {contract.provider_id!r} does not match local gnomAD."
            )
        if contract.provider_version != cls.provider_version:
            raise GnomADProviderError(
                f"Execution provider version {contract.provider_version!r} does not match local gnomAD {cls.provider_version!r}."
            )
        if contract.access_method not in {"LOCAL", "FILE", "LOCAL_ONLY"}:
            raise GnomADProviderError(
                f"Local gnomAD requires a LOCAL/FILE execution contract, got {contract.access_method!r}."
            )
        if not contract.location:
            raise GnomADProviderError("Local gnomAD execution contract does not contain a location.")
        provider = cls(contract.location)
        provider.execution_scope = contract.execution_scope
        return provider

    def query_variant(self, variant: CanonicalVariant) -> list[PopulationObservationData]:
        chrom = variant.chromosome
        region = f"{chrom}:{variant.position}-{variant.position}"
        try:
            proc = subprocess.Popen(
                ["tabix", self.vcf_path, region],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                stdout, stderr = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired as exc:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                raise GnomADProviderError("tabix timed out and its process group was terminated") from exc
        except FileNotFoundError as exc:
            raise GnomADProviderError("tabix executable is not available") from exc
        if proc.returncode not in (0, 1):
            raise GnomADProviderError((stderr or "").strip() or f"tabix failed with code {proc.returncode}")

        from datetime import datetime, timezone

        request_metadata = {
            "provider": self.provider_id,
            "provider_version": self.provider_version,
            "resource_location": self.vcf_path,
            "region": region,
            "genome_build": variant.genome_build,
            "execution_scope": self.execution_scope,
        }
        request_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    **request_metadata,
                    "reference": variant.reference,
                    "alternate": variant.alternate,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        response_sha256 = hashlib.sha256(stdout.encode("utf-8")).hexdigest()
        observed_at = datetime.now(timezone.utc).isoformat()

        best: dict[str, Any] | None = None
        for line in stdout.splitlines():
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
            return [
                PopulationObservationData(
                    population_level=level,
                    population_code=code,
                    population_label=label,
                    allele_count=None,
                    allele_number=None,
                    allele_frequency=None,
                    homozygote_count=None,
                    availability="NOT_FOUND",
                    quality_status="NO_MATCH",
                    request_fingerprint=request_fingerprint,
                    response_sha256=response_sha256,
                    request_metadata=request_metadata,
                    observed_at=observed_at,
                )
                for level, code, label in (
                    ("GLOBAL", "GLOBAL", "Global"),
                    ("ANCESTRY", "MID", "Middle Eastern"),
                )
            ]

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
                    request_fingerprint=request_fingerprint,
                    response_sha256=response_sha256,
                    request_metadata=request_metadata,
                    observed_at=observed_at,
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
