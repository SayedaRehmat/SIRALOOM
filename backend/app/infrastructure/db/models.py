from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, Text, JSON, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.infrastructure.db.base import Base

def now() -> datetime:
    return datetime.now(timezone.utc)

class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    external_identifier: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"))
    external_subject: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class OrganizationMembership(Base):
    """Server-authoritative organization membership for an authenticated subject."""
    __tablename__ = "organization_memberships"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)

class OrganizationEntitlement(Base):
    """Licensing/usage envelope for an organization: TRIAL, EVALUATION, PAID, ENTERPRISE, ON_PREMISE.

    Absence of a row for an organization means no entitlement restrictions are enforced
    (this keeps existing/paid organizations unaffected). A row is only created explicitly,
    e.g. by the free-trial onboarding path.
    """
    __tablename__ = "organization_entitlements"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, unique=True)
    plan: Mapped[str] = mapped_column(Text, nullable=False, default="TRIAL")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    max_analyses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    analyses_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_vcf_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class ResourceDeploymentProfile(Base):
    """Organization-level policy selecting the governed resource environment.

    The workflow is shared by trial and laboratory deployments. This record
    selects how resource identities are resolved; it does not itself approve
    scientific resources.
    """
    __tablename__ = "resource_deployment_profiles"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, unique=True
    )
    profile_type: Mapped[str] = mapped_column(Text, nullable=False)
    profile_version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"))
    case_identifier: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    clinical_context: Mapped[dict] = mapped_column(JSON, default=dict)
    language: Mapped[str] = mapped_column(Text, default="en")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (UniqueConstraint("organization_id", "case_identifier"),)

class Specimen(Base):
    __tablename__ = "specimens"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id"))
    specimen_identifier: Mapped[str | None] = mapped_column(Text)
    specimen_type: Mapped[str | None] = mapped_column(Text)
    collection_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Assay(Base):
    __tablename__ = "assays"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    assay_type: Mapped[str] = mapped_column(Text)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Analysis(Base):
    __tablename__ = "analyses"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id"))
    parent_analysis_id: Mapped[UUID | None] = mapped_column(ForeignKey("analyses.id"))
    assay_id: Mapped[UUID | None] = mapped_column(ForeignKey("assays.id"))
    analysis_type: Mapped[str] = mapped_column(Text)
    workflow_id: Mapped[str] = mapped_column(Text)
    workflow_version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    queue_task_id: Mapped[str | None] = mapped_column(Text)
    reference_build: Mapped[str] = mapped_column(Text)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    analysis_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index(
            "uq_analyses_parent_version",
            "parent_analysis_id",
            "analysis_version",
            unique=True,
            sqlite_where=text("parent_analysis_id IS NOT NULL"),
            postgresql_where=text("parent_analysis_id IS NOT NULL"),
        ),
    )

class AnalysisDispatch(Base):
    """Durable publication intent for an analysis execution.

    The row is created in the same transaction that moves an analysis to
    QUEUED. Publication to Celery is deliberately outside that transaction;
    the dispatcher can retry a durable PENDING intent without creating another
    Analysis row. The execution fence remains authoritative at the worker.
    """
    __tablename__ = "analysis_dispatches"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    dispatch_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    task_id: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (
        UniqueConstraint("analysis_id", "dispatch_generation"),
        Index("ix_analysis_dispatches_status", "status"),
    )


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[UUID | None] = mapped_column(ForeignKey("analyses.id"))
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id"))
    artifact_type: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(Text)
    storage_uri: Mapped[str] = mapped_column(Text)
    genome_build: Mapped[str | None] = mapped_column(Text)
    specimen_id: Mapped[UUID | None] = mapped_column(ForeignKey("specimens.id"))
    paired_artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    validation_status: Mapped[str] = mapped_column(Text, default="PENDING")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class TechnicalQCObservation(Base):
    __tablename__ = "technical_qc_observations"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"))
    artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    metric_name: Mapped[str] = mapped_column(Text)
    metric_value: Mapped[float | None] = mapped_column(Float)
    metric_unit: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="NOT_ASSESSED")
    source: Mapped[str] = mapped_column(Text, default="LAB_QC")
    source_version: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class QCAssessment(Base):
    __tablename__ = "qc_assessments"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"))
    assay_id: Mapped[UUID | None] = mapped_column(ForeignKey("assays.id"))
    status: Mapped[str] = mapped_column(Text)
    profile_name: Mapped[str | None] = mapped_column(Text)
    profile_version: Mapped[str | None] = mapped_column(Text)
    metrics_json: Mapped[dict] = mapped_column("metrics", JSON, default=dict)
    evaluated_rules: Mapped[list] = mapped_column(JSON, default=list)
    gate_status: Mapped[str] = mapped_column(Text, default="NOT_ASSESSED")
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ToolRun(Base):
    __tablename__ = "tool_runs"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"))
    tool_name: Mapped[str] = mapped_column(Text)
    tool_version: Mapped[str] = mapped_column(Text)
    container_digest: Mapped[str | None] = mapped_column(Text)
    command_fingerprint: Mapped[str | None] = mapped_column(Text)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_code: Mapped[int | None] = mapped_column(Integer)
    stdout_artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    stderr_artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class AnalysisPartition(Base):
    __tablename__ = "analysis_partitions"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"))
    step_id: Mapped[str] = mapped_column(Text)
    partition_key: Mapped[str] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer)
    record_start: Mapped[int] = mapped_column(BigInteger)
    record_end: Mapped[int] = mapped_column(BigInteger)
    variant_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(Text, default="PENDING")
    input_artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    resource_class: Mapped[str] = mapped_column(Text, default="STANDARD")
    cpu_request: Mapped[float] = mapped_column(Float, default=1.0)
    memory_mb: Mapped[int] = mapped_column(Integer, default=1024)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(Text)
    # Unique fencing token for the current lease generation. Worker identity alone
    # is not sufficient because the same workflow worker can reclaim an expired
    # lease after a timeout; stale workers must not be able to mutate the new lease.
    lease_token: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (UniqueConstraint("analysis_id", "step_id", "partition_key"),)

class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"))
    step_id: Mapped[str] = mapped_column(Text)
    step_order: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_artifacts: Mapped[list] = mapped_column(JSON, default=list)
    output_artifacts: Mapped[list] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (UniqueConstraint("analysis_id", "step_id"),)

class Variant(Base):
    __tablename__ = "variants"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    genome_build: Mapped[str] = mapped_column(Text)
    chromosome: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(BigInteger)
    reference: Mapped[str] = mapped_column(Text)
    alternate: Mapped[str] = mapped_column(Text)
    normalization_status: Mapped[str] = mapped_column(Text)
    canonical_key: Mapped[str] = mapped_column(Text, unique=True)
    identifiers: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("genome_build", "chromosome", "position", "reference", "alternate"),)

class Annotation(Base):
    __tablename__ = "annotations"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    variant_id: Mapped[UUID] = mapped_column(ForeignKey("variants.id"))
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"))
    provider_name: Mapped[str] = mapped_column(Text)
    provider_version: Mapped[str] = mapped_column(Text)
    resource_id: Mapped[UUID | None] = mapped_column(ForeignKey("resources.id"))
    resource_name: Mapped[str | None] = mapped_column(Text)
    resource_version: Mapped[str | None] = mapped_column(Text)
    request_fingerprint: Mapped[str | None] = mapped_column(Text)
    response_sha256: Mapped[str | None] = mapped_column(Text)
    request_metadata: Mapped[dict] = mapped_column("request_metadata", JSON, default=dict)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        # A governed annotation observation is unique for one analysis, canonical
        # variant, provider implementation, and exact registered resource release.
        # The partial predicate preserves compatibility with legacy observations
        # that predate resource provenance and have resource_id=NULL; new workflow
        # writes always carry a governed resource_id.
        Index(
            "uq_annotations_observation_identity",
            "analysis_id",
            "variant_id",
            "provider_name",
            "provider_version",
            "resource_id",
            "resource_version",
            unique=True,
            sqlite_where=text("resource_id IS NOT NULL"),
            postgresql_where=text("resource_id IS NOT NULL"),
        ),
    )

class Resource(Base):
    __tablename__ = "resources"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    name: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    resource_type: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    genome_build: Mapped[str | None] = mapped_column(Text)
    access_method: Mapped[str] = mapped_column(Text)
    license_text: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    population_definition: Mapped[dict | None] = mapped_column(JSON)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ResourceDiscovery(Base):
    """Durable identity and provenance for a discovered resource release."""

    __tablename__ = "resource_discoveries"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    publisher: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_source_url: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_url: Mapped[str] = mapped_column(Text, nullable=False)
    release_identity: Mapped[str] = mapped_column(Text, nullable=False)
    access_mode: Mapped[str] = mapped_column(Text, nullable=False)
    license_status: Mapped[str] = mapped_column(Text, nullable=False)
    license_url: Mapped[str | None] = mapped_column(Text)
    terms_url: Mapped[str | None] = mapped_column(Text)
    checksum_status: Mapped[str] = mapped_column(Text, nullable=False)
    expected_sha256: Mapped[str | None] = mapped_column(Text)
    expected_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    authority_evidence_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="DISCOVERED")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    __table_args__ = (
        UniqueConstraint("resource_id", "release_identity", "artifact_url"),
    )


class ResourceStaging(Base):
    """Durable staging/integrity state for a concrete resource release artifact."""

    __tablename__ = "resource_stagings"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    resource_version: Mapped[str] = mapped_column(Text, nullable=False)
    staging_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_uri: Mapped[str] = mapped_column(Text, nullable=False)
    destination_uri: Mapped[str] = mapped_column(Text, nullable=False)
    storage_backend: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="DISCOVERED")
    expected_sha256: Mapped[str | None] = mapped_column(Text)
    observed_sha256: Mapped[str | None] = mapped_column(Text)
    expected_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    observed_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    __table_args__ = (
        UniqueConstraint("resource_id", "resource_version", "staging_key"),
    )


class ResourceExecutionRecord(Base):
    """Immutable runtime snapshot of a governed resource execution."""

    __tablename__ = "resource_execution_records"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    step_id: Mapped[str] = mapped_column(Text, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    batch_key: Mapped[str | None] = mapped_column(Text)
    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    requested_resource_id: Mapped[UUID | None] = mapped_column(ForeignKey("resources.id"))
    fallback_resource_id: Mapped[UUID | None] = mapped_column(ForeignKey("resources.id"))
    qualification_id: Mapped[UUID] = mapped_column(ForeignKey("resource_qualifications.id"), nullable=False)
    qualification_version: Mapped[str] = mapped_column(Text, nullable=False)
    resource_version: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_version: Mapped[str] = mapped_column(Text, nullable=False)
    access_method: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    dataset: Mapped[str | None] = mapped_column(Text)
    contract_hash: Mapped[str] = mapped_column(Text, nullable=False)
    contract_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="STARTED")
    request_fingerprint: Mapped[str | None] = mapped_column(Text)
    response_sha256: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ResourceQualification(Base):
    __tablename__ = "resource_qualifications"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    qualification_version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    checks_json: Mapped[dict] = mapped_column("checks", JSON, default=dict)
    qualified_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("resource_id", "qualification_version"),)

class ResourceApproval(Base):
    """Organization-scoped adoption decision for a technically qualified resource."""
    __tablename__ = "resource_approvals"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    qualification_id: Mapped[UUID] = mapped_column(ForeignKey("resource_qualifications.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (
        UniqueConstraint("resource_id", "organization_id", "qualification_id"),
    )


class ResourceApprovalAction(Base):
    """Append-only audit trail for organization resource adoption decisions."""
    __tablename__ = "resource_approval_actions"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    approval_id: Mapped[UUID] = mapped_column(ForeignKey("resource_approvals.id"), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    before_status: Mapped[str] = mapped_column(Text, nullable=False)
    after_status: Mapped[str] = mapped_column(Text, nullable=False)
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        UniqueConstraint("approval_id", "resulting_version"),
    )


class OrganizationResourceBinding(Base):
    """The resource version currently adopted for one laboratory organization."""
    __tablename__ = "organization_resource_bindings"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    resource_name: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    genome_build: Mapped[str | None] = mapped_column(Text)
    identity_key: Mapped[str] = mapped_column(Text, nullable=False)
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    bound_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    previous_resource_id: Mapped[UUID | None] = mapped_column(ForeignKey("resources.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint("organization_id", "identity_key"),
    )


class PopulationObservation(Base):
    __tablename__ = "population_observations"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"))
    variant_id: Mapped[UUID] = mapped_column(ForeignKey("variants.id"))
    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"))
    population_level: Mapped[str] = mapped_column(Text)
    population_code: Mapped[str] = mapped_column(Text)
    population_label: Mapped[str] = mapped_column(Text)
    allele_count: Mapped[int | None] = mapped_column(BigInteger)
    allele_number: Mapped[int | None] = mapped_column(BigInteger)
    allele_frequency: Mapped[float | None] = mapped_column(Float)
    homozygote_count: Mapped[int | None] = mapped_column(BigInteger)
    availability: Mapped[str] = mapped_column(Text)
    quality_status: Mapped[str | None] = mapped_column(Text)
    source_record_id: Mapped[str | None] = mapped_column(Text)
    request_fingerprint: Mapped[str | None] = mapped_column(Text)
    response_sha256: Mapped[str | None] = mapped_column(Text)
    request_metadata: Mapped[dict] = mapped_column("request_metadata", JSON, default=dict)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("analysis_id", "variant_id", "resource_id", "population_code"),)

class PhenotypeObservation(Base):
    __tablename__ = "phenotype_observations"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id"))
    analysis_id: Mapped[UUID | None] = mapped_column(ForeignKey("analyses.id"))
    hpo_id: Mapped[str] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(Text)
    present: Mapped[bool] = mapped_column(default=True)
    onset: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="CLINICAL_INPUT")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("case_id", "analysis_id", "hpo_id", "present"),)

class PedigreeMember(Base):
    __tablename__ = "pedigree_members"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id"))
    member_identifier: Mapped[str] = mapped_column(Text)
    relationship_to_proband: Mapped[str | None] = mapped_column(Text)
    sex: Mapped[str | None] = mapped_column(Text)
    affected_status: Mapped[str] = mapped_column(Text, default="UNKNOWN")
    is_proband: Mapped[bool] = mapped_column(default=False)
    sampled: Mapped[bool] = mapped_column(default=False)
    specimen_id: Mapped[UUID | None] = mapped_column(ForeignKey("specimens.id"))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("case_id", "member_identifier"),)

class PedigreeRelationship(Base):
    __tablename__ = "pedigree_relationships"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id"))
    parent_member_id: Mapped[UUID] = mapped_column(ForeignKey("pedigree_members.id"))
    child_member_id: Mapped[UUID] = mapped_column(ForeignKey("pedigree_members.id"))
    relationship_type: Mapped[str] = mapped_column(Text, default="PARENT_CHILD")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("case_id", "parent_member_id", "child_member_id"),)

class SegregationObservation(Base):
    __tablename__ = "segregation_observations"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"))
    variant_id: Mapped[UUID] = mapped_column(ForeignKey("variants.id"))
    pedigree_member_id: Mapped[UUID] = mapped_column(ForeignKey("pedigree_members.id"))
    genotype: Mapped[str | None] = mapped_column(Text)
    zygosity: Mapped[str | None] = mapped_column(Text)
    phase: Mapped[str | None] = mapped_column(Text)
    allele_observed: Mapped[str | None] = mapped_column(Text)
    phenotype_status: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="HUMAN_REVIEW")
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("analysis_id", "variant_id", "pedigree_member_id"),)

class InheritanceAssessment(Base):
    __tablename__ = "inheritance_assessments"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"))
    variant_id: Mapped[UUID] = mapped_column(ForeignKey("variants.id"))
    model: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, default=0)
    rationale: Mapped[str] = mapped_column(Text)
    observation_fingerprint: Mapped[str] = mapped_column(Text)
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("analysis_id", "variant_id", "model", "observation_fingerprint"),)

class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    variant_id: Mapped[UUID] = mapped_column(ForeignKey("variants.id"))
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"))
    evidence_type: Mapped[str] = mapped_column(Text)
    statement: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(Text)
    source_version: Mapped[str | None] = mapped_column(Text)
    resource_id: Mapped[UUID | None] = mapped_column(ForeignKey("resources.id"))
    source_record_id: Mapped[str | None] = mapped_column(Text)
    request_fingerprint: Mapped[str | None] = mapped_column(Text)
    response_sha256: Mapped[str | None] = mapped_column(Text)
    request_metadata: Mapped[dict] = mapped_column("request_metadata", JSON, default=dict)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observation_ids: Mapped[list] = mapped_column(JSON, default=list)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by_type: Mapped[str] = mapped_column(Text)
    created_by_id: Mapped[str] = mapped_column(Text)
    evidence_fingerprint: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("analysis_id", "evidence_fingerprint"),)


class ACMGSourceAssertion(Base):
    """Source-level ACMG/ClinGen criterion assertion preserved separately from SIRALOOM classification."""
    __tablename__ = "acmg_source_assertions"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    variant_id: Mapped[UUID] = mapped_column(ForeignKey("variants.id"), nullable=False)
    evidence_id: Mapped[UUID] = mapped_column(ForeignKey("evidence.id"), nullable=False)
    criterion: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    strength: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(Text)
    source_version: Mapped[str | None] = mapped_column(Text)
    source_record_id: Mapped[str | None] = mapped_column(Text)
    source_classification: Mapped[str | None] = mapped_column(Text)
    condition: Mapped[str | None] = mapped_column(Text)
    gene: Mapped[str | None] = mapped_column(Text)
    mondo_id: Mapped[str | None] = mapped_column(Text)
    expert_panel: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    pmids: Mapped[list] = mapped_column(JSON, default=list)
    source_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    assertion_fingerprint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("analysis_id", "evidence_id", "criterion"),)


class ClinGenSpecification(Base):
    __tablename__ = "clingen_specifications"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    specification_id: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text, default="ClinGen")
    framework: Mapped[str] = mapped_column(Text)
    source_iri: Mapped[str | None] = mapped_column(Text)
    modified_at: Mapped[str | None] = mapped_column(Text)
    gene_scope: Mapped[list] = mapped_column(JSON, default=list)
    disease_scope: Mapped[list] = mapped_column(JSON, default=list)
    criteria: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    request_fingerprint: Mapped[str | None] = mapped_column(Text)
    response_sha256: Mapped[str | None] = mapped_column(Text)
    request_metadata: Mapped[dict] = mapped_column("request_metadata", JSON, default=dict)
    validated_for_automation: Mapped[bool] = mapped_column(default=False)
    validation_status: Mapped[str] = mapped_column(Text, default="UNVALIDATED")
    validated_by: Mapped[str | None] = mapped_column(Text)
    validation_reason: Mapped[str | None] = mapped_column(Text)
    validation_reference: Mapped[str | None] = mapped_column(Text)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("specification_id", "version"),)

class ACMGAssessment(Base):
    __tablename__ = "acmg_assessments"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    variant_id: Mapped[UUID] = mapped_column(ForeignKey("variants.id"))
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"))
    framework_name: Mapped[str] = mapped_column(Text)
    framework_version: Mapped[str] = mapped_column(Text)
    specification_provider: Mapped[str | None] = mapped_column(Text)
    specification_id: Mapped[str | None] = mapped_column(Text)
    specification_version: Mapped[str | None] = mapped_column(Text)
    criterion: Mapped[str] = mapped_column(Text)
    automated_assessment: Mapped[dict] = mapped_column(JSON, default=dict)
    reviewed_assessment: Mapped[dict | None] = mapped_column(JSON)
    final_assessment: Mapped[dict | None] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(Text)
    review_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (UniqueConstraint("variant_id", "analysis_id", "criterion"),)

class Classification(Base):
    __tablename__ = "classifications"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    variant_id: Mapped[UUID] = mapped_column(ForeignKey("variants.id"))
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"))
    framework_name: Mapped[str] = mapped_column(Text)
    framework_version: Mapped[str] = mapped_column(Text)
    specification_provider: Mapped[str | None] = mapped_column(Text)
    specification_id: Mapped[str | None] = mapped_column(Text)
    specification_version: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str] = mapped_column(Text)
    criterion_ids: Mapped[list] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    state: Mapped[str] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_classification_id: Mapped[UUID | None] = mapped_column(ForeignKey("classifications.id"))
    review_version: Mapped[int] = mapped_column(Integer, default=0)
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class ReviewAction(Base):
    __tablename__ = "review_actions"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id"))
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"))
    variant_id: Mapped[UUID | None] = mapped_column(ForeignKey("variants.id"))
    reviewer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    action_type: Mapped[str] = mapped_column(Text)
    sequence_number: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    before_state: Mapped[dict | None] = mapped_column(JSON)
    after_state: Mapped[dict | None] = mapped_column(JSON)
    expected_version: Mapped[int] = mapped_column(Integer, default=0)
    resulting_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("analysis_id", "variant_id", "sequence_number"),)

class ReportabilityDecision(Base):
    __tablename__ = "reportability_decisions"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"))
    variant_id: Mapped[UUID] = mapped_column(ForeignKey("variants.id"))
    classification_id: Mapped[UUID] = mapped_column(ForeignKey("classifications.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_decision_id: Mapped[UUID | None] = mapped_column(ForeignKey("reportability_decisions.id"))
    policy_name: Mapped[str] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(Text)
    disposition: Mapped[str] = mapped_column(Text)
    priority_score: Mapped[int] = mapped_column(Integer, default=0)
    priority_band: Mapped[str] = mapped_column(Text, default="ROUTINE")
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(Text)
    review_version: Mapped[int] = mapped_column(Integer, default=0)
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class ConfirmationRecord(Base):
    __tablename__ = "confirmation_records"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"))
    variant_id: Mapped[UUID] = mapped_column(ForeignKey("variants.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_record_id: Mapped[UUID | None] = mapped_column(ForeignKey("confirmation_records.id"))
    required: Mapped[bool] = mapped_column(default=False)
    method: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="NOT_REQUIRED")
    result: Mapped[str | None] = mapped_column(Text)
    laboratory: Mapped[str | None] = mapped_column(Text)
    accession: Mapped[str | None] = mapped_column(Text)
    performed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class FollowUpPlan(Base):
    __tablename__ = "follow_up_plans"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id"))
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"))
    variant_id: Mapped[UUID | None] = mapped_column(ForeignKey("variants.id"))
    action_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="PLANNED")
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responsible_role: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    completed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class SecondaryFindingDecision(Base):
    __tablename__ = "secondary_finding_decisions"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"))
    variant_id: Mapped[UUID] = mapped_column(ForeignKey("variants.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_decision_id: Mapped[UUID | None] = mapped_column(ForeignKey("secondary_finding_decisions.id"))
    policy_name: Mapped[str] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(Text)
    eligibility: Mapped[str] = mapped_column(Text, default="REVIEW")
    consent_status: Mapped[str] = mapped_column(Text, default="NOT_DOCUMENTED")
    disposition: Mapped[str] = mapped_column(Text, default="REVIEW")
    status: Mapped[str] = mapped_column(Text, default="DRAFT")
    rationale: Mapped[str | None] = mapped_column(Text)
    gene_disease_context: Mapped[dict] = mapped_column(JSON, default=dict)
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("analysis_id", "variant_id", "version"),)

class Report(Base):
    __tablename__ = "reports"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id"))
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"))
    report_version: Mapped[int] = mapped_column(Integer)
    supersedes_report_id: Mapped[UUID | None] = mapped_column(ForeignKey("reports.id"))
    language: Mapped[str] = mapped_column(Text)
    report_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    signed_artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    signed_sha256: Mapped[str | None] = mapped_column(Text)
    signout_reason: Mapped[str | None] = mapped_column(Text)
    content_json: Mapped[dict] = mapped_column(JSON, default=dict)
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CaseExport(Base):
    __tablename__ = "case_exports"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id"))
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(Text)
    include_artifacts: Mapped[bool] = mapped_column(default=True)
    include_reports: Mapped[bool] = mapped_column(default=True)
    include_evidence: Mapped[bool] = mapped_column(default=True)
    include_audit: Mapped[bool] = mapped_column(default=True)
    include_provenance: Mapped[bool] = mapped_column(default=True)
    artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    queue_task_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CaseExportDispatch(Base):
    """Durable publication intent for one case-export execution."""
    __tablename__ = "case_export_dispatches"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    case_export_id: Mapped[UUID] = mapped_column(
        ForeignKey("case_exports.id"), nullable=False
    )
    dispatch_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    task_id: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (
        UniqueConstraint("case_export_id", "dispatch_generation"),
        Index("ix_case_export_dispatches_status", "status"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    event_version: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text)
    case_id: Mapped[UUID | None] = mapped_column(ForeignKey("cases.id"))
    analysis_id: Mapped[UUID | None] = mapped_column(ForeignKey("analyses.id"))
    actor_type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str] = mapped_column(Text)
    subject_type: Mapped[str | None] = mapped_column(Text)
    subject_id: Mapped[str | None] = mapped_column(Text)
    operation: Mapped[str | None] = mapped_column(Text)
    before_state: Mapped[dict | None] = mapped_column(JSON)
    after_state: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    input_artifacts: Mapped[list] = mapped_column(JSON, default=list)
    output_artifacts: Mapped[list] = mapped_column(JSON, default=list)
    software: Mapped[dict] = mapped_column(JSON, default=dict)
    workflow: Mapped[dict] = mapped_column(JSON, default=dict)
    resource_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    previous_event_hash: Mapped[str | None] = mapped_column(Text)
    event_hash: Mapped[str | None] = mapped_column(Text, unique=True)

class Installation(Base):
    __tablename__ = "installations"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"))
    installation_fingerprint: Mapped[str] = mapped_column(Text, unique=True)
    hostname: Mapped[str | None] = mapped_column(Text)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_check_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text)

class License(Base):
    __tablename__ = "licenses"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"))
    license_key_id: Mapped[str] = mapped_column(Text, unique=True)
    plan: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    max_installations: Mapped[int] = mapped_column(Integer)
    max_concurrent_jobs: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class LicenseEntitlement(Base):
    __tablename__ = "license_entitlements"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    license_id: Mapped[UUID] = mapped_column(ForeignKey("licenses.id"))
    installation_id: Mapped[UUID] = mapped_column(ForeignKey("installations.id"))
    lease_version: Mapped[int] = mapped_column(Integer)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    features: Mapped[list] = mapped_column(JSON, default=list)
    signed_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    signature: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AnalysisResourceSnapshot(Base):
    __tablename__ = "analysis_resource_snapshots"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(ForeignKey("resources.id"), nullable=True)
    resource_kind: Mapped[str] = mapped_column(Text, nullable=False)
    resource_name: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str | None] = mapped_column(Text)
    genome_build: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        UniqueConstraint("analysis_id", "resource_kind", "resource_name", "version", "checksum"),
    )


class ReanalysisChangeEvent(Base):
    __tablename__ = "reanalysis_change_events"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    change_fingerprint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(ForeignKey("resources.id"))
    trigger_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_kind: Mapped[str] = mapped_column(Text, nullable=False)
    resource_name: Mapped[str] = mapped_column(Text, nullable=False)
    previous_version: Mapped[str | None] = mapped_column(Text)
    new_version: Mapped[str | None] = mapped_column(Text)
    previous_checksum: Mapped[str | None] = mapped_column(Text)
    new_checksum: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class ReanalysisCandidate(Base):
    __tablename__ = "reanalysis_candidates"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id"), nullable=False)
    parent_analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    change_event_id: Mapped[UUID | None] = mapped_column(ForeignKey("reanalysis_change_events.id"))
    trigger_type: Mapped[str] = mapped_column(Text, nullable=False)
    earliest_affected_step: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    child_analysis_id: Mapped[UUID | None] = mapped_column(ForeignKey("analyses.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("parent_analysis_id", "change_event_id"),
    )


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    notification_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="UNREAD")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    case_id: Mapped[UUID | None] = mapped_column(ForeignKey("cases.id"))
    analysis_id: Mapped[UUID | None] = mapped_column(ForeignKey("analyses.id"))
    candidate_id: Mapped[UUID | None] = mapped_column(ForeignKey("reanalysis_candidates.id"))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowDecisionRecord(Base):
    """Immutable durable record of the decision taken for one workflow outcome."""
    __tablename__ = "workflow_decision_records"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id"), nullable=False)
    step_id: Mapped[str] = mapped_column(Text, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outcome_kind: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    retryable: Mapped[bool] = mapped_column(nullable=False, default=False)
    fallback_allowed: Mapped[bool] = mapped_column(nullable=False, default=False)
    lab_action_required: Mapped[bool] = mapped_column(nullable=False, default=False)
    resource_id: Mapped[UUID | None] = mapped_column(ForeignKey("resources.id"))
    fallback_resource_id: Mapped[UUID | None] = mapped_column(ForeignKey("resources.id"))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)