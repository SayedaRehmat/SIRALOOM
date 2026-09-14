from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("external_identifier", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("external_subject", sa.Text()),
        sa.Column("email", sa.Text()),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("case_identifier", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("clinical_context", sa.JSON(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "case_identifier"),
    )
    op.create_table(
        "specimens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("specimen_identifier", sa.Text()),
        sa.Column("specimen_type", sa.Text()),
        sa.Column("collection_datetime", sa.DateTime(timezone=True)),
        sa.Column("received_datetime", sa.DateTime(timezone=True)),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "assays",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("assay_type", sa.Text(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "analyses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("parent_analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id")),
        sa.Column("analysis_type", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("workflow_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reference_build", sa.Text(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id")),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("artifact_type", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text()),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("genome_build", sa.Text()),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_artifacts_sha256", "artifacts", ["sha256"])
    op.create_table(
        "tool_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("tool_version", sa.Text(), nullable=False),
        sa.Column("container_digest", sa.Text()),
        sa.Column("command_fingerprint", sa.Text()),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("exit_code", sa.Integer()),
        sa.Column("stdout_artifact_id", sa.Uuid(), sa.ForeignKey("artifacts.id")),
        sa.Column("stderr_artifact_id", sa.Uuid(), sa.ForeignKey("artifacts.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "workflow_steps",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("step_id", sa.Text(), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("input_artifacts", sa.JSON(), nullable=False),
        sa.Column("output_artifacts", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("analysis_id", "step_id"),
    )
    op.create_index("ix_workflow_steps_status", "workflow_steps", ["status"])
    op.create_table(
        "variants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("genome_build", sa.Text(), nullable=False),
        sa.Column("chromosome", sa.Text(), nullable=False),
        sa.Column("position", sa.BigInteger(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("alternate", sa.Text(), nullable=False),
        sa.Column("normalization_status", sa.Text(), nullable=False),
        sa.Column("identifiers", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("genome_build", "chromosome", "position", "reference", "alternate"),
    )
    op.create_table(
        "annotations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variants.id"), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("provider_version", sa.Text(), nullable=False),
        sa.Column("resource_name", sa.Text()),
        sa.Column("resource_version", sa.Text()),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_annotations_variant", "annotations", ["variant_id"])
    op.create_table(
        "resources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("genome_build", sa.Text()),
        sa.Column("access_method", sa.Text(), nullable=False),
        sa.Column("license_text", sa.Text()),
        sa.Column("checksum", sa.Text()),
        sa.Column("location", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("population_definition", sa.JSON()),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "population_observations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variants.id"), nullable=False),
        sa.Column("resource_id", sa.Uuid(), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("population_level", sa.Text(), nullable=False),
        sa.Column("population_code", sa.Text(), nullable=False),
        sa.Column("population_label", sa.Text(), nullable=False),
        sa.Column("allele_count", sa.BigInteger()),
        sa.Column("allele_number", sa.BigInteger()),
        sa.Column("allele_frequency", sa.Float()),
        sa.Column("homozygote_count", sa.BigInteger()),
        sa.Column("availability", sa.Text(), nullable=False),
        sa.Column("quality_status", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_population_variant", "population_observations", ["variant_id"])
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variants.id"), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("evidence_type", sa.Text(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text()),
        sa.Column("source_version", sa.Text()),
        sa.Column("source_record_id", sa.Text()),
        sa.Column("observation_ids", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_by_type", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "acmg_assessments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variants.id"), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("framework_name", sa.Text(), nullable=False),
        sa.Column("framework_version", sa.Text(), nullable=False),
        sa.Column("specification_provider", sa.Text()),
        sa.Column("specification_id", sa.Text()),
        sa.Column("specification_version", sa.Text()),
        sa.Column("criterion", sa.Text(), nullable=False),
        sa.Column("automated_assessment", sa.JSON(), nullable=False),
        sa.Column("reviewed_assessment", sa.JSON()),
        sa.Column("final_assessment", sa.JSON()),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("variant_id", "analysis_id", "criterion"),
    )
    op.create_table(
        "classifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variants.id"), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("framework_name", sa.Text(), nullable=False),
        sa.Column("framework_version", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("criterion_ids", sa.JSON(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("review_status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "review_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variants.id")),
        sa.Column("reviewer_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("before_state", sa.JSON()),
        sa.Column("after_state", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("report_version", sa.Integer(), nullable=False),
        sa.Column("supersedes_report_id", sa.Uuid(), sa.ForeignKey("reports.id")),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("report_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), sa.ForeignKey("artifacts.id")),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "report_version", name="uq_report_case_version"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_version", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("cases.id")),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id")),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text()),
        sa.Column("subject_id", sa.Text()),
        sa.Column("operation", sa.Text()),
        sa.Column("before_state", sa.JSON()),
        sa.Column("after_state", sa.JSON()),
        sa.Column("reason", sa.Text()),
        sa.Column("input_artifacts", sa.JSON(), nullable=False),
        sa.Column("output_artifacts", sa.JSON(), nullable=False),
        sa.Column("software", sa.JSON(), nullable=False),
        sa.Column("workflow", sa.JSON(), nullable=False),
        sa.Column("resource_versions", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.Text()),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_case_time", "audit_events", ["case_id", "occurred_at"])
    op.add_column("audit_events", sa.Column("previous_event_hash", sa.Text()))
    op.add_column("audit_events", sa.Column("event_hash", sa.Text()))
    op.create_index("ix_audit_event_hash", "audit_events", ["event_hash"], unique=True)

    op.create_table(
        "installations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("installation_fingerprint", sa.Text(), nullable=False, unique=True),
        sa.Column("hostname", sa.Text()),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_check_in", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False),
    )
    op.create_table(
        "licenses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("license_key_id", sa.Text(), nullable=False, unique=True),
        sa.Column("plan", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("max_installations", sa.Integer(), nullable=False),
        sa.Column("max_concurrent_jobs", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "license_entitlements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("license_id", sa.Uuid(), sa.ForeignKey("licenses.id"), nullable=False),
        sa.Column("installation_id", sa.Uuid(), sa.ForeignKey("installations.id"), nullable=False),
        sa.Column("lease_version", sa.Integer(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("signed_payload", sa.JSON(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    for table in ["license_entitlements", "licenses", "installations", "audit_events", "reports", "review_actions", "classifications", "acmg_assessments", "evidence", "population_observations", "resources", "annotations", "variants", "workflow_steps", "tool_runs", "artifacts", "analyses", "assays", "specimens", "cases", "users", "organizations"]:
        op.drop_table(table)
