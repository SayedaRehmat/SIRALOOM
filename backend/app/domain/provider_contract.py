"""Executable provider contract for governed scientific resources.

The contract is deliberately more than a provider name or endpoint. Every
scientific provider must expose the complete execution lifecycle:

1. validate its governed execution contract;
2. prepare a request from canonical SIRALOOM inputs;
3. execute against the qualified resource;
4. validate the raw response;
5. normalize it into SIRALOOM's domain representation;
6. map the normalized observation to evidence;
7. emit provenance and a deterministic execution fingerprint.

A provider is not production-ready merely because it can make an HTTP request.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from backend.app.domain.resource_source_contract import ResourceExecutionContract
from backend.app.domain.resource_capabilities import ResourceCapability


class ProviderContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderRequest:
    operation: str
    payload: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderRawResult:
    operation: str
    payload: Any
    response_sha256: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderNormalizedResult:
    operation: str
    observations: tuple[dict[str, Any], ...]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderEvidenceResult:
    evidence: tuple[dict[str, Any], ...]
    metadata: dict[str, Any] = field(default_factory=dict)


class ScientificResourceProvider(ABC):
    provider_id: str
    provider_version: str
    capabilities: frozenset[ResourceCapability]
    supported_builds: frozenset[str]
    trial_only: bool = False

    @abstractmethod
    def validate_execution_contract(self, contract: ResourceExecutionContract) -> None:
        ...

    @abstractmethod
    def prepare_request(self, operation: str, inputs: dict[str, Any]) -> ProviderRequest:
        ...

    @abstractmethod
    def execute(self, request: ProviderRequest) -> ProviderRawResult:
        ...

    @abstractmethod
    def validate_response(self, result: ProviderRawResult) -> None:
        ...

    @abstractmethod
    def normalize_result(
        self,
        result: ProviderRawResult,
        *,
        inputs: dict[str, Any],
    ) -> ProviderNormalizedResult:
        ...

    @abstractmethod
    def to_evidence(
        self,
        normalized: ProviderNormalizedResult,
        *,
        inputs: dict[str, Any],
    ) -> ProviderEvidenceResult:
        ...

    def health_check(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "status": "IMPLEMENTED",
            "capabilities": sorted(str(x) for x in self.capabilities),
        }
