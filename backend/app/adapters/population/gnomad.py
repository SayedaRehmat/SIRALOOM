from __future__ import annotations

import hashlib
import json
import math
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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
            joint_details = {"ac": None, "an": None, "homozygote_count": None}
        elif not isinstance(joint_details, dict):
            raise GnomADProviderError("gnoMAD GraphQL joint result must be an object or null")
        joint_ac, joint_an, joint_hom = _graphql_counts(
            joint_details, context="joint", nullable=True
        )
        joint_values_available = _frequency_available(joint_ac, joint_an)
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
        joint_populations = _graphql_populations(
            joint_details.get("populations"), context="joint"
        )
        mid_joint = joint_populations.get("mid")
        if mid_joint is not None:
            mid_ac, mid_an, mid_hom = mid_joint
        else:
            mid_ac = mid_an = mid_hom = None
        mid_joint_available = _frequency_available(mid_ac, mid_an)
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
                cohort_details = {"ac": None, "an": None, "homozygote_count": None}
            elif not isinstance(cohort_details, dict):
                raise GnomADProviderError(f"gnoMAD GraphQL {cohort} result must be an object or null")
            cohort_code = f"{cohort.upper()}S"
            global_ac, global_an, global_hom = _graphql_counts(
                cohort_details, context=cohort, nullable=True
            )
            global_available = _frequency_available(global_ac, global_an)
            observations.append(
                PopulationObservationData(
                    population_level="GLOBAL",
                    population_code=f"GLOBAL_{cohort_code}",
                    population_label=f"gnomAD {cohort}s",
                    allele_count=global_ac,
                    allele_number=global_an,
                    allele_frequency=_af(global_ac, global_an),
                    homozygote_count=global_hom,
                    availability=("AVAILABLE" if global_available else "NOT_AVAILABLE"),
                    quality_status=("PASS" if global_available else "NO_OBSERVATION"),
                    source_record_id=source_record_id,
                    request_fingerprint=request_fingerprint,
                    response_sha256=response_sha256,
                    request_metadata=request_metadata,
                    observed_at=observed_at,
                )
            )
            populations = _graphql_populations(
                cohort_details.get("populations"), context=cohort
            )
            mid_pop = populations.get("mid")
            if mid_pop is not None:
                ac, an, hom = mid_pop
            else:
                ac = an = hom = None
            ancestry_available = _frequency_available(ac, an)
            observations.append(
                PopulationObservationData(
                    population_level="ANCESTRY",
                    population_code=f"MID_{cohort_code}",
                    population_label=f"Middle Eastern ({cohort}s)",
                    allele_count=ac,
                    allele_number=an,
                    allele_frequency=_af(ac, an),
                    homozygote_count=hom,
                    availability=("AVAILABLE" if ancestry_available else "NOT_AVAILABLE"),
                    quality_status=("PASS" if ancestry_available else "NO_ANCESTRY_OBSERVATION"),
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


def _graphql_counts(
    values: dict[str, Any], *, context: str, nullable: bool
) -> tuple[int | None, int | None, int | None]:
    counts = tuple(
        _graphql_count(values, field=field, context=context, nullable=nullable)
        for field in ("ac", "an", "homozygote_count")
    )
    ac, an, _homozygotes = counts
    if ac is not None and an is not None and ac > an:
        raise GnomADProviderError(
            f"gnoMAD GraphQL {context} allele count exceeds allele number"
        )
    return counts


def _graphql_count(
    values: dict[str, Any], *, field: str, context: str, nullable: bool
) -> int | None:
    if field not in values:
        raise GnomADProviderError(
            f"gnoMAD GraphQL {context} result is missing {field}"
        )
    value = values[field]
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GnomADProviderError(
            f"gnoMAD GraphQL {context}.{field} must be a non-negative integer"
        )
    return value


def _graphql_populations(
    populations: Any, *, context: str
) -> dict[str, tuple[int | None, int | None, int | None]]:
    if populations is None:
        return {}
    if not isinstance(populations, list):
        raise GnomADProviderError(
            f"gnoMAD GraphQL {context}.populations must be a list"
        )
    result: dict[str, tuple[int | None, int | None, int | None]] = {}
    for population in populations:
        if not isinstance(population, dict):
            raise GnomADProviderError(
                f"gnoMAD GraphQL {context}.populations must contain objects"
            )
        population_id = population.get("id")
        if not isinstance(population_id, str) or not population_id.strip():
            raise GnomADProviderError(
                f"gnoMAD GraphQL {context} population is missing a valid id"
            )
        key = population_id.casefold()
        if key in result:
            raise GnomADProviderError(
                f"gnoMAD GraphQL {context} contains duplicate population id {population_id!r}"
            )
        counts = _graphql_counts(
            population, context=f"{context}.population[{population_id}]", nullable=True
        )
        result[key] = counts
    return result


def _frequency_available(ac: int | None, an: int | None) -> bool:
    """A frequency is interpretable only when a positive allele number exists."""
    return ac is not None and ac >= 0 and an is not None and an > 0 and ac <= an


def _af(ac: int | None, an: int | None) -> float | None:
    if not _frequency_available(ac, an):
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
            ac = _array_count(
                info.get(f"AC{suffix}"),
                best["alt_index"],
                field=f"AC{suffix}",
            )
            an = _nonnegative_count(info.get(f"AN{suffix}"), field=f"AN{suffix}")
            af_text = _array_text(info.get(f"AF{suffix}"), best["alt_index"])
            af = _array_float(info.get(f"AF{suffix}"), best["alt_index"])
            hom = _array_count(
                info.get(f"nhomalt{suffix}"),
                best["alt_index"],
                field=f"nhomalt{suffix}",
            )
            if ac is not None and an is not None and ac > an:
                raise GnomADProviderError(
                    f"Local gnomAD {suffix or 'global'} allele count exceeds allele number"
                )
            # A source AF is not interpretable without a callable denominator.
            # Never expose it as a frequency when AN is missing or zero.
            if not _frequency_available(ac, an):
                af = None
            else:
                if af_text is not None:
                    _validate_source_af_matches_counts(
                        af_text, ac=ac, an=an, context=suffix or "global"
                    )
                # AC/AN is the exact frequency represented by these same
                # gnomAD VCF fields. Store that value rather than a rounded AF.
                af = _af(ac, an)
            availability = "AVAILABLE" if _frequency_available(ac, an) else "NOT_AVAILABLE"
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


def _array_text(value: str | None, index: int) -> str | None:
    if value is None:
        return None
    parts = value.split(",")
    if index >= len(parts):
        raise GnomADProviderError("Local gnomAD AF has no value for the requested alternate allele")
    raw_value = parts[index]
    return None if raw_value in {"", "."} else raw_value


def _validate_source_af_matches_counts(
    af_text: str, *, ac: int | None, an: int | None, context: str
) -> None:
    if ac is None or an is None or an <= 0:
        return
    try:
        reported = Decimal(af_text)
    except InvalidOperation as exc:
        raise GnomADProviderError("Local gnomAD AF is not a valid decimal") from exc
    if not reported.is_finite() or reported < 0 or reported > 1:
        raise GnomADProviderError("Local gnomAD AF must be a finite frequency between 0 and 1")
    expected = Decimal(ac) / Decimal(an)
    rounding_tolerance = Decimal(5).scaleb(reported.as_tuple().exponent - 1)
    if abs(reported - expected) > rounding_tolerance:
        raise GnomADProviderError(
            f"Local gnomAD {context} AF is inconsistent with AC/AN at the source precision"
        )


def _nonnegative_count(value: str | None, *, field: str) -> int | None:
    if value in (None, "", "."):
        return None
    digits = value.removeprefix("+")
    if not digits or not digits.isascii() or not digits.isdigit():
        raise GnomADProviderError(
            f"Local gnomAD {field} must be a non-negative integer or missing"
        )
    return int(digits)


def _array_count(value: str | None, index: int, *, field: str) -> int | None:
    if value in (None, "", "."):
        return None
    parts = value.split(",")
    if index >= len(parts):
        raise GnomADProviderError(
            f"Local gnomAD {field} has no value for the requested alternate allele"
        )
    return _nonnegative_count(parts[index], field=field)


def _array_float(value: str | None, index: int) -> float | None:
    raw_value = _array_text(value, index)
    if raw_value is None:
        return None
    try:
        parsed = float(raw_value)
    except ValueError as exc:
        raise GnomADProviderError("Local gnomAD AF must be a finite frequency") from exc
    if not math.isfinite(parsed) or not 0 <= parsed <= 1:
        raise GnomADProviderError("Local gnomAD AF must be between zero and one")
    return parsed
