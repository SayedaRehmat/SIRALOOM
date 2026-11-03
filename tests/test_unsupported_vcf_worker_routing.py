import json
from hashlib import sha256
from pathlib import Path
from uuid import uuid4, uuid5

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.domain.workflow_decision import WorkflowAction, WorkflowDecision
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AnalysisPartition,
    Artifact,
    AuditEvent,
    Case,
    Organization,
    Resource,
    User,
    Variant,
    WorkflowStep,
    ResourceQualification,
    ResourceExecutionRecord,
    ResourceApproval,
    OrganizationResourceBinding,
)
from backend.app.workflows.variant import _check_routed_artifact_validation_replay


def test_routed_artifact_replay_rejects_reference_package_replacement():
    metadata = {
        "reference_validation_status": "PASS",
        "reference_package_id": "resource-v1",
        "reference_package_version": "1",
        "reference_fasta_sha256": "a" * 64,
        "source_reference_allele_profile": {"result": "PASS"},
    }

    with pytest.raises(RuntimeError, match="different reference package identity"):
        _check_routed_artifact_validation_replay(
            metadata,
            status="PASS",
            reference_package={
                "resource_id": "resource-v1",
                "version": "2",
                "fasta_sha256": "b" * 64,
            },
            active_reference_package=None,
            reference_profile={"result": "PASS"},
        )


def test_routed_artifact_replay_rejects_changed_reference_allele_profile():
    metadata = {
        "reference_validation_status": "PASS",
        "reference_package_id": "resource-v1",
        "reference_package_version": "1",
        "reference_fasta_sha256": "a" * 64,
        "source_reference_allele_profile": {"result": "PASS"},
    }

    with pytest.raises(RuntimeError, match="different source allele profile"):
        _check_routed_artifact_validation_replay(
            metadata,
            status="PASS",
            reference_package={
                "resource_id": "resource-v1",
                "version": "1",
                "fasta_sha256": "a" * 64,
            },
            active_reference_package=None,
            reference_profile={"result": "PASS", "checked_record_count": 1},
        )


def test_routed_artifact_replay_preserves_validation_when_resource_is_unavailable():
    assert _check_routed_artifact_validation_replay(
        {
            "reference_validation_status": "PASS",
            "reference_package_id": "resource-v1",
            "reference_package_version": "1",
            "reference_fasta_sha256": "a" * 64,
            "source_reference_allele_profile": {"result": "PASS"},
        },
        status="NOT_RUN",
        reference_package=None,
        active_reference_package=None,
        reference_profile=None,
    )


def _vcf(columns: str, records: str, *, headers: str = "") -> str:
    return (
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=1000>\n"
        "##contig=<ID=2,length=1000>\n"
        + headers
        + columns
        + "\n"
        + records
    )


@pytest.mark.parametrize(
    ("filename", "vcf", "artifact_type", "count_key", "review_reason_code"),
    [
        (
            "blocks.g.vcf",
            _vcf(
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1",
                "1\t1\t.\tA\t<NON_REF>\t.\tPASS\tEND=10\tGT:DP:MIN_DP:GQ:PL\t0/0:30:25:40:0,40,400\n",
                headers='##ALT=<ID=NON_REF,Description="Any possible alternate allele">\n',
            ),
            "GVCF_REFERENCE_BLOCKS",
            "gvcf_reference_blocks",
            "GVCF_REFERENCE_CONFIDENCE_ANALYSIS_UNSUPPORTED",
        ),
        (
            "deletion.vcf",
            _vcf(
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
                "1\t5\tdel1\tA\t<DEL>\t50\tPASS\tSVTYPE=DEL;END=10\n",
                headers='##ALT=<ID=DEL,Description="Deletion">\n',
            ),
            "STRUCTURAL_VARIANT_RECORDS",
            "structural_variant_records",
            "STRUCTURAL_VARIANT_INTERPRETATION_UNSUPPORTED",
        ),
        (
            "breakends.vcf",
            _vcf(
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
                "1\t100\tbnd1\tA\tA]2:200]\t.\tPASS\tSVTYPE=BND;MATEID=bnd2\n"
                "2\t200\tbnd2\tC\t[1:100[C\t.\tPASS\tSVTYPE=BND;MATEID=bnd1\n",
            ),
            "STRUCTURAL_VARIANT_RECORDS",
            "structural_variant_records",
            "STRUCTURAL_VARIANT_INTERPRETATION_UNSUPPORTED",
        ),
        (
            "unresolved.g.vcf",
            _vcf(
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1",
                "1\t5\tvar1\tA\tC,<NON_REF>\t50\tPASS\tDP=20\tGT:AD:PL\t0/2:10,0,10:0,50,100,80,0,80\n",
                headers=(
                    '##ALT=<ID=NON_REF,Description="Any possible alternate allele">\n'
                    '##INFO=<ID=DP,Number=1,Type=Integer,Description="Depth">\n'
                    '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
                    '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths">\n'
                    '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Phred likelihoods">\n'
                ),
            ),
            "UNRESOLVED_GVCF_VARIANTS",
            "gvcf_unresolved_variant_records",
            "GVCF_VARIANT_ALLELE_UNRESOLVED",
        ),
        (
            "reference-only.vcf",
            _vcf(
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
                "1\t5\tref1\tA\t.\t.\tPASS\t.\n",
            ),
            None,
            "reference_only_records",
            "NO_VARIANT_ALLELES_PROVIDED",
        ),
        (
            "telomere.vcf",
            _vcf(
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
                "1\t0\ttelo1\tA\tG\t.\tPASS\t.\n",
            ),
            "TELOMERE_COORDINATE_RECORDS",
            "telomere_records",
            "VCF_TELOMERE_COORDINATE_UNSUPPORTED",
        ),
    ],
)
def test_production_worker_preserves_valid_non_sequence_records_for_review(
    monkeypatch, tmp_path, filename, vcf, artifact_type, count_key, review_reason_code
):
    """The real worker routes valid GVCF/SV records instead of blanket-blocking them."""
    import importlib

    workflow = importlib.import_module("backend.app.workflows.variant")
    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'routed-input.db'}")
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)
    store = ArtifactStore(tmp_path / "artifacts")
    organization_id, user_id, case_id, analysis_id = uuid4(), uuid4(), uuid4(), uuid4()
    source = tmp_path / filename
    source.write_text(vcf, encoding="utf-8")
    source_sha256 = sha256(source.read_bytes()).hexdigest()

    try:
        with local_session() as db:
            db.add(Organization(id=organization_id, name="Input Routing Lab"))
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="Input Routing Test", role="ADMIN", status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"ROUTE-{analysis_id}", status="ACTIVE",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.flush()
            input_artifact = store.put_file(
                db=db, case_id=case_id, analysis_id=analysis_id,
                source_path=source, filename=filename, artifact_type="SOURCE_VCF",
                media_type="text/plain", genome_build="GRCh38", metadata={},
                validation_status="VALID",
            )
            db.add(Analysis(
                id=analysis_id, case_id=case_id, parent_analysis_id=None,
                assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1", workflow_version="test",
                status=AnalysisStatus.QUEUED, queue_task_id="routing-test",
                reference_build="GRCh38",
                configuration={"input_artifact_id": str(input_artifact.id)},
                started_at=None, completed_at=None, created_by=user_id,
                analysis_version=1,
            ))
            db.commit()

        monkeypatch.setattr(db_module, "SessionLocal", local_session)
        monkeypatch.setattr(workflow, "artifact_store_for_organization", lambda *_a, **_k: store)
        monkeypatch.setattr(workflow, "artifact_store_for_uri", lambda *_a, **_k: store)

        def unexpected_reference_lookup(*_args, **_kwargs):
            raise AssertionError("records with no sequence-resolved variants need no normalization reference")

        monkeypatch.setattr(workflow, "resolve_resource_with_fallback", unexpected_reference_lookup)
        monkeypatch.setattr(workflow, "load_reference_package", unexpected_reference_lookup)
        workflow.run_variant_analysis(analysis_id)

        with local_session() as db:
            analysis = db.get(Analysis, analysis_id)
            source_row = db.get(Artifact, input_artifact.id)
            routed = db.scalar(select(Artifact).where(
                Artifact.analysis_id == analysis_id,
                Artifact.artifact_type == artifact_type,
            ))
            normalization = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "normalize",
            ))
            event = db.scalar(select(AuditEvent).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "VCF_RECORDS_ROUTED_TO_REVIEW",
            ))
            assert analysis.status == AnalysisStatus.REQUIRES_REVIEW
            assert normalization.status == StepStatus.REQUIRES_REVIEW
            assert normalization.error_code == "NO_SEQUENCE_VARIANTS_TO_NORMALIZE"
            assert normalization.metadata_json["review_reason_codes"] == [review_reason_code]
            assert normalization.metadata_json["routing"][count_key] > 0
            if artifact_type is None:
                assert routed is None
                assert normalization.metadata_json["next_step"] == "UPSTREAM_VARIANT_CALLSET_REVIEW"
                assert "not a negative clinical result" in normalization.error_message
                manifest = db.scalar(select(Artifact).where(
                    Artifact.analysis_id == analysis_id,
                    Artifact.artifact_type == "VCF_EXCLUSION_MANIFEST",
                ))
                assert manifest is not None and store.exists(manifest.storage_uri)
                assert str(manifest.id) in normalization.output_artifacts
                assert event.output_artifacts == [{
                    "artifact_id": str(manifest.id), "sha256": manifest.sha256,
                }]
            else:
                assert routed is not None
                assert routed.metadata_json["source_artifact_id"] == str(source_row.id)
                assert routed.metadata_json["source_sha256"] == source_sha256
                assert routed.metadata_json["record_count"] == normalization.metadata_json["routing"][count_key]
                assert routed.metadata_json["interpretation_status"] == "NOT_ANALYZED"
                assert routed.metadata_json["review_status"] == "REQUIRES_SPECIALIZED_REVIEW"
                assert routed.metadata_json["review_reason_code"] == review_reason_code
                if artifact_type == "TELOMERE_COORDINATE_RECORDS":
                    assert normalization.metadata_json["next_step"] == "VCF_TELOMERE_COORDINATE_REVIEW"
                    assert routed.metadata_json["reference_validation_status"] == (
                        "NOT_VALIDATED_UNSUPPORTED_COORDINATE"
                    )
                    assert routed.metadata_json["reference_validation_reason_code"] == (
                        "VCF_TELOMERE_COORDINATE_UNSUPPORTED"
                    )
                else:
                    assert routed.metadata_json["reference_validation_status"] == "NOT_RUN"
                    assert routed.metadata_json["reference_validation_reason_code"] == (
                        "NO_SEQUENCE_VARIANTS_ELIGIBLE_FOR_REFERENCE_NORMALIZATION"
                    )
            assert store.exists(source_row.storage_uri)
            source_records = [line for line in vcf.splitlines() if line and not line.startswith("#")]
            assert source_row.sha256 == source_sha256
            assert sha256(store.read_bytes(source_row.storage_uri)).hexdigest() == source_sha256
            if routed is not None:
                assert store.exists(routed.storage_uri)
                routed_bytes = store.read_bytes(routed.storage_uri)
                assert sha256(routed_bytes).hexdigest() == routed.sha256
                routed_records = [line for line in routed_bytes.decode("utf-8").splitlines() if line and not line.startswith("#")]
                assert routed_records == source_records
            assert event.payload["routing"][count_key] > 0
            assert event.payload["review_reason_codes"] == [review_reason_code]
            if routed is not None:
                assert event.output_artifacts[0]["artifact_id"] == str(routed.id)
            assert db.scalar(select(Artifact).where(
                Artifact.analysis_id == analysis_id,
                Artifact.artifact_type == "NORMALIZED_VCF",
            )) is None
    finally:
        engine.dispose()


def test_production_worker_rejects_malformed_symbolic_sv_with_precise_reason(monkeypatch, tmp_path):
    import importlib

    workflow = importlib.import_module("backend.app.workflows.variant")
    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'malformed-sv.db'}")
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)
    store = ArtifactStore(tmp_path / "artifacts")
    organization_id, user_id, case_id, analysis_id = uuid4(), uuid4(), uuid4(), uuid4()
    source = tmp_path / "malformed-del.vcf"
    source.write_text(_vcf(
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
        "1\t5\tdel1\tA\t<DEL>\t50\tPASS\tSVTYPE=DEL\n",
        headers='##ALT=<ID=DEL,Description="Deletion">\n',
    ), encoding="utf-8")
    try:
        with local_session() as db:
            db.add(Organization(id=organization_id, name="Malformed Input Lab"))
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="Malformed Input Test", role="ADMIN", status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"MALFORMED-{analysis_id}", status="ACTIVE",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.flush()
            artifact = store.put_file(
                db=db, case_id=case_id, analysis_id=analysis_id,
                source_path=source, filename=source.name, artifact_type="SOURCE_VCF",
                media_type="text/plain", genome_build="GRCh38", metadata={},
                validation_status="VALID",
            )
            db.add(Analysis(
                id=analysis_id, case_id=case_id, parent_analysis_id=None,
                assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1", workflow_version="test",
                status=AnalysisStatus.QUEUED, queue_task_id="malformed-sv-test",
                reference_build="GRCh38",
                configuration={"input_artifact_id": str(artifact.id)},
                started_at=None, completed_at=None, created_by=user_id,
                analysis_version=1,
            ))
            db.commit()
        monkeypatch.setattr(db_module, "SessionLocal", local_session)
        monkeypatch.setattr(workflow, "artifact_store_for_organization", lambda *_a, **_k: store)
        monkeypatch.setattr(workflow, "artifact_store_for_uri", lambda *_a, **_k: store)

        workflow.run_variant_analysis(analysis_id)

        with local_session() as db:
            analysis = db.get(Analysis, analysis_id)
            validation = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "validate_input",
            ))
            assert analysis.status == AnalysisStatus.BLOCKED
            assert validation.status == StepStatus.BLOCKED
            assert validation.error_code == "VCF_SV_SPAN_MISSING"
            assert "requires END or allele-specific SVLEN" in validation.error_message
            assert store.exists(db.get(Artifact, artifact.id).storage_uri)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("reference_mismatch", "worker_loss", "normalization_resource_failure", "artifact_identity_conflict"),
    [
        (False, False, False, False),
        (True, False, False, False),
        (False, True, False, False),
        (False, False, True, False),
        (False, False, False, True),
    ],
)
def test_production_worker_normalizes_called_variant_from_gvcf_and_preserves_block(
    monkeypatch, tmp_path, reference_mismatch, worker_loss,
    normalization_resource_failure, artifact_identity_conflict
):
    """Exercise the profile-bound, qualified BCFtools execution path and durable provenance in the production worker."""
    import gzip
    import importlib
    from types import SimpleNamespace
    from datetime import UTC, datetime
    import hashlib
    import json

    from backend.app.domain.resource_source_contract import validate_execution_contract
    from backend.app.domain.resource_execution import (
        start_resource_execution as real_start_resource_execution,
        complete_resource_execution as real_complete_resource_execution,
    )

    workflow = importlib.import_module("backend.app.workflows.variant")
    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'gvcf-positive.db'}")
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)
    store = ArtifactStore(tmp_path / "artifacts")
    organization_id, user_id, case_id, analysis_id, resource_id, normalization_resource_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    sequence = "A" * 20 + "T" + "A" * 979
    fasta = tmp_path / "reference.fa"
    fasta.write_text(f">1\n{sequence}\n", encoding="utf-8", newline="\n")
    fai = tmp_path / "reference.fa.fai"
    fai.write_text(f"1\t{len(sequence)}\t3\t{len(sequence)}\t{len(sequence)+1}\n", encoding="utf-8")
    source = tmp_path / "sample.g.vcf"
    source.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=1000>\n"
        '##ALT=<ID=NON_REF,Description="Any possible alternate allele">\n'
        '##INFO=<ID=DP,Number=1,Type=Integer,Description="Depth">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths">\n'
        '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Phred likelihoods">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
        "1\t0\ttelo1\tA\tG\t50\tPASS\t.\tGT:AD:PL\t0/1:10,10:0,20,200\n"
        "1\t1\t.\tA\t<NON_REF>\t.\tPASS\tEND=10;DP=30\tGT:AD:PL\t0/0:30,0:0,40,400\n"
        "1\t11\trs1\tA\tC,<NON_REF>\t50\tPASS\tDP=24\tGT:AD:PL\t0/1:15,9,0:100,50,60,40,0,30\n"
        "1\t20\tdel1\tAT\tA\t50\tPASS\t.\tGT:AD:PL\t0/1:10,10:0,20,200\n"
        "1\t21\tstar1\tT\t*\t50\tPASS\t.\tGT:AD:PL\t0/1:10,10:0,20,200\n"
        + f"1\t30\tsvdel1\t{'C' if reference_mismatch else 'A'}\t<DEL>\t50\tPASS\tSVTYPE=DEL;END=35\tGT:AD:PL\t0/1:10,10:0,20,200\n"
        + "1\t1001\ttelo-after\tA\tG\t50\tPASS\t.\tGT:AD:PL\t0/1:10,10:0,20,200\n",
        encoding="utf-8",
    )
    try:
        with local_session() as db:
            db.add(Organization(id=organization_id, name="GVCF Positive Lab"))
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="GVCF Positive Test", role="ADMIN", status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"GVCF-{analysis_id}", status="ACTIVE",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.flush()
            input_artifact = store.put_file(
                db=db, case_id=case_id, analysis_id=analysis_id,
                source_path=source, filename=source.name, artifact_type="SOURCE_VCF",
                media_type="text/plain", genome_build="GRCh38", metadata={},
                validation_status="VALID",
            )
            reference = Resource(
                id=resource_id, organization_id=organization_id,
                name="Test reference", provider="SIRALOOM_TEST",
                resource_type="REFERENCE_PACKAGE", version="fixture-1",
                genome_build="GRCh38", access_method="API", license_text="test",
                checksum="a" * 64, location="https://fixture.invalid/reference",
                status="ACTIVE", population_definition=None, metadata_json={},
            )
            db.add(reference)
            normalization_resource = Resource(
                id=normalization_resource_id,
                organization_id=organization_id,
                name="Qualified BCFtools 1.25",
                provider="bcftools",
                resource_type="NORMALIZATION",
                version="1.25",
                genome_build=None,
                access_method="LOCAL",
                license_text="test",
                checksum="a" * 64,
                location="/opt/siraloom/qualified/bcftools/1.25/bin/bcftools",
                status="ACTIVE",
                population_definition=None,
                metadata_json={"execution": {"executable": "/opt/siraloom/qualified/bcftools/1.25/bin/bcftools"}},
            )
            db.add(normalization_resource)
            qualification_id = uuid4()
            qualified_contract = validate_execution_contract(
                {
                    "provider_id": "bcftools",
                    "provider_version": "1.25",
                    "access_method": "LOCAL",
                    "location": normalization_resource.location,
                    "execution_scope": "ORGANIZATION_MANAGED",
                    "toolchain": {"bcftools": {
                        "executable": normalization_resource.location,
                        "sha256": "f" * 64,
                    }},
                },
                resource_provider=normalization_resource.provider,
                resource_access_method=normalization_resource.access_method,
                resource_location=normalization_resource.location,
                resource_organization_id=organization_id,
            )
            qualified_contract_hash = hashlib.sha256(
                json.dumps(
                    qualified_contract.as_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            db.add(ResourceQualification(
                id=qualification_id,
                resource_id=normalization_resource_id,
                qualification_version="siraloom-resource-qualification-v1",
                status="QUALIFIED",
                checks_json={"execution_contract": qualified_contract.as_dict()},
                qualified_by=user_id,
                qualified_at=datetime.now(UTC),
            ))
            if not normalization_resource_failure:
                approval_id = uuid4()
                now = datetime.now(UTC)
                db.add(ResourceApproval(
                    id=approval_id,
                    resource_id=normalization_resource_id,
                    organization_id=organization_id,
                    qualification_id=qualification_id,
                    status="APPROVED",
                    version=2,
                    requested_at=now,
                    decided_at=now,
                    decided_by=user_id,
                    reason="Approved qualified BCFtools resource for the integration fixture.",
                ))
                db.add(OrganizationResourceBinding(
                    id=uuid4(),
                    organization_id=organization_id,
                    resource_id=normalization_resource_id,
                    resource_name=normalization_resource.name,
                    provider=normalization_resource.provider,
                    resource_type=normalization_resource.resource_type,
                    genome_build=None,
                    identity_key="|".join([
                        normalization_resource.name,
                        normalization_resource.provider,
                        normalization_resource.resource_type,
                        "UNSPECIFIED",
                    ]),
                    bound_by=user_id,
                    reason="Current approved normalization resource binding.",
                ))
            db.add(Analysis(
                id=analysis_id, case_id=case_id, parent_analysis_id=None,
                assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1", workflow_version="test",
                status=AnalysisStatus.QUEUED, queue_task_id="gvcf-positive-test",
                reference_build="GRCh38",
                configuration={
                    "input_artifact_id": str(input_artifact.id),
                    "reference_resource_id": str(resource_id),
                    "resource_profile_id": str(uuid4()),
                    "resource_plan": {
                        "status": "READY",
                        "deployment": {"profile_type": "LABORATORY", "profile_version": "1"},
                        "selected": [{
                            "resource_id": str(normalization_resource_id),
                            "capability": workflow.NORMALIZATION_ENGINE,
                            "execution": {
                                "resource_id": str(normalization_resource_id),
                                "resource_version": "1.25",
                                "qualification_id": str(qualification_id),
                                "qualification_version": "siraloom-resource-qualification-v1",
                                "contract_hash": qualified_contract_hash,
                            },
                        }],
                        "issues": [],
                    },
                },
                started_at=None, completed_at=None, created_by=user_id,
                analysis_version=1,
            ))
            db.commit()

        monkeypatch.setattr(db_module, "SessionLocal", local_session)
        monkeypatch.setattr(workflow, "artifact_store_for_organization", lambda *_a, **_k: store)
        monkeypatch.setattr(workflow, "artifact_store_for_uri", lambda *_a, **_k: store)
        decision = WorkflowDecision(WorkflowAction.CONTINUE, "TEST_REFERENCE_SELECTED", "Fixture reference selected")
        monkeypatch.setattr(workflow, "resolve_resource_with_fallback", lambda db, **_k: SimpleNamespace(
            resource=db.get(Resource, resource_id), used_fallback=False,
            requested_resource_id=resource_id, fallback_resource_id=None, decision=decision,
        ))
        reference_runtime = SimpleNamespace(
            resource=reference,
            execution=SimpleNamespace(
                contract=SimpleNamespace(access_method="API", toolchain={}),
                snapshot={"test": "reference-qualified"},
                contract_hash="e" * 64,
            ),
        )
        normalization_runtime = SimpleNamespace(
            resource=normalization_resource,
            execution=SimpleNamespace(
                contract=SimpleNamespace(
                    toolchain={"bcftools": {
                        "executable": normalization_resource.location,
                        "sha256": "f" * 64,
                    }}
                ),
                snapshot={"test": "normalization-qualified"},
                contract_hash="f" * 64,
            ),
        )

        real_resolve_profile_runtime_resource = workflow.resolve_profile_runtime_resource

        def resolve_profile_resource(_db, *, analysis_id, capability):
            if capability == "REFERENCE_PACKAGE":
                return reference_runtime
            if capability == workflow.NORMALIZATION_ENGINE:
                return real_resolve_profile_runtime_resource(
                    _db,
                    analysis_id=analysis_id,
                    capability=capability,
                )
            if capability == "ANNOTATION_ENGINE":
                raise workflow.ProfileRuntimeResourceError(
                    "ANNOTATION_PROVIDER_UNAVAILABLE",
                    "Fixture intentionally stops after normalization.",
                )
            raise AssertionError(f"Unexpected profile capability: {capability}")

        monkeypatch.setattr(workflow, "resolve_profile_runtime_resource", resolve_profile_resource)
        monkeypatch.setattr(workflow, "load_reference_package", lambda *_a, **_k: {
            "resource_id": str(resource_id), "version": "fixture-1",
            "package_checksum": "a" * 64, "fasta_path": str(fasta),
            "fasta_sha256": "b" * 64, "fai_sha256": "c" * 64,
            "contigs_sha256": "d" * 64, "contig_policy": "EXACT",
            "contigs": [{"name": "1", "length": 1000}],
        })
        monkeypatch.setattr(workflow, "resolve_resource_execution", lambda *_a, **_k: SimpleNamespace(
            contract=SimpleNamespace(access_method="API"), snapshot={"test": True},
            contract_hash="e" * 64,
        ))
        def start_execution(db, **kwargs):
            resolved = kwargs.get("resolved")
            if getattr(resolved, "resource_id", None) == normalization_resource_id:
                return real_start_resource_execution(db, **kwargs)
            return SimpleNamespace(metadata_json={})

        def complete_execution(db, record, **kwargs):
            if isinstance(record, ResourceExecutionRecord):
                return real_complete_resource_execution(db, record, **kwargs)
            return None

        monkeypatch.setattr(workflow, "start_resource_execution", start_execution)
        monkeypatch.setattr(workflow, "complete_resource_execution", complete_execution)

        def fake_normalize(resource, input_path, output_path, **kwargs):
            assert resource.id == normalization_resource_id
            assert kwargs["approved"] is True
            assert kwargs["expected_bcftools_sha256"] == "f" * 64
            assert kwargs["qualified_bcftools_executable"] == normalization_resource.location
            routed_text = Path(input_path).read_text(encoding="utf-8")
            assert "A\tC,<NON_REF>" in routed_text
            assert "AT\tA" in routed_text
            assert "\t*\t" not in routed_text
            assert "\t0\ttelo1\t" not in routed_text
            assert "\t1001\ttelo-after\t" not in routed_text
            assert "<NON_REF>\t.\tPASS\tEND=10" not in routed_text
            index = Path(str(output_path) + ".csi")
            vcf_payload = (
                "##fileformat=VCFv4.3\n##contig=<ID=1,length=1000>\n"
                '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
                '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths">\n'
                '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Phred likelihoods">\n'
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
                "1\t11\trs1\tA\tC\t50\tPASS\tDP=24\tGT:AD:PL\t0/1:15,9:100,50,60\n"
                "1\t20\tdel1\tAT\tA\t50\tPASS\t.\tGT:AD:PL\t0/1:10,10:0,20,200\n"
            )
            with output_path.open("wb") as raw_handle:
                with gzip.GzipFile(fileobj=raw_handle, mode="wb", filename="", mtime=0) as handle:
                    handle.write(vcf_payload.encode("utf-8"))
            index.write_bytes(b"fixture-csi")
            stats = {
                "tool": "bcftools", "tool_version": "bcftools 1.25",
                "expected_tool_version": "1.25", "operation": "fixture-normalization",
                "command": "bcftools view -A && bcftools norm -f ref.fa -c e -m -any",
                "source_record_mapping_tag": "SIRALOOM_ORIG",
                "source_record_mapping_policy": "BCFTOOLS_OLD_REC_TAG_SOURCE_ALT_INDEX",
                "compression": "BGZF", "index": "CSI", "index_path": str(index),
                "multiallelic_overlap_policy": ".",
                "executable_identity": {
                    "path": kwargs["qualified_bcftools_executable"],
                    "sha256": kwargs["expected_bcftools_sha256"],
                },
                "executable_integrity_status": "MATCHED_QUALIFIED_SHA256",
            }
            return stats, SimpleNamespace(snapshot={"qualified": True})

        used_real_bcftools = False
        monkeypatch.setattr(workflow, "normalize_with_selected_provider", fake_normalize)
        if artifact_identity_conflict:
            from backend.app.infrastructure.artifacts.store import ArtifactIdentityConflictError

            original_put_file = store.put_file

            def conflict_normalized_artifact(**kwargs):
                if kwargs.get("artifact_type") == "NORMALIZED_VCF":
                    raise ArtifactIdentityConflictError(
                        "fixture: normalized artifact ID already contains different bytes"
                    )
                return original_put_file(**kwargs)

            monkeypatch.setattr(store, "put_file", conflict_normalized_artifact)

        if worker_loss:
            queue_module = importlib.import_module(
                "backend.app.infrastructure.queue.celery_app"
            )
            monkeypatch.setattr(db_module, "engine", engine)
            task_id = "gvcf-positive-test"
            normalized_id = uuid5(
                analysis_id, "siraloom:normalization:normalized-vcf:v6"
            )
            normalized_uri = store.uri_for_artifact(
                case_id=case_id,
                artifact_id=normalized_id,
                filename="normalized.vcf.gz",
            )
            original_put_file = store.put_file
            artifact_write_losses = {"remaining": 1}

            def lose_worker_after_normalized_artifact_flush(**kwargs):
                artifact = original_put_file(**kwargs)
                if (
                    kwargs.get("artifact_type") == "NORMALIZED_VCF"
                    and artifact_write_losses["remaining"]
                ):
                    artifact_write_losses["remaining"] -= 1
                    raise SystemExit("simulated worker loss after normalized file and row flush")
                return artifact

            monkeypatch.setattr(store, "put_file", lose_worker_after_normalized_artifact_flush)
            normalization_calls = {"count": 0}
            original_normalize = workflow.normalize_with_selected_provider

            def count_real_normalization(*args, **kwargs):
                normalization_calls["count"] += 1
                return original_normalize(*args, **kwargs)

            monkeypatch.setattr(
                workflow, "normalize_with_selected_provider", count_real_normalization
            )

            def deliver(*, redelivered):
                queue_module.run_analysis_task.push_request(
                    id=task_id,
                    retries=0,
                    delivery_info={"redelivered": redelivered},
                )
                try:
                    return queue_module.run_analysis_task.run(str(analysis_id))
                finally:
                    queue_module.run_analysis_task.pop_request()

            with pytest.raises(SystemExit, match="simulated worker loss"):
                deliver(redelivered=False)

            with local_session() as db:
                interrupted = db.get(Analysis, analysis_id)
                interrupted_step = db.scalar(select(WorkflowStep).where(
                    WorkflowStep.analysis_id == analysis_id,
                    WorkflowStep.step_id == "normalize",
                ))
                assert interrupted.status == AnalysisStatus.RUNNING
                assert interrupted_step.status == StepStatus.RUNNING
                assert db.scalar(select(Artifact).where(
                    Artifact.analysis_id == analysis_id,
                    Artifact.artifact_type == "NORMALIZED_VCF",
                )) is None
                assert store.exists(normalized_uri)
                assert normalization_calls["count"] == 1

            monkeypatch.setattr(store, "put_file", original_put_file)
            deliver(redelivered=True)
        else:
            workflow.run_variant_analysis(analysis_id)

        with local_session() as db:
            step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "normalize",
            ))
            normalized = db.scalar(select(Artifact).where(
                Artifact.analysis_id == analysis_id,
                Artifact.artifact_type == "NORMALIZED_VCF",
            ))
            block_artifact = db.scalar(select(Artifact).where(
                Artifact.analysis_id == analysis_id,
                Artifact.artifact_type == "GVCF_REFERENCE_BLOCKS",
            ))
            star_artifact = db.scalar(select(Artifact).where(
                Artifact.analysis_id == analysis_id,
                Artifact.artifact_type == "SPANNING_DELETION_RECORDS",
            ))
            sv_artifact = db.scalar(select(Artifact).where(
                Artifact.analysis_id == analysis_id,
                Artifact.artifact_type == "STRUCTURAL_VARIANT_RECORDS",
            ))
            telomere_artifact = db.scalar(select(Artifact).where(
                Artifact.analysis_id == analysis_id,
                Artifact.artifact_type == "TELOMERE_COORDINATE_RECORDS",
            ))
            telomere_after_artifact = db.scalar(select(Artifact).where(
                Artifact.analysis_id == analysis_id,
                Artifact.artifact_type == "TELOMERE_AFTER_CONTIG_RECORDS",
            ))
            exclusion_manifests = db.scalars(select(Artifact).where(
                Artifact.analysis_id == analysis_id,
                Artifact.artifact_type == "VCF_EXCLUSION_MANIFEST",
            )).all()
            analysis = db.get(Analysis, analysis_id)
            if normalization_resource_failure or artifact_identity_conflict:
                expected_error = (
                    "RESOURCE_NOT_ADOPTED"
                    if normalization_resource_failure
                    else "ARTIFACT_IDENTITY_CONFLICT"
                )
                assert analysis.status == AnalysisStatus.REQUIRES_REVIEW
                assert step.status == StepStatus.REQUIRES_REVIEW
                assert step.error_code == expected_error
                assert normalized is None
                provider_execution = db.scalar(select(ResourceExecutionRecord).where(
                    ResourceExecutionRecord.analysis_id == analysis_id,
                    ResourceExecutionRecord.resource_id == normalization_resource_id,
                ))
                if artifact_identity_conflict:
                    assert provider_execution is not None
                else:
                    assert provider_execution is None
                review_event = db.scalar(select(AuditEvent).where(
                    AuditEvent.analysis_id == analysis_id,
                    AuditEvent.event_type == (
                        "NORMALIZATION_RESOURCE_REQUIRES_REVIEW"
                        if normalization_resource_failure
                        else "NORMALIZATION_ARTIFACT_IDENTITY_CONFLICT"
                    ),
                ))
                assert review_event is not None
                if normalization_resource_failure:
                    assert review_event.payload["automatic_fallback"] is False
                else:
                    assert review_event.payload["automatic_overwrite"] is False
                assert review_event.payload["human_action_required"] is True
                return
            assert block_artifact is not None and store.exists(block_artifact.storage_uri)
            assert star_artifact is not None and store.exists(star_artifact.storage_uri)
            assert sv_artifact is not None and store.exists(sv_artifact.storage_uri)
            assert telomere_artifact is not None and store.exists(telomere_artifact.storage_uri)
            assert telomere_after_artifact is not None and store.exists(telomere_after_artifact.storage_uri)
            assert len(exclusion_manifests) == 1
            exclusion_manifest = exclusion_manifests[0]
            assert store.exists(exclusion_manifest.storage_uri)
            assert exclusion_manifest.metadata_json["source_artifact_id"] == str(input_artifact.id)
            assert exclusion_manifest.metadata_json["source_sha256"] == input_artifact.sha256
            assert exclusion_manifest.metadata_json["reference_contig_lengths_resolved"] is True
            assert exclusion_manifest.metadata_json["record_count"] == 5
            exclusion_rows = [
                json.loads(line)
                for line in store.read_bytes(exclusion_manifest.storage_uri).decode("utf-8").splitlines()
            ]
            assert [row["source_record_index"] for row in exclusion_rows] == [1, 2, 5, 6, 7]
            assert {row["routed_artifact_type"] for row in exclusion_rows} == {
                "GVCF_REFERENCE_BLOCKS", "SPANNING_DELETION_RECORDS",
                "STRUCTURAL_VARIANT_RECORDS", "TELOMERE_COORDINATE_RECORDS",
                "TELOMERE_AFTER_CONTIG_RECORDS",
            }
            assert block_artifact.metadata_json["source_artifact_id"] == str(input_artifact.id)
            assert star_artifact.metadata_json["source_sha256"] == input_artifact.sha256
            assert sv_artifact.metadata_json["source_sha256"] == input_artifact.sha256
            assert block_artifact.metadata_json["record_count"] == 1
            assert star_artifact.metadata_json["record_count"] == 1
            assert sv_artifact.metadata_json["record_count"] == 1
            assert telomere_artifact.metadata_json["record_count"] == 1
            assert telomere_after_artifact.metadata_json["record_count"] == 1
            assert sha256(store.read_bytes(block_artifact.storage_uri)).hexdigest() == block_artifact.sha256
            assert sha256(store.read_bytes(star_artifact.storage_uri)).hexdigest() == star_artifact.sha256
            assert sha256(store.read_bytes(sv_artifact.storage_uri)).hexdigest() == sv_artifact.sha256
            assert sha256(store.read_bytes(telomere_artifact.storage_uri)).hexdigest() == telomere_artifact.sha256
            assert sha256(store.read_bytes(telomere_after_artifact.storage_uri)).hexdigest() == telomere_after_artifact.sha256
            assert "END=10" in store.read_bytes(block_artifact.storage_uri).decode("utf-8")
            assert "\t*\t" in store.read_bytes(star_artifact.storage_uri).decode("utf-8")
            assert "<DEL>" in store.read_bytes(sv_artifact.storage_uri).decode("utf-8")
            assert "\t0\ttelo1\t" in store.read_bytes(telomere_artifact.storage_uri).decode("utf-8")
            assert "\t1001\ttelo-after\t" in store.read_bytes(telomere_after_artifact.storage_uri).decode("utf-8")
            if reference_mismatch:
                for artifact in (block_artifact, star_artifact, sv_artifact):
                    assert artifact.metadata_json["reference_validation_status"] == "FAILED"
                    assert artifact.metadata_json["reference_validation_reason_code"] == "VCF_REFERENCE_MISMATCH"
                assert telomere_artifact.metadata_json["reference_validation_status"] == (
                    "NOT_VALIDATED_UNSUPPORTED_COORDINATE"
                )
                assert telomere_after_artifact.metadata_json["reference_validation_status"] == (
                    "NOT_VALIDATED_UNSUPPORTED_COORDINATE"
                )
                assert analysis.status == AnalysisStatus.BLOCKED
                assert step.status == StepStatus.BLOCKED
                assert step.error_code == "VCF_REFERENCE_MISMATCH"
                assert step.metadata_json["next_step"] == "REFERENCE_OR_INPUT_REVIEW"
                assert normalized is None
                blocked_event = db.scalar(select(AuditEvent).where(
                    AuditEvent.analysis_id == analysis_id,
                    AuditEvent.event_type == "NORMALIZATION_BLOCKED",
                ))
                assert blocked_event is not None
                assert {item["artifact_id"] for item in blocked_event.output_artifacts} == {
                    str(block_artifact.id), str(star_artifact.id), str(sv_artifact.id),
                    str(telomere_artifact.id),
                    str(telomere_after_artifact.id),
                    str(exclusion_manifest.id),
                }
                assert set(step.output_artifacts) == {
                    str(block_artifact.id), str(star_artifact.id), str(sv_artifact.id),
                    str(telomere_artifact.id), str(telomere_after_artifact.id),
                    str(exclusion_manifest.id),
                }
            else:
                for artifact in (block_artifact, star_artifact, sv_artifact):
                    assert artifact.metadata_json["reference_validation_status"] == "PASS"
                    assert artifact.metadata_json["reference_package_id"] == str(resource_id)
                    assert artifact.metadata_json["reference_package_version"] == "fixture-1"
                    assert artifact.metadata_json["reference_fasta_sha256"] == "b" * 64
                assert telomere_artifact.metadata_json["reference_validation_status"] == (
                    "NOT_VALIDATED_UNSUPPORTED_COORDINATE"
                )
                assert telomere_artifact.metadata_json["reference_validation_reason_code"] == (
                    "VCF_TELOMERE_COORDINATE_UNSUPPORTED"
                )
                assert telomere_after_artifact.metadata_json["reference_validation_status"] == (
                    "NOT_VALIDATED_UNSUPPORTED_COORDINATE"
                )
                assert step.status == StepStatus.SUCCEEDED, (step.error_code, step.error_message, step.metadata_json)
                assert step.metadata_json["record_count"] == 2
                assert step.metadata_json["source_record_count"] == 7
                assert step.metadata_json["routing"]["gvcf_reference_blocks"] == 1
                assert step.metadata_json["routing"]["sequence_records"] == 2
                assert step.metadata_json["routing"]["spanning_deletion_records"] == 1
                assert step.metadata_json["routing"]["structural_variant_records"] == 1
                assert step.metadata_json["routing"]["telomere_records"] == 1
                assert step.metadata_json["routing"]["telomere_after_contig_records"] == 1
                assert step.metadata_json["source_reference_allele_profile"]["result"] == "PARTIAL"
                assert step.metadata_json["source_reference_allele_profile"]["checked_record_count"] == 5
                assert step.metadata_json["source_reference_allele_profile"]["unvalidated_telomere_record_count"] == 2
                assert normalized is not None and store.exists(normalized.storage_uri)
                assert sha256(store.read_bytes(normalized.storage_uri)).hexdigest() == normalized.sha256
                assert normalized.metadata_json["source_artifact_id"] == str(input_artifact.id)
                assert normalized.metadata_json["source_record_count"] == 7
                assert normalized.metadata_json["normalization_tool_version"] == "bcftools 1.25"
                assert normalized.metadata_json["normalization_provider_resource_id"] == str(normalization_resource_id)
                assert normalized.metadata_json["normalization_provider_version"] == "1.25"
                assert normalized.metadata_json["normalization_executable_identity"]["sha256"] == "f" * 64
                assert normalized.metadata_json["normalization_executable_integrity_status"] == "MATCHED_QUALIFIED_SHA256"
                executions = db.scalars(select(ResourceExecutionRecord).where(
                    ResourceExecutionRecord.analysis_id == analysis_id,
                    ResourceExecutionRecord.resource_id == normalization_resource_id,
                )).all()
                assert len(executions) == (2 if worker_loss else 1)
                for execution in executions:
                    assert execution.status == "SUCCEEDED"
                    assert execution.qualification_id == qualification_id
                    assert execution.contract_json["toolchain"]["bcftools"]["sha256"] == "f" * 64
                    assert execution.metadata_json["executable_identity"]["sha256"] == "f" * 64
                    assert execution.response_sha256 == normalized.sha256
                assert str(exclusion_manifest.id) in step.output_artifacts
                assert str(exclusion_manifest.id) in step.metadata_json["exclusion_manifest_artifact_ids"]
                if worker_loss:
                    assert normalization_calls["count"] == 2
                    normalized_rows = db.scalars(select(Artifact).where(
                        Artifact.analysis_id == analysis_id,
                        Artifact.artifact_type == "NORMALIZED_VCF",
                    )).all()
                    completed_events = db.scalars(select(AuditEvent).where(
                        AuditEvent.analysis_id == analysis_id,
                        AuditEvent.event_type == "NORMALIZATION_COMPLETED",
                    )).all()
                    recovery_events = db.scalars(select(AuditEvent).where(
                        AuditEvent.analysis_id == analysis_id,
                        AuditEvent.event_type == "WORKFLOW_WORKER_RECOVERY",
                    )).all()
                    assert len(normalized_rows) == 1
                    assert len(completed_events) == 1
                    assert len(recovery_events) == 1
                    assert recovery_events[0].payload["recovered_steps"] == ["normalize"]
                assert normalized.metadata_json["record_count"] == 2
                assert normalized.metadata_json["source_reference_allele_profile"]["checked_record_count"] == 5
                if used_real_bcftools:
                    assert "bcftools view --no-version -A" in normalized.metadata_json["normalization_command"]
                    assert normalized.metadata_json["normalization_version"] == "6.0"
                    partition = db.scalar(select(AnalysisPartition).where(
                        AnalysisPartition.analysis_id == analysis_id,
                        AnalysisPartition.step_id == "normalize",
                    ))
                    assert partition is not None
                    source_mappings = partition.metadata_json["source_record_mappings"]
                    assert [
                        (item["source_position"], item["source_reference"],
                         item["source_alternate"], item["source_alt_index"])
                        for item in source_mappings
                    ] == [(11, "A", "C", 1), (20, "AT", "A", 1)]
                    normalized_text = gzip.decompress(store.read_bytes(normalized.storage_uri)).decode("utf-8")
                    normalized_records = [
                        line.split("\t") for line in normalized_text.splitlines()
                        if line and not line.startswith("#")
                    ]
                    called_variant = next(record for record in normalized_records if record[1] == "11")
                    assert called_variant[4] == "C"
                    assert called_variant[8] == "GT:AD:PL:SIRALOOM_SOURCE_GT:SIRALOOM_SOURCE_ALT_COUNT"
                    assert called_variant[9] == "0/1:15,9:100,50,60:0/1:1"
                assert analysis.status == AnalysisStatus.BLOCKED
                annotation = db.scalar(select(WorkflowStep).where(
                    WorkflowStep.analysis_id == analysis_id,
                    WorkflowStep.step_id == "annotate",
                ))
                assert annotation.error_code == "ANNOTATION_PROVIDER_UNAVAILABLE"
                assert db.scalar(select(Variant).where(
                    Variant.position == 11,
                    Variant.reference == "A",
                    Variant.alternate == "C",
                )) is not None
                assert db.scalar(select(AuditEvent).where(
                    AuditEvent.analysis_id == analysis_id,
                    AuditEvent.event_type == "NORMALIZATION_BLOCKED",
                )) is None
                # The worker materialized each sequence-resolved variant only
                # after reference-aware normalization succeeded.
                assert db.scalar(select(Variant).where(
                    Variant.position == 11,
                    Variant.reference == "A",
                    Variant.alternate == "C",
                )) is not None
                assert db.scalar(select(Variant).where(
                    Variant.position == 20,
                    Variant.reference == "AT",
                    Variant.alternate == "A",
                )) is not None
            # The original source remains immutable and retains all source records.
            original = db.get(Artifact, input_artifact.id)
            assert store.exists(original.storage_uri)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("approval_state", "expected_code", "expected_next_step"),
    [
        (
            "ABSENT",
            "VCF_SPECIFICATION_RELEASE_NOT_REGISTERED",
            "OFFICIAL_SPECIFICATION_DISCOVERY_AND_QUALIFICATION_REQUIRED",
        ),
        (
            "UNQUALIFIED",
            "VCF_SPECIFICATION_QUALIFICATION_REQUIRED",
            "PARSER_CONFORMANCE_QUALIFICATION_REQUIRED",
        ),
        (
            "PENDING",
            "VCF_SPECIFICATION_LAB_APPROVAL_PENDING",
            "LAB_APPROVAL_REQUIRED",
        ),
        (
            "REJECTED",
            "VCF_SPECIFICATION_LAB_APPROVAL_REJECTED",
            "PREVIOUSLY_APPROVED_SPECIFICATION_RETAINED",
        ),
        (
            "APPROVED",
            "VCF_SPECIFICATION_PARSER_NOT_IMPLEMENTED",
            "PARSER_IMPLEMENTATION_AND_CONFORMANCE_REQUIRED",
        ),
    ],
)
def test_production_worker_audits_future_vcf_specification_governance_and_parser_state(
    monkeypatch, tmp_path, approval_state, expected_code, expected_next_step
):
    """Exercise real-worker gating for absent, unqualified, pending, rejected and approved VCFv4.6."""
    import importlib

    workflow = importlib.import_module("backend.app.workflows.variant")
    from backend.app.domain.resources import (
        decide_resource_approval,
        request_resource_approval,
        require_approved_vcf_specification,
    )
    from backend.app.infrastructure.db.models import ResourceApproval, ResourceQualification
    db_module = importlib.import_module("backend.app.infrastructure.db.session")

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / (approval_state.lower() + '-vcf-spec.db')}")
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)
    store = ArtifactStore(tmp_path / "artifacts")
    organization_id, user_id, case_id, analysis_id = uuid4(), uuid4(), uuid4(), uuid4()
    source = tmp_path / f"{approval_state.lower()}-future.vcf"
    source.write_text(
        "##fileformat=VCFv4.6\n"
        "##contig=<ID=1,length=1000>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    try:
        with local_session() as db:
            db.add(Organization(id=organization_id, name="Future VCF Governance Lab"))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="Future VCF Test",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"VCF-SPEC-{analysis_id}",
                status="ACTIVE",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.flush()
            artifact = store.put_file(
                db=db,
                case_id=case_id,
                analysis_id=analysis_id,
                source_path=source,
                filename=source.name,
                artifact_type="SOURCE_VCF",
                media_type="text/plain",
                genome_build="GRCh38",
                metadata={},
                validation_status="VALID",
            )
            db.add(Analysis(
                id=analysis_id,
                case_id=case_id,
                parent_analysis_id=None,
                assay_id=None,
                analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1",
                workflow_version="test",
                status=AnalysisStatus.QUEUED,
                queue_task_id=f"vcf-spec-{approval_state.lower()}",
                reference_build="GRCh38",
                configuration={"input_artifact_id": str(artifact.id)},
                started_at=None,
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))
            if approval_state != "ABSENT":
                specification = Resource(
                    id=uuid4(),
                    organization_id=None,
                    name="VCF specification VCFv4.6",
                    provider="HTS-Specifications",
                    resource_type="VCF_SPECIFICATION",
                    version="VCFv4.6",
                    genome_build=None,
                    access_method="HTTPS",
                    license_text=None,
                    checksum="a" * 64,
                    location="https://samtools.github.io/hts-specs/VCFv4.6.pdf",
                    status="CANDIDATE" if approval_state == "UNQUALIFIED" else "QUALIFIED",
                    population_definition=None,
                    metadata_json={},
                )
                qualification = ResourceQualification(
                    id=uuid4(),
                    resource_id=specification.id,
                    qualification_version="vcf-spec-qualification-v1",
                    status="BLOCKED" if approval_state == "UNQUALIFIED" else "QUALIFIED",
                    checks_json={"vcf_specification": {"status": "BLOCKED" if approval_state == "UNQUALIFIED" else "QUALIFIED"}},
                    qualified_by=None,
                )
                db.add_all([specification, qualification])
                if approval_state != "UNQUALIFIED":
                    approval = request_resource_approval(
                        db,
                        resource_id=specification.id,
                        organization_id=organization_id,
                        qualification_version="vcf-spec-qualification-v1",
                        actor_id=user_id,
                    )
                db.flush()
                if approval_state in {"REJECTED", "APPROVED"}:
                    decide_resource_approval(
                        db,
                        approval_id=approval.id,
                        organization_id=organization_id,
                        actor_id=user_id,
                        decision=approval_state,
                        expected_version=1,
                        reason=f"Test laboratory decision: {approval_state}",
                    )
                db.commit()
                approval_snapshot = (
                    require_approved_vcf_specification(
                        db,
                        organization_id=organization_id,
                        version="VCFv4.6",
                    )
                    if approval_state == "APPROVED"
                    else None
                )
            else:
                db.commit()

        monkeypatch.setattr(db_module, "SessionLocal", local_session)
        monkeypatch.setattr(workflow, "artifact_store_for_organization", lambda *_a, **_k: store)
        monkeypatch.setattr(workflow, "artifact_store_for_uri", lambda *_a, **_k: store)
        # The standalone header-reader has dedicated plain/BGZF tests. Pin the
        # workflow boundary's declared version so this test isolates approval
        # routing after artifact materialization.
        monkeypatch.setattr(workflow, "read_vcf_fileformat", lambda _path: "VCFv4.6")

        if approval_state in {"ABSENT", "UNQUALIFIED", "PENDING", "REJECTED"}:
            def parser_must_not_run(*_args, **_kwargs):
                raise AssertionError("strict parser must not run before laboratory approval")

            monkeypatch.setattr(workflow, "validate_vcf_strict", parser_must_not_run)

        workflow.run_variant_analysis(analysis_id)

        with local_session() as db:
            analysis = db.get(Analysis, analysis_id)
            validation = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "validate_input",
            ))
            event = db.scalar(select(AuditEvent).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "WORKFLOW_BLOCKED",
            ))
            assert analysis.status == AnalysisStatus.BLOCKED
            assert validation.status == StepStatus.BLOCKED
            assert validation.error_code == expected_code
            assert validation.metadata_json["detected_vcf_version"] == "VCFv4.6" if approval_state == "APPROVED" else validation.metadata_json["vcf_specification_approval"]["version"] == "VCFv4.6"
            assert validation.metadata_json["next_step"] == expected_next_step
            assert event is not None
            assert event.payload["error_code"] == expected_code
            assert event.payload["vcf_version"] == "VCFv4.6"
            if approval_state in {"PENDING", "REJECTED", "APPROVED"}:
                approval_row = db.scalar(select(ResourceApproval).where(
                    ResourceApproval.resource_id == specification.id,
                    ResourceApproval.organization_id == organization_id,
                ))
                assert approval_row is not None
                assert approval_row.status == approval_state
                adoption_event_type = (
                    "RESOURCE_ADOPTION_REQUESTED"
                    if approval_state == "PENDING"
                    else "RESOURCE_ADOPTION_DECISION"
                )
                adoption_event = db.scalar(select(AuditEvent).where(
                    AuditEvent.subject_id == str(specification.id),
                    AuditEvent.event_type == adoption_event_type,
                ))
                assert adoption_event is not None
                if approval_state == "PENDING":
                    assert adoption_event.after_state["approval_id"] == str(approval_row.id)
                    assert adoption_event.after_state["status"] == "PENDING"
                else:
                    assert adoption_event.payload["approval_id"] == str(approval_row.id)
                    assert adoption_event.payload["decision"] == approval_state
            else:
                assert db.scalar(select(ResourceApproval)) is None
            # A governance/parser block is terminal before any scientific
            # transformation: normalization, variant materialization and
            # downstream annotation must not have started.
            normalization = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "normalize",
            ))
            assert normalization is not None
            assert normalization.status not in {StepStatus.RUNNING, StepStatus.SUCCEEDED}
            assert db.scalar(select(Artifact).where(
                Artifact.analysis_id == analysis_id,
                Artifact.artifact_type == "NORMALIZED_VCF",
            )) is None
            # Variant rows are global canonical identities and do not
            # carry a case/analysis foreign key. The isolated database must
            # remain empty because the blocked workflow cannot materialize one.
            assert db.scalar(select(Variant)) is None
            assert db.scalar(select(AuditEvent).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "ARTIFACT_VALIDATED",
            )) is None
            if approval_state == "APPROVED":
                assert validation.metadata_json["parser_support"] == "NOT_IMPLEMENTED"
                assert validation.metadata_json["vcf_specification_approval"] == approval_snapshot
                assert event.payload["laboratory_approval"] == approval_snapshot
            else:
                assert validation.metadata_json["vcf_specification_approval"]["status"] == expected_code
                if approval_state == "ABSENT":
                    assert "no registered qualified release" in validation.error_message.lower()
                elif approval_state == "UNQUALIFIED":
                    assert "not qualified for laboratory use" in validation.error_message.lower()
                else:
                    assert approval_state.lower() in validation.error_message.lower() or (
                        approval_state == "PENDING" and "awaiting" in validation.error_message.lower()
                    )
    finally:
        engine.dispose()


def test_artifact_store_rejects_different_bytes_for_same_artifact_identity(tmp_path):
    import hashlib

    from backend.app.infrastructure.artifacts.store import ArtifactIdentityConflictError

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'artifact-conflict.db'}")
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)
    store = ArtifactStore(tmp_path / "artifact-store")
    case_id, analysis_id, artifact_id = uuid4(), uuid4(), uuid4()
    first = tmp_path / "first.vcf.gz"
    second = tmp_path / "second.vcf.gz"
    first.write_bytes(b"first normalized VCF bytes")
    second.write_bytes(b"different normalized VCF bytes")

    with local_session() as db:
        first_artifact = store.put_file(
            db=db,
            case_id=case_id,
            analysis_id=analysis_id,
            source_path=first,
            filename="normalized.vcf.gz",
            artifact_type="NORMALIZED_VCF",
            media_type="application/gzip",
            genome_build="GRCh38",
            artifact_id=artifact_id,
        )
        db.commit()
        assert first_artifact.sha256 == hashlib.sha256(first.read_bytes()).hexdigest()
        replayed_artifact = store.put_file(
            db=db,
            case_id=case_id,
            analysis_id=analysis_id,
            source_path=first,
            filename="normalized.vcf.gz",
            artifact_type="NORMALIZED_VCF",
            media_type="application/gzip",
            genome_build="GRCh38",
            artifact_id=artifact_id,
        )
        assert replayed_artifact.id == first_artifact.id
        assert replayed_artifact.sha256 == first_artifact.sha256

        with pytest.raises(ArtifactIdentityConflictError) as exc:
            store.put_file(
                db=db,
                case_id=case_id,
                analysis_id=analysis_id,
                source_path=second,
                filename="normalized.vcf.gz",
                artifact_type="NORMALIZED_VCF",
                media_type="application/gzip",
                genome_build="GRCh38",
                artifact_id=artifact_id,
            )

    assert exc.value.code == "ARTIFACT_IDENTITY_CONFLICT"
    engine.dispose()
