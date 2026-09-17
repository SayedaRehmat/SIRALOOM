from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, Text, JSON, UniqueConstraint
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

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
    resource_name: Mapped[str | None] = mapped_column(Text)
    resource_version: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Resource(Base):
    __tablename__ = "resources"
    id: Mapped[UUID] = mapped_column(primary_key=True)
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
    source_record_id: Mapped[str | None] = mapped_column(Text)
    observation_ids: Mapped[list] = mapped_column(JSON, default=list)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by_type: Mapped[str] = mapped_column(Text)
    created_by_id: Mapped[str] = mapped_column(Text)
    evidence_fingerprint: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("analysis_id", "evidence_fingerprint"),)


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
