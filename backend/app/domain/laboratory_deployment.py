"""Versioned contract for deploying SIRALOOM in a laboratory-owned environment.

This contract describes infrastructure SIRALOOM requires; it does not provision
that infrastructure. The same scientific workflow runs in trial and laboratory
modes. A laboratory deployment removes trial application quotas and instead
binds execution to laboratory-owned compute, storage, databases, queues, and
qualified scientific resources.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Literal


LABORATORY_DEPLOYMENT_CONTRACT_VERSION = "1"

AccessMode = Literal["LOCAL", "OBJECT_STORAGE", "API"]


@dataclass(frozen=True)
class DeploymentServiceRequirement:
    """A runtime service that must be reachable by the SIRALOOM deployment."""

    name: str
    purpose: str
    required: bool = True
    externally_managed: bool = False


@dataclass(frozen=True)
class DeploymentStorageRequirement:
    """Durable storage contract for artifacts and worker workspace."""

    name: str
    purpose: str
    access_mode: AccessMode
    durable: bool = True
    minimum_free_bytes: int = 0


@dataclass(frozen=True)
class LaboratoryDeploymentContract:
    """Machine-readable minimum contract for a laboratory installation."""

    contract_version: str
    deployment_profile_type: str
    services: tuple[DeploymentServiceRequirement, ...]
    storage: tuple[DeploymentStorageRequirement, ...]
    required_resource_capabilities: tuple[str, ...]
    application_file_size_limit: int | None
    application_analysis_count_limit: int | None
    requires_tls_at_user_boundary: bool
    requires_durable_database: bool
    requires_durable_artifact_storage: bool

    @property
    def is_laboratory(self) -> bool:
        return self.deployment_profile_type == "LABORATORY"

    def validate(self) -> None:
        if self.contract_version.strip() == "":
            raise ValueError("contract_version is required")
        if self.deployment_profile_type != "LABORATORY":
            raise ValueError("laboratory deployment contract requires LABORATORY profile")
        if not self.services:
            raise ValueError("at least one runtime service requirement is required")
        if not self.storage:
            raise ValueError("at least one storage requirement is required")
        if not self.required_resource_capabilities:
            raise ValueError("at least one scientific resource capability is required")
        if self.application_file_size_limit is not None:
            raise ValueError("laboratory deployment must not define an application file-size ceiling")
        if self.application_analysis_count_limit is not None:
            raise ValueError("laboratory deployment must not define an application analysis-count ceiling")
        if not self.requires_durable_database:
            raise ValueError("laboratory deployment requires durable database storage")
        if not self.requires_durable_artifact_storage:
            raise ValueError("laboratory deployment requires durable artifact storage")
        if not self.requires_tls_at_user_boundary:
            raise ValueError("laboratory deployment requires TLS at the user boundary")
        for item in self.services:
            if not item.name.strip() or not item.purpose.strip():
                raise ValueError("service requirements require name and purpose")
        for item in self.storage:
            if not item.name.strip() or not item.purpose.strip():
                raise ValueError("storage requirements require name and purpose")
            if item.minimum_free_bytes < 0:
                raise ValueError("minimum_free_bytes cannot be negative")

    def snapshot(self) -> dict:
        """Return deterministic, audit-safe deployment contract data."""
        self.validate()
        return {
            "contract_version": self.contract_version,
            "deployment_profile_type": self.deployment_profile_type,
            "services": [asdict(item) for item in self.services],
            "storage": [asdict(item) for item in self.storage],
            "required_resource_capabilities": list(self.required_resource_capabilities),
            "application_file_size_limit": self.application_file_size_limit,
            "application_analysis_count_limit": self.application_analysis_count_limit,
            "requires_tls_at_user_boundary": self.requires_tls_at_user_boundary,
            "requires_durable_database": self.requires_durable_database,
            "requires_durable_artifact_storage": self.requires_durable_artifact_storage,
        }

    @property
    def contract_hash(self) -> str:
        material = json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return sha256(material).hexdigest()


def laboratory_deployment_contract() -> LaboratoryDeploymentContract:
    """Return the canonical v1 laboratory deployment contract.

    PostgreSQL/Redis are externally managed by default at the contract level so
    the deployment package can support both lab-owned infrastructure and the
    bundled Docker Compose installation that will be added later.
    """
    return LaboratoryDeploymentContract(
        contract_version=LABORATORY_DEPLOYMENT_CONTRACT_VERSION,
        deployment_profile_type="LABORATORY",
        services=(
            DeploymentServiceRequirement("siraloom-api", "FastAPI application API"),
            DeploymentServiceRequirement("siraloom-worker", "Durable Celery workflow execution"),
            DeploymentServiceRequirement("postgresql", "Durable transactional application state", externally_managed=True),
            DeploymentServiceRequirement("redis", "Celery task transport", externally_managed=True),
        ),
        storage=(
            DeploymentStorageRequirement(
                "artifact-storage",
                "Durable uploaded, normalized, report, and provenance artifacts",
                "LOCAL",
            ),
            DeploymentStorageRequirement(
                "worker-workspace",
                "Temporary worker execution workspace and bounded staging",
                "LOCAL",
                durable=False,
            ),
        ),
        required_resource_capabilities=(
            "REFERENCE_PACKAGE",
            "ANNOTATION_ENGINE",
            "POPULATION",
            "ACMG_RULE_SPECIFICATION",
        ),
        application_file_size_limit=None,
        application_analysis_count_limit=None,
        requires_tls_at_user_boundary=True,
        requires_durable_database=True,
        requires_durable_artifact_storage=True,
    )
