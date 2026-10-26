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
    Artifact,
    AuditEvent,
    Case,
    Organization,
    Resource,
    User,
    Variant,
    WorkflowStep,
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
                assert event.output_artifacts == []
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
    ("reference_mismatch", "worker_loss"),
    [(False, False), (True, False), (False, True)],
)
def test_production_worker_normalizes_called_variant_from_gvcf_and_preserves_block(
    monkeypatch, tmp_path, reference_mismatch, worker_loss
):
    """Exercise routing, reference validation, normalization persistence, and variant indexing in the worker."""
    import gzip
    import importlib
    from types import SimpleNamespace

    from backend.app.domain.vcf_tools import bcftools_available

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
            assert "A\tC,<NON_REF>" in routed_text
            assert "AT\tA" in routed_text
            assert "\t*\t" not in routed_text
            assert "\t0\ttelo1\t" not in routed_text
            assert "\t1001\ttelo-after\t" not in routed_text
            assert "<NON_REF>\t.\tPASS\tEND=10" not in routed_text
            index = Path(str(output_path) + ".csi")
            with gzip.open(output_path, "wt", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    "##fileformat=VCFv4.3\n##contig=<ID=1,length=1000>\n"
                    '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
                    '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths">\n'
                    '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Phred likelihoods">\n'
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
                    "1\t11\trs1\tA\tC\t50\tPASS\tDP=24\tGT:AD:PL\t0/1:15,9:100,50,60\n"
                    "1\t20\tdel1\tAT\tA\t50\tPASS\t.\tGT:AD:PL\t0/1:10,10:0,20,200\n"
                )
            index.write_bytes(b"fixture-csi")
            return {
                "tool": "bcftools", "tool_version": "bcftools 1.19",
                "expected_tool_version": "1.19", "operation": "fixture-normalization",
                "command": "bcftools view -A && bcftools norm -f ref.fa -c e -m -any",
                "compression": "BGZF", "index": "CSI", "index_path": str(index),
            }

        used_real_bcftools = bcftools_available()
        if worker_loss and not used_real_bcftools:
            pytest.skip("normalization worker-loss recovery requires pinned BCFtools")
        if not used_real_bcftools:
            monkeypatch.setattr(workflow, "normalize_vcf_with_bcftools", fake_normalize)
        if worker_loss:
            queue_module = importlib.import_module(
                "backend.app.infrastructure.queue.celery_app"
            )
            monkeypatch.setattr(db_module, "engine", engine)
            task_id = "gvcf-positive-test"
            normalized_id = uuid5(
                analysis_id, "siraloom:normalization:normalized-vcf:v3"
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
            original_normalize = workflow.normalize_vcf_with_bcftools

            def count_real_normalization(*args, **kwargs):
                normalization_calls["count"] += 1
                return original_normalize(*args, **kwargs)

            monkeypatch.setattr(
                workflow, "normalize_vcf_with_bcftools", count_real_normalization
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
            analysis = db.get(Analysis, analysis_id)
            assert block_artifact is not None and store.exists(block_artifact.storage_uri)
            assert star_artifact is not None and store.exists(star_artifact.storage_uri)
            assert sv_artifact is not None and store.exists(sv_artifact.storage_uri)
            assert telomere_artifact is not None and store.exists(telomere_artifact.storage_uri)
            assert telomere_after_artifact is not None and store.exists(telomere_after_artifact.storage_uri)
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
                }
                assert set(step.output_artifacts) == {
                    str(block_artifact.id), str(star_artifact.id), str(sv_artifact.id),
                    str(telomere_artifact.id), str(telomere_after_artifact.id),
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
                assert normalized.metadata_json["normalization_tool_version"] == "bcftools 1.19"
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
                    assert "bcftools view -A" in normalized.metadata_json["normalization_command"]
                    normalized_text = gzip.decompress(store.read_bytes(normalized.storage_uri)).decode("utf-8")
                    normalized_records = [
                        line.split("\t") for line in normalized_text.splitlines()
                        if line and not line.startswith("#")
                    ]
                    called_variant = next(record for record in normalized_records if record[1] == "11")
                    assert called_variant[4] == "C"
                    assert called_variant[8] == "GT:AD:PL"
                    assert called_variant[9] == "0/1:15,9:100,50,60"
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
