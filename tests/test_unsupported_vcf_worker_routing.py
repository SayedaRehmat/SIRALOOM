from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.domain.workflow_decision import WorkflowAction, WorkflowDecision
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    Artifact,
    AuditEvent,
    Case,
    Organization,
    Resource,
    User,
    Variant,
    WorkflowStep,
)
from backend.app.domain.vcf_tools import VCFToolError


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
    ("filename", "vcf", "artifact_type", "count_key"),
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
        ),
    ],
)
def test_production_worker_preserves_valid_non_sequence_records_for_review(
    monkeypatch, tmp_path, filename, vcf, artifact_type, count_key
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
            assert normalization.metadata_json["routing"][count_key] > 0
            assert routed is not None
            assert routed.metadata_json["source_artifact_id"] == str(source_row.id)
            assert routed.metadata_json["source_sha256"] == source_sha256
            assert routed.metadata_json["record_count"] == normalization.metadata_json["routing"][count_key]
            assert store.exists(source_row.storage_uri)
            assert store.exists(routed.storage_uri)
            assert event.payload["routing"][count_key] > 0
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


@pytest.mark.parametrize("reference_mismatch", [False, True])
def test_production_worker_normalizes_called_variant_from_gvcf_and_preserves_block(
    monkeypatch, tmp_path, reference_mismatch
):
    """Exercise routing, reference validation, normalization persistence, and variant indexing in the worker."""
    import gzip
    import importlib
    from types import SimpleNamespace

    workflow = importlib.import_module("backend.app.workflows.variant")
    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'gvcf-positive.db'}")
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)
    store = ArtifactStore(tmp_path / "artifacts")
    organization_id, user_id, case_id, analysis_id, resource_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    sequence = "A" * 20 + "T" + "A" * 979
    fasta = tmp_path / "reference.fa"
    fasta.write_text(f">1\n{sequence}\n", encoding="utf-8")
    fai = tmp_path / "reference.fa.fai"
    fai.write_text(f"1\t{len(sequence)}\t3\t{len(sequence)}\t{len(sequence)+1}\n", encoding="utf-8")
    source = tmp_path / "sample.g.vcf"
    source.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=1000>\n"
        '##ALT=<ID=NON_REF,Description="Any possible alternate allele">\n'
        "##INFO=<ID=DP,Number=1,Type=Integer,Description=Depth>\n"
        "##FORMAT=<ID=GT,Number=1,Type=String,Description=Genotype>\n"
        "##FORMAT=<ID=AD,Number=R,Type=Integer,Description=Allelic depths>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
        "1\t1\t.\tA\t<NON_REF>\t.\tPASS\tEND=10;DP=30\tGT:AD\t0/0:30,0\n"
        f"1\t11\trs1\t{'G' if reference_mismatch else 'A'}\tC,<NON_REF>\t50\tPASS\tDP=24\tGT:AD\t0/1:15,9,0\n"
        "1\t20\tdel1\tAT\tA\t50\tPASS\t.\tGT:AD\t0/1:10,10\n"
        "1\t21\tstar1\tT\t*\t50\tPASS\t.\tGT:AD\t0/1:10,10\n",
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
            db.add(Analysis(
                id=analysis_id, case_id=case_id, parent_analysis_id=None,
                assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1", workflow_version="test",
                status=AnalysisStatus.QUEUED, queue_task_id="gvcf-positive-test",
                reference_build="GRCh38",
                configuration={
                    "input_artifact_id": str(input_artifact.id),
                    "reference_resource_id": str(resource_id),
                },
                started_at=None, completed_at=None, created_by=user_id,
                analysis_version=1,
            ))
            db.commit()

        monkeypatch.setattr(db_module, "SessionLocal", local_session)
        monkeypatch.setattr(workflow, "artifact_store_for_organization", lambda *_a, **_k: store)
        decision = WorkflowDecision(WorkflowAction.CONTINUE, "TEST_REFERENCE_SELECTED", "Fixture reference selected")
        monkeypatch.setattr(workflow, "resolve_resource_with_fallback", lambda db, **_k: SimpleNamespace(
            resource=db.get(Resource, resource_id), used_fallback=False,
            requested_resource_id=resource_id, fallback_resource_id=None, decision=decision,
        ))
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
        monkeypatch.setattr(workflow, "start_resource_execution", lambda *_a, **_k: SimpleNamespace())
        monkeypatch.setattr(workflow, "complete_resource_execution", lambda *_a, **_k: None)

        def fake_normalize(input_path, output_path, **kwargs):
            routed_text = Path(input_path).read_text(encoding="utf-8")
            assert ("G\tC,<NON_REF>" if reference_mismatch else "A\tC,<NON_REF>") in routed_text
            assert "AT\tA" in routed_text
            assert "\t*\t" not in routed_text
            assert "<NON_REF>\t.\tPASS\tEND=10" not in routed_text
            if reference_mismatch:
                raise VCFToolError(
                    "bcftools reference-aware normalization failed (exit 1): REF allele mismatch"
                )
            index = Path(str(output_path) + ".csi")
            with gzip.open(output_path, "wt", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    "##fileformat=VCFv4.3\n##contig=<ID=1,length=1000>\n"
                    "##FORMAT=<ID=GT,Number=1,Type=String,Description=Genotype>\n"
                    "##FORMAT=<ID=AD,Number=R,Type=Integer,Description=Allelic depths>\n"
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
                    "1\t11\trs1\tA\tC\t50\tPASS\tDP=24\tGT:AD\t0/1:15,9\n"
                    "1\t20\tdel1\tAT\tA\t50\tPASS\t.\tGT:AD\t0/1:10,10\n"
                )
            index.write_bytes(b"fixture-csi")
            return {
                "tool": "bcftools", "tool_version": "bcftools 1.19",
                "expected_tool_version": "1.19", "operation": "fixture-normalization",
                "command": "bcftools view -A && bcftools norm -f ref.fa -c e -m -any",
                "compression": "BGZF", "index": "CSI", "index_path": str(index),
            }

        monkeypatch.setattr(workflow, "normalize_vcf_with_bcftools", fake_normalize)
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
            analysis = db.get(Analysis, analysis_id)
            assert block_artifact is not None and store.exists(block_artifact.storage_uri)
            assert star_artifact is not None and store.exists(star_artifact.storage_uri)
            assert block_artifact.metadata_json["source_artifact_id"] == str(input_artifact.id)
            assert star_artifact.metadata_json["source_sha256"] == input_artifact.sha256
            assert block_artifact.metadata_json["record_count"] == 1
            assert star_artifact.metadata_json["record_count"] == 1
            assert sha256(store.read_bytes(block_artifact.storage_uri)).hexdigest() == block_artifact.sha256
            assert sha256(store.read_bytes(star_artifact.storage_uri)).hexdigest() == star_artifact.sha256
            assert "END=10" in store.read_bytes(block_artifact.storage_uri).decode("utf-8")
            assert "\t*\t" in store.read_bytes(star_artifact.storage_uri).decode("utf-8")
            if reference_mismatch:
                assert analysis.status == AnalysisStatus.FAILED
                assert step.status == StepStatus.FAILED
                assert step.error_code == "NORMALIZATION_FAILED"
                assert normalized is None
                assert db.scalar(select(AuditEvent).where(
                    AuditEvent.analysis_id == analysis_id,
                    AuditEvent.event_type == "NORMALIZATION_FAILED",
                )) is not None
            else:
                assert step.status == StepStatus.SUCCEEDED
                assert step.metadata_json["record_count"] == 2
                assert step.metadata_json["source_record_count"] == 4
                assert step.metadata_json["routing"]["gvcf_reference_blocks"] == 1
                assert step.metadata_json["routing"]["sequence_records"] == 2
                assert step.metadata_json["routing"]["spanning_deletion_records"] == 1
                assert normalized is not None and store.exists(normalized.storage_uri)
                assert sha256(store.read_bytes(normalized.storage_uri)).hexdigest() == normalized.sha256
                assert normalized.metadata_json["source_artifact_id"] == str(input_artifact.id)
                assert normalized.metadata_json["source_record_count"] == 4
                assert normalized.metadata_json["normalization_tool_version"] == "bcftools 1.19"
                assert normalized.metadata_json["record_count"] == 2
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
