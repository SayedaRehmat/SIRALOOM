"""Exercise population, evidence, and ACMG stage replay after durable commits."""
import gzip
import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from backend.app.adapters.phenotype.hpo_obo import HPOOboProvider
from backend.app.adapters.phenotype.hpoa import HPOAProvider
from backend.app.adapters.population.gnomad import PopulationObservationData
from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.domain.resource_execution import resolve_resource_execution
from backend.app.domain.resource_source_contract import ResourceExecutionContract
from backend.app.domain.variant_identity import canonical_key, stable_variant_uuid
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    ACMGSourceAssertion,
    Analysis,
    Annotation,
    AuditEvent,
    Case,
    Classification,
    ClinGenSpecification,
    Evidence,
    Organization,
    PhenotypeObservation,
    PopulationObservation,
    Resource,
    ResourceExecutionRecord,
    ResourceQualification,
    User,
    Variant,
    WorkflowStep,
)


@pytest.mark.parametrize(
    (
        "no_match",
        "ontology_valid",
        "hpoa_license",
        "inject_internal_evidence_error",
        "inject_clingen_provider_error",
        "inject_hpo_resource_resolution_error",
    ),
    [
        (False, True, True, False, False, None),
        (True, True, True, False, False, None),
        (False, False, True, False, False, None),
        (True, False, True, False, False, None),
        (False, True, False, False, False, None),
        (True, True, False, False, False, None),
        (False, False, False, False, False, None),
        (True, False, False, False, False, None),
        (False, True, True, True, False, None),
        (False, True, True, False, True, None),
        (False, True, True, False, False, "PHENOTYPE_ONTOLOGY"),
        (False, True, True, False, False, "DISEASE_PHENOTYPE_ASSOCIATION"),
    ],
    ids=[
        "available-frequency-licensed-hpoa-hpo-ready",
        "no-match-licensed-hpoa-hpo-ready",
        "available-frequency-licensed-hpoa-ontology-failure",
        "no-match-ontology-failure-licensed-hpoa",
        "available-frequency-unlicensed-hpoa",
        "no-match-unlicensed-hpoa",
        "ontology-failure-unlicensed-hpoa",
        "no-match-ontology-failure-unlicensed-hpoa",
        "internal-evidence-builder-failure-is-not-provider-limitation",
        "typed-clingen-provider-failure-is-recorded-as-limitation",
        "internal-hpo-ontology-resolution-error-is-not-resource-limitation",
        "internal-hpoa-resolution-error-is-not-resource-limitation",
    ],
)
def test_real_workflow_recovers_population_evidence_and_acmg_after_commits(
    monkeypatch, tmp_path, no_match, ontology_valid, hpoa_license,
    inject_internal_evidence_error, inject_clingen_provider_error,
    inject_hpo_resource_resolution_error,
):
    import importlib

    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    workflow = importlib.import_module("backend.app.workflows.variant")
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'population-redelivery.db'}")
    Base.metadata.create_all(engine)
    LocalSession = sessionmaker(bind=engine, expire_on_commit=False)
    store = ArtifactStore(tmp_path / "artifacts")
    clingen_enabled = not no_match and ontology_valid and hpoa_license
    organization_id, user_id, case_id, analysis_id, resource_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    secondary_resource_id, secondary_qualification_id = uuid4(), uuid4()
    clinvar_resource_id = uuid4()
    hpo_resource_id, hpo_qualification_id = uuid4(), uuid4()
    hpoa_resource_id, hpoa_qualification_id = uuid4(), uuid4()
    clingen_vp_resource_id, clingen_vp_qualification_id = uuid4(), uuid4()
    clingen_gdv_resource_id, clingen_gdv_qualification_id = uuid4(), uuid4()
    hpo_path = tmp_path / "hp.obo"
    hpo_path.write_text(
        "format-version: 1.2\n"
        "data-version: hp/releases/2026-09-01/hp-base.owl\n\n"
        "ontology: hp.obo\n\n"
        "[Term]\nid: HP:0000001\nname: Root\n\n"
        "[Term]\nid: HP:0000002\nname: Parent\nis_a: HP:0000001 ! Root\n\n"
        "[Term]\nid: HP:0000003\nname: Child\nis_a: HP:0000002 {xref=\"PMID:1\"} ! Parent\n"
        "\n[Term]\nid: HP:0000004\nname: Absent finding\n"
        "\n[Term]\nid: HP:0000005\nname: Excluded finding\n"
        "\n[Term]\nid: HP:0000006\nname: Uncertain finding\n"
        "\n[Term]\nid: HP:0000007\nname: Unassessed finding\n",
        encoding="utf-8",
    )
    hpo_checksum = hashlib.sha256(hpo_path.read_bytes()).hexdigest()
    hpoa_path = tmp_path / "phenotype.hpoa"
    hpoa_path.write_text(
        "#version: 2026-09-02\n"
        "#hpo-version: http://purl.obolibrary.org/obo/hp/releases/2026-09-01/hp.json\n"
        "database_id\tdisease_name\tqualifier\thpo_id\treference\tevidence\t"
        "onset\tfrequency\tsex\tmodifier\taspect\tbiocuration\n"
        "MONDO:0000001\tDisease X\t\tHP:0000003\tPMID:123\tPCS\t"
        "\t1/2\t\t\tP\tHPO:curator[2026-01-01]\n"
        "MONDO:0000001\tDisease X\tNOT\tHP:0000004\tPMID:124\tTAS\t"
        "\t0/3\t\t\tP\tHPO:curator[2026-01-02]\n",
        encoding="utf-8",
    )
    hpoa_checksum = hashlib.sha256(hpoa_path.read_bytes()).hexdigest()
    clingen_vp_path = tmp_path / "clingen-variant.tsv"
    clingen_gdv_path = tmp_path / "clingen-gene-disease.csv"
    if clingen_enabled:
        clingen_vp_path.write_text(
            "gene\thgvs\tclassification\tcondition\tmoi\texpert_panel\tmet_codes\tunmet_codes\tversion\n"
            "GENE1\tNM_TEST.1:c.555T>C\tPathogenic\tDisease X\tAutosomal recessive\tFixture VCEP\tPM2\t\tfixture-v1\n",
            encoding="utf-8",
        )
        clingen_gdv_path.write_text(
            "GENE SYMBOL,GENE ID (HGNC),DISEASE LABEL,DISEASE ID (MONDO),MOI,SOP,CLASSIFICATION,ONLINE REPORT,CLASSIFICATION DATE,GCEP\n"
            "GENE1,HGNC:1,Disease X,MONDO:0000001,Autosomal recessive,6,Definitive,https://example.test/report/fixture,2026-09-01,Fixture GCEP\n",
            encoding="utf-8",
        )
    variant_key = canonical_key("GRCh38", "1", 555, "T", "C")
    variant_id = stable_variant_uuid(variant_key)
    provider_calls = {"count": 0}
    clinvar_calls = {"count": 0}

    try:
        source = tmp_path / "source.vcf"
        source.write_text(
            "##fileformat=VCFv4.2\n"
            "##contig=<ID=1,length=1000000>\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
            "1\t555\t.\tT\tC\t.\tPASS\t.\n",
            encoding="utf-8",
        )
        normalized = tmp_path / "normalized.vcf.gz"
        normalized.write_bytes(gzip.compress(source.read_bytes()))

        with LocalSession() as db:
            db.add(Organization(
                id=organization_id,
                name="Population Replay Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="Population Replay Test",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"POP-REPLAY-{case_id}",
                status="OPEN",
                clinical_context=(
                    {
                        "disease": "Disease X" if not no_match else None,
                        "gene_disease_evidence": [{
                            "gene": "GENE1",
                            "disease": "Disease X",
                            "disease_id": "MONDO:0000001",
                            "hpo_terms": ["HP:0000002"],
                        }],
                    }
                ),
                language="en",
                created_by=user_id,
            ))
            db.flush()
            db.add(PhenotypeObservation(
                id=uuid4(),
                case_id=case_id,
                analysis_id=None,
                hpo_id="HP:0000002",
                label="Parent",
                present=True,
                source="CLINICAL_INPUT",
                evidence={},
            ))
            for hpo_id, status in (
                ("HP:0000004", "ABSENT"),
                ("HP:0000005", "EXCLUDED"),
                ("HP:0000006", "UNKNOWN"),
                ("HP:0000007", "NOT_ASSESSED"),
            ):
                db.add(PhenotypeObservation(
                    id=uuid4(),
                    case_id=case_id,
                    analysis_id=None,
                    hpo_id=hpo_id,
                    label=status.title(),
                    present=False,
                    phenotype_status=status,
                    source="CLINICAL_INPUT",
                    evidence={},
                ))
            db.flush()
            source_artifact = store.put_file(
                db=db,
                case_id=case_id,
                analysis_id=analysis_id,
                source_path=source,
                filename="source.vcf",
                artifact_type="SOURCE_VCF",
                media_type="text/plain",
                genome_build="GRCh38",
                metadata={},
            )
            normalized_artifact = store.put_file(
                db=db,
                case_id=case_id,
                analysis_id=analysis_id,
                source_path=normalized,
                filename="normalized.vcf.gz",
                artifact_type="NORMALIZED_VCF",
                media_type="application/gzip",
                genome_build="GRCh38",
                metadata={},
            )
            db.flush()
            db.add(Analysis(
                id=analysis_id,
                case_id=case_id,
                parent_analysis_id=None,
                assay_id=None,
                analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1",
                workflow_version="test",
                status=AnalysisStatus.RUNNING,
                queue_task_id="population-replay-test",
                reference_build="GRCh38",
                configuration={
                    "input_artifact_id": str(source_artifact.id),
                    "clinvar_resource_id": str(clinvar_resource_id),
                },
                started_at=datetime.now(UTC),
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))
            db.flush()
            db.add(Variant(
                id=variant_id,
                genome_build="GRCh38",
                chromosome="1",
                position=555,
                reference="T",
                alternate="C",
                normalization_status="NORMALIZED",
                canonical_key=variant_key,
                identifiers={},
            ))
            resource = Resource(
                id=resource_id,
                organization_id=organization_id,
                name="Fixture population resource",
                provider="fixture-population",
                resource_type="POPULATION",
                version="release-v1",
                genome_build="GRCh38",
                access_method="API",
                license_text=None,
                checksum="a" * 64,
                location="https://fixture.invalid/population",
                status="ACTIVE",
                population_definition=None,
                metadata_json={},
            )
            db.add(resource)
            hpo_resource = Resource(
                id=hpo_resource_id,
                organization_id=organization_id,
                name="Fixture HPO OBO",
                provider="HPO",
                resource_type="PHENOTYPE_ONTOLOGY",
                version="2026-09-01",
                genome_build=None,
                access_method="LOCAL",
                license_text=None,
                checksum=hpo_checksum if ontology_valid else "0" * 64,
                location=str(hpo_path),
                status="ACTIVE",
                population_definition=None,
                metadata_json={},
            )
            db.add(hpo_resource)
            hpoa_resource = Resource(
                id=hpoa_resource_id,
                organization_id=organization_id,
                name="Fixture HPO disease annotations",
                provider="HPOA",
                resource_type="DISEASE_PHENOTYPE_ASSOCIATION",
                version="2026-09-02",
                genome_build=None,
                access_method="LOCAL",
                license_text=("Fixture license declaration" if hpoa_license else None),
                checksum=hpoa_checksum,
                location=str(hpoa_path),
                status="ACTIVE",
                population_definition=None,
                metadata_json={},
            )
            db.add(hpoa_resource)
            db.flush()
            db.add(ResourceQualification(
                id=hpo_qualification_id,
                resource_id=hpo_resource_id,
                qualification_version="fixture-qualification-v1",
                status="QUALIFIED",
                checks_json={"execution_contract": {
                    "provider_id": "HPO",
                    "provider_version": "OBO",
                    "access_method": "LOCAL",
                    "location": str(hpo_path),
                    "dataset": "2026-09-01",
                    "toolchain": {"sha256": hpo_checksum, "release": "2026-09-01"},
                }},
                qualified_by=user_id,
                qualified_at=datetime.now(UTC),
            ))
            db.add(ResourceQualification(
                id=hpoa_qualification_id,
                resource_id=hpoa_resource_id,
                qualification_version="fixture-hpoa-qualification-v1",
                status="QUALIFIED",
                checks_json={"execution_contract": {
                    "provider_id": "HPOA",
                    "provider_version": "HPOA_TSV",
                    "access_method": "LOCAL",
                    "location": str(hpoa_path),
                    "dataset": "2026-09-02",
                    "toolchain": {
                        "sha256": hpoa_checksum,
                        "release": "2026-09-02",
                        "hpo_release": "2026-09-01",
                    },
                }},
                qualified_by=user_id,
                qualified_at=datetime.now(UTC),
            ))
            db.add(Resource(
                id=clinvar_resource_id,
                organization_id=organization_id,
                name="Fixture ClinVar resource",
                provider="NCBI ClinVar",
                resource_type="EVIDENCE",
                version="clinvar-v1",
                genome_build="GRCh38",
                access_method="API",
                license_text=None,
                checksum="f" * 64,
                location="https://fixture.invalid/clinvar",
                status="ACTIVE",
                population_definition=None,
                metadata_json={},
            ))
            if clingen_enabled:
                secondary_vcf_path = tmp_path / "secondary-population.vcf.gz"
                secondary_vcf_path.write_bytes(b"fixture-only tabix resource\n")
                secondary_resource = Resource(
                    id=secondary_resource_id,
                    organization_id=organization_id,
                    name="Fixture secondary population resource",
                    provider="1000GENOMES",
                    resource_type="POPULATION",
                    version="phase3",
                    genome_build="GRCh38",
                    access_method="LOCAL",
                    license_text="Test fixture only",
                    checksum=hashlib.sha256(secondary_vcf_path.read_bytes()).hexdigest(),
                    location=str(secondary_vcf_path),
                    status="ACTIVE",
                    population_definition=None,
                    metadata_json={},
                )
                db.add(secondary_resource)
                secondary_contract = ResourceExecutionContract(
                    provider_id="1000GENOMES",
                    provider_version="phase3",
                    access_method="LOCAL",
                    endpoint=None,
                    location=str(secondary_vcf_path),
                    dataset="phase3",
                    execution_scope="ORGANIZATION_MANAGED",
                    toolchain={
                        "info_fields": {"AC": "AC", "AN": "AN", "AF": "AF"},
                        "population_code": "GLOBAL",
                        "population_label": "1000 Genomes Phase 3",
                    },
                )
                db.add(ResourceQualification(
                    id=secondary_qualification_id,
                    resource_id=secondary_resource_id,
                    qualification_version="fixture-secondary-qualification-v1",
                    status="QUALIFIED",
                    checks_json={"execution_contract": secondary_contract.as_dict()},
                    qualified_by=user_id,
                    qualified_at=datetime.now(UTC),
                ))
                clingen_vp_resource = Resource(
                    id=clingen_vp_resource_id,
                    organization_id=organization_id,
                    name="Fixture ClinGen Variant Pathogenicity",
                    provider="ClinGen Variant Pathogenicity",
                    resource_type="EVIDENCE",
                    version="fixture-v1",
                    genome_build=None,
                    access_method="LOCAL",
                    license_text="Test fixture only",
                    checksum=hashlib.sha256(clingen_vp_path.read_bytes()).hexdigest(),
                    location=str(clingen_vp_path),
                    status="ACTIVE",
                    population_definition=None,
                    metadata_json={},
                )
                clingen_gdv_resource = Resource(
                    id=clingen_gdv_resource_id,
                    organization_id=organization_id,
                    name="Fixture ClinGen Gene-Disease Validity",
                    provider="ClinGen Gene-Disease Validity",
                    resource_type="EVIDENCE",
                    version="fixture-v1",
                    genome_build=None,
                    access_method="LOCAL",
                    license_text="Test fixture only",
                    checksum=hashlib.sha256(clingen_gdv_path.read_bytes()).hexdigest(),
                    location=str(clingen_gdv_path),
                    status="ACTIVE",
                    population_definition=None,
                    metadata_json={},
                )
                db.add_all([clingen_vp_resource, clingen_gdv_resource])
                for resource_row, qualification_id, provider_id, provider_version, path in (
                    (clingen_vp_resource, clingen_vp_qualification_id, "ClinGen Variant Pathogenicity", "ERepo", clingen_vp_path),
                    (clingen_gdv_resource, clingen_gdv_qualification_id, "ClinGen Gene-Disease Validity", "GeneValidity", clingen_gdv_path),
                ):
                    contract = ResourceExecutionContract(
                        provider_id=provider_id,
                        provider_version=provider_version,
                        access_method="LOCAL",
                        endpoint=None,
                        location=str(path),
                        dataset="fixture-v1",
                        execution_scope="ORGANIZATION_MANAGED",
                    )
                    db.add(ResourceQualification(
                        id=qualification_id,
                        resource_id=resource_row.id,
                        qualification_version="fixture-qualification-v1",
                        status="QUALIFIED",
                        checks_json={"execution_contract": contract.as_dict()},
                        qualified_by=user_id,
                        qualified_at=datetime.now(UTC),
                    ))
                population_contract = ResourceExecutionContract(
                    provider_id="fixture-population",
                    provider_version="v1",
                    access_method="API",
                    endpoint="https://fixture.invalid/population",
                    location="https://fixture.invalid/population",
                    dataset="release-v1",
                    execution_scope="ORGANIZATION_MANAGED",
                )
                db.add(ResourceQualification(
                    id=uuid4(), resource_id=resource_id,
                    qualification_version="fixture-population-qualification-v1",
                    status="QUALIFIED",
                    checks_json={"execution_contract": population_contract.as_dict()},
                    qualified_by=user_id, qualified_at=datetime.now(UTC),
                ))
                clinvar_contract = ResourceExecutionContract(
                    provider_id="NCBI ClinVar",
                    provider_version="v1",
                    access_method="API",
                    endpoint="https://fixture.invalid/clinvar",
                    location="https://fixture.invalid/clinvar",
                    dataset="clinvar-v1",
                    execution_scope="ORGANIZATION_MANAGED",
                )
                db.add(ResourceQualification(
                    id=uuid4(), resource_id=clinvar_resource_id,
                    qualification_version="fixture-clinvar-qualification-v1",
                    status="QUALIFIED",
                    checks_json={"execution_contract": clinvar_contract.as_dict()},
                    qualified_by=user_id, qualified_at=datetime.now(UTC),
                ))
                db.flush()
                selected_resources = [
                    ("POPULATION", resource),
                    ("POPULATION_SECONDARY", secondary_resource),
                    ("CLINICAL_DATABASE", db.get(Resource, clinvar_resource_id)),
                    ("PHENOTYPE_ONTOLOGY", hpo_resource),
                    ("DISEASE_PHENOTYPE_ASSOCIATION", hpoa_resource),
                    ("CLINGEN_VARIANT_ASSERTION", clingen_vp_resource),
                    ("CLINGEN_GENE_DISEASE_VALIDITY", clingen_gdv_resource),
                ]
                selected = []
                for capability, selected_resource in selected_resources:
                    resolved = resolve_resource_execution(db, resource=selected_resource)
                    selected.append({
                        "capability": capability,
                        "resource_id": str(selected_resource.id),
                        "execution": resolved.snapshot,
                    })
                analysis_row = db.get(Analysis, analysis_id)
                analysis_row.configuration = {
                    **(analysis_row.configuration or {}),
                    "resource_profile_id": "WES_GRCh38_STANDARD",
                    "resource_plan": {
                        "status": "READY_WITH_LIMITATIONS",
                        "profile_version": "2",
                        "selected": selected,
                    },
                }
            db.add(Annotation(
                id=uuid4(),
                variant_id=variant_id,
                analysis_id=analysis_id,
                provider_name="fixture-annotation",
                provider_version="v1",
                resource_id=None,
                resource_name="fixture-annotation",
                resource_version="v1",
                request_fingerprint="request",
                response_sha256="b" * 64,
                request_metadata={},
                payload={"normalized": (
                    {
                        "gene": {"symbol": "GENE1"},
                        "hgvs": {"c": "NM_TEST.1:c.555T>C", "p": None},
                        "computational": {},
                        "splice": {},
                    }
                    if not no_match
                    else {}
                )},
            ))
            if not no_match:
                db.add(ClinGenSpecification(
                    id=uuid4(),
                    specification_id="SPEC-REPLAY",
                    version="1.0",
                    provider="ClinGen",
                    framework="ACMG/AMP",
                    gene_scope=["GENE1"],
                    disease_scope=["Disease X"],
                    criteria={
                        "PM2": {
                            "max_allele_frequency": 0.0001,
                            "minimum_allele_number": 1000,
                            "population_level": "GLOBAL",
                            "population_codes": ["GLOBAL"],
                            "strength": "MODERATE",
                        }
                    },
                    raw_payload={"fixture": "approved test specification"},
                    retrieved_at=datetime.now(UTC),
                    validated_for_automation=True,
                    validation_status="APPROVED_FOR_AUTOMATION",
                ))
            for order, step_id in enumerate((
                "validate_input", "normalize", "annotate", "population",
                "build_evidence", "acmg_assessment", "review", "reportability",
                "report", "export_provenance",
            ), start=1):
                status = (
                    StepStatus.PENDING
                    if step_id in {"population", "build_evidence", "acmg_assessment"}
                    else StepStatus.SUCCEEDED
                )
                outputs = (
                    [str(source_artifact.id)] if step_id == "validate_input"
                    else [str(normalized_artifact.id)] if step_id == "normalize"
                    else []
                )
                db.add(WorkflowStep(
                    id=uuid4(),
                    analysis_id=analysis_id,
                    step_id=step_id,
                    step_order=order,
                    status=status,
                    attempt=0,
                    input_artifacts=[],
                    output_artifacts=outputs,
                    metadata_json={"seeded_checkpoint": True} if status == StepStatus.SUCCEEDED else {},
                ))
            db.commit()

        monkeypatch.setattr(db_module, "SessionLocal", LocalSession)
        monkeypatch.setattr(
            workflow,
            "artifact_store_for_organization",
            lambda *_args, **_kwargs: store,
        )
        monkeypatch.setattr(workflow, "artifact_store_for_uri", lambda *_a, **_k: store)

        secondary_match_expected = clingen_enabled and not inject_internal_evidence_error
        secondary_response = (
            "1\t555\trs-secondary\tT\tC\t.\tPASS\tAC=1;AN=100;AF=0.01\n"
            if secondary_match_expected
            else "1\t555\trs-secondary\tT\tG\t.\tPASS\tAC=1;AN=100;AF=0.01\n"
        )
        secondary_calls = {"count": 0}

        def fake_tabix_run(*_args, **_kwargs):
            secondary_calls["count"] += 1
            return SimpleNamespace(returncode=0, stderr="", stdout=secondary_response)

        monkeypatch.setattr(
            "backend.app.adapters.population.secondary.subprocess.run",
            fake_tabix_run,
        )

        contract = SimpleNamespace(
            provider_id="fixture-population",
            provider_version="v1",
            access_method="API",
            endpoint="https://fixture.invalid/population",
            location="https://fixture.invalid/population",
            dataset="fixture-v1",
            as_dict=lambda: {
                "provider_id": "fixture-population",
                "provider_version": "v1",
                "access_method": "API",
                "endpoint": "https://fixture.invalid/population",
                "location": "https://fixture.invalid/population",
                "dataset": "fixture-v1",
            },
        )
        execution = SimpleNamespace(
            resource_id=resource_id,
            resource_version="release-v1",
            qualification_id=uuid4(),
            qualification_version="qualification-v1",
            contract=contract,
            contract_hash="c" * 64,
        )
        hpo_contract = ResourceExecutionContract(
            provider_id="HPO",
            provider_version="OBO",
            access_method="LOCAL",
            endpoint=None,
            location=str(hpo_path),
            dataset="2026-09-01",
            execution_scope="LABORATORY",
            toolchain={"sha256": hpo_checksum, "release": "2026-09-01"},
        )
        hpo_execution = SimpleNamespace(
            resource_id=hpo_resource_id,
            resource_version="2026-09-01",
            qualification_id=hpo_qualification_id,
            qualification_version="fixture-qualification-v1",
            contract=hpo_contract,
            contract_hash="f" * 64,
        )
        hpoa_contract = ResourceExecutionContract(
            provider_id="HPOA", provider_version="HPOA_TSV", access_method="LOCAL",
            endpoint=None, location=str(hpoa_path), dataset="2026-09-02",
            execution_scope="LABORATORY",
            toolchain={"sha256": hpoa_checksum, "release": "2026-09-02", "hpo_release": "2026-09-01"},
        )
        hpoa_execution = SimpleNamespace(
            resource_id=hpoa_resource_id, resource_version="2026-09-02",
            qualification_id=hpoa_qualification_id,
            qualification_version="fixture-hpoa-qualification-v1",
            contract=hpoa_contract, contract_hash="a" * 64,
        )
        clinvar_contract = SimpleNamespace(
            provider_id="NCBI ClinVar",
            provider_version="v1",
            access_method="API",
            endpoint="https://fixture.invalid/clinvar",
            location="https://fixture.invalid/clinvar",
            dataset="clinvar-v1",
            as_dict=lambda: {
                "provider_id": "NCBI ClinVar",
                "provider_version": "v1",
                "access_method": "API",
                "endpoint": "https://fixture.invalid/clinvar",
                "location": "https://fixture.invalid/clinvar",
                "dataset": "clinvar-v1",
            },
        )
        clinvar_execution = SimpleNamespace(
            resource_id=clinvar_resource_id,
            resource_version="clinvar-v1",
            qualification_id=uuid4(),
            qualification_version="qualification-v1",
            contract=clinvar_contract,
            contract_hash="d" * 64,
            snapshot={"resource_id": str(clinvar_resource_id), "resource_version": "clinvar-v1"},
        )

        class FakeProvider:
            provider_id = "fixture-population"

            def query_variant(self, _variant):
                provider_calls["count"] += 1
                if not no_match:
                    return [PopulationObservationData(
                        population_level="GLOBAL",
                        population_code="GLOBAL",
                        population_label="Global",
                        allele_count=0,
                        allele_number=5000,
                        allele_frequency=0.0,
                        homozygote_count=0,
                        request_fingerprint="d" * 64,
                        response_sha256="e" * 64,
                        request_metadata={"fixture": True},
                    )]
                return [
                    PopulationObservationData(
                        population_level="GLOBAL",
                        population_code=f"GLOBAL_{cohort.upper()}S",
                        population_label=f"gnomAD {cohort}s",
                        allele_count=None,
                        allele_number=None,
                        allele_frequency=None,
                        homozygote_count=None,
                        availability="NOT_FOUND",
                        quality_status="NO_MATCH",
                        request_fingerprint="d" * 64,
                        response_sha256="e" * 64,
                        request_metadata={"fixture": True},
                    )
                    for cohort in ("exome", "genome")
                ]

        class FakeClinVarProvider:
            def query_variant(self, **_kwargs):
                clinvar_calls["count"] += 1
                return []

        provider = FakeProvider()
        candidate = SimpleNamespace(resource=resource, execution=execution)
        hpo_candidate = SimpleNamespace(
            resource=hpo_resource,
            execution=hpo_execution,
        )
        hpoa_candidate = SimpleNamespace(resource=hpoa_resource, execution=hpoa_execution)

        def fake_execution_plan(*_args, **kwargs):
            capability = kwargs["requirements"][0].capability
            if capability == workflow.ResourceCapability.PHENOTYPE:
                candidates = [hpo_candidate]
            elif capability == workflow.ResourceCapability.DISEASE_PHENOTYPE:
                candidates = [hpoa_candidate]
            elif capability == workflow.ResourceCapability.POPULATION_FREQUENCY:
                candidates = [candidate]
            else:
                candidates = []
            return SimpleNamespace(
                profile_type="TRIAL_PUBLIC",
                profile_version="test",
                unavailable_optional=[],
                for_capability=lambda _capability: candidates,
            )

        monkeypatch.setattr(
            workflow,
            "build_resource_execution_plan",
            fake_execution_plan,
        )
        monkeypatch.setattr(
            workflow,
            "resolve_resource_execution",
            lambda _db, *, resource: {
                clinvar_resource_id: clinvar_execution,
                hpo_resource_id: hpo_execution,
                hpoa_resource_id: hpoa_execution,
            }.get(resource.id, execution),
        )
        monkeypatch.setattr(
            workflow.ClinVarVCVProvider,
            "from_execution_contract",
            lambda **_kwargs: FakeClinVarProvider(),
        )
        monkeypatch.setattr(
            workflow,
            "register_builtin_providers",
            lambda: SimpleNamespace(
                resolve=lambda **_kwargs: SimpleNamespace(factory=lambda _contract: provider),
                require=lambda **kwargs: SimpleNamespace(
                    factory=(HPOAProvider.from_execution_contract
                        if kwargs.get("provider_id") == "HPOA"
                        else HPOOboProvider.from_execution_contract)
                ),
            ),
        )

        actual_mark_step = workflow.mark_step
        worker_loss = {"injected": False}

        def crash_after_provider_commit(db, step, status, **kwargs):
            if (
                step.step_id == "population"
                and status == StepStatus.SUCCEEDED
                and not worker_loss["injected"]
            ):
                worker_loss["injected"] = True
                raise SystemExit(73)
            return actual_mark_step(db, step, status, **kwargs)

        monkeypatch.setattr(workflow, "mark_step", crash_after_provider_commit)
        with pytest.raises(SystemExit, match="73"):
            workflow.run_variant_analysis(analysis_id)

        with LocalSession() as db:
            executions = db.scalars(select(ResourceExecutionRecord).where(
                ResourceExecutionRecord.analysis_id == analysis_id,
                ResourceExecutionRecord.step_id == "population",
            )).all()
            observations = db.scalars(select(PopulationObservation).where(
                PopulationObservation.analysis_id == analysis_id,
            )).all()
            assert len(executions) == 1 + int(clingen_enabled)
            assert all(execution.status == "SUCCEEDED" for execution in executions)
            assert len(observations) == (
                2 if no_match else 1 + int(secondary_match_expected)
            )
            if clingen_enabled:
                secondary_execution_record = next(
                    execution
                    for execution in executions
                    if execution.resource_id == secondary_resource_id
                )
                assert len(secondary_execution_record.request_fingerprint) == 64
                assert secondary_execution_record.response_sha256 == hashlib.sha256(
                    secondary_response.encode()
                ).hexdigest()
                assert secondary_execution_record.metadata_json["query_outcome"] == (
                    "MATCHED" if secondary_match_expected else "NO_MATCH"
                )
                if secondary_match_expected:
                    secondary_observation = next(
                        observation
                        for observation in observations
                        if observation.resource_id == secondary_resource_id
                    )
                    assert secondary_observation.request_fingerprint == secondary_execution_record.request_fingerprint
                    assert secondary_observation.response_sha256 == secondary_execution_record.response_sha256
                    assert secondary_observation.request_metadata["alternate"] == "C"
                    assert secondary_observation.observed_at is not None
                assert secondary_calls["count"] == 1
            else:
                assert secondary_calls["count"] == 0
            if no_match:
                assert all(row.availability == "NOT_FOUND" for row in observations)
                assert all(row.allele_count is None and row.allele_number is None and row.allele_frequency is None for row in observations)
            assert executions[0].request_fingerprint == "d" * 64
            assert executions[0].response_sha256 == "e" * 64
            assert executions[0].metadata_json["query_outcome"] == (
                "NO_MATCH" if no_match else "MATCHED"
            )
            assert provider_calls["count"] == 1

        # Simulate worker loss after evidence and resource-execution rows commit,
        # but before the evidence batch checkpoint is marked complete.
        real_save_batch_checkpoint = workflow._save_batch_checkpoint
        evidence_worker_loss = {"injected": False}

        def crash_before_evidence_checkpoint(db, step, start, end, **kwargs):
            if (
                step.step_id == "build_evidence"
                and kwargs.get("status") == "SUCCEEDED"
                and not evidence_worker_loss["injected"]
            ):
                evidence_worker_loss["injected"] = True
                raise SystemExit(75)
            return real_save_batch_checkpoint(db, step, start, end, **kwargs)

        monkeypatch.setattr(workflow, "_save_batch_checkpoint", crash_before_evidence_checkpoint)
        real_step = workflow._step

        def stop_after_population(db, received_analysis_id, step_id):
            if step_id == "acmg_assessment":
                raise SystemExit(74)
            return real_step(db, received_analysis_id, step_id)

        monkeypatch.setattr(workflow, "_step", stop_after_population)
        if inject_hpo_resource_resolution_error:
            real_resolver = workflow.resolve_profile_runtime_resources

            def fail_hpo_resolution(db, *, analysis_id, capability, provider_id=None):
                if capability == inject_hpo_resource_resolution_error:
                    raise RuntimeError("injected internal resource resolver defect")
                return real_resolver(
                    db,
                    analysis_id=analysis_id,
                    capability=capability,
                    provider_id=provider_id,
                )

            monkeypatch.setattr(
                workflow,
                "resolve_profile_runtime_resources",
                fail_hpo_resolution,
            )
            workflow.run_variant_analysis(analysis_id)
            with LocalSession() as db:
                current = db.get(Analysis, analysis_id)
                evidence_step = db.scalar(select(WorkflowStep).where(
                    WorkflowStep.analysis_id == analysis_id,
                    WorkflowStep.step_id == "build_evidence",
                ))
                assert current.status == AnalysisStatus.FAILED
                assert evidence_step.error_code == "EVIDENCE_BUILD_FAILED"
                assert "provider_limitations" not in (evidence_step.metadata_json or {})
            return
        if inject_internal_evidence_error:
            evidence_engine_module = importlib.import_module(
                "backend.app.evidence.engine"
            )

            def fail_evidence_mapping(self, **_kwargs):
                raise RuntimeError("injected evidence mapping defect")

            monkeypatch.setattr(
                evidence_engine_module.EvidenceEngine,
                "build_from_clingen_variant_assertions",
                fail_evidence_mapping,
            )
            workflow.run_variant_analysis(analysis_id)
            with LocalSession() as db:
                current = db.get(Analysis, analysis_id)
                evidence_step = db.scalar(select(WorkflowStep).where(
                    WorkflowStep.analysis_id == analysis_id,
                    WorkflowStep.step_id == "build_evidence",
                ))
                executions = db.scalars(select(ResourceExecutionRecord).where(
                    ResourceExecutionRecord.analysis_id == analysis_id,
                    ResourceExecutionRecord.resource_id == clingen_vp_resource_id,
                    ResourceExecutionRecord.step_id == "build_evidence",
                )).all()
                assert current.status == AnalysisStatus.FAILED
                assert evidence_step.error_code == "EVIDENCE_BUILD_FAILED"
                assert "provider_limitations" not in (evidence_step.metadata_json or {})
                assert len(executions) == 1
                assert executions[0].status == "SUCCESS"
                assert executions[0].response_sha256
                assert db.scalar(select(func.count(Evidence.id)).where(
                    Evidence.analysis_id == analysis_id,
                    Evidence.resource_id == clingen_vp_resource_id,
                )) == 0
            return
        if inject_clingen_provider_error:
            clingen_module = importlib.import_module(
                "backend.app.adapters.clingen.variant_pathogenicity"
            )

            def fail_clingen_query(self, **_kwargs):
                raise clingen_module.ClinGenVariantPathogenicityError(
                    "fixture provider response failure"
                )

            monkeypatch.setattr(
                workflow.ClinGenVariantPathogenicityProvider,
                "query_variant",
                fail_clingen_query,
            )
            with pytest.raises(SystemExit, match="75"):
                workflow.run_variant_analysis(analysis_id)
            with LocalSession() as db:
                executions = db.scalars(select(ResourceExecutionRecord).where(
                    ResourceExecutionRecord.analysis_id == analysis_id,
                    ResourceExecutionRecord.resource_id == clingen_vp_resource_id,
                    ResourceExecutionRecord.step_id == "build_evidence",
                )).all()
                evidence_step = db.scalar(select(WorkflowStep).where(
                    WorkflowStep.analysis_id == analysis_id,
                    WorkflowStep.step_id == "build_evidence",
                ))
                assert len(executions) == 1
                assert executions[0].status == "FAILED"
                assert executions[0].error_code == "CLINGEN_VARIANT_PATHOGENICITY_QUERY_FAILED"
                assert evidence_step.status == StepStatus.RUNNING
                assert evidence_step.metadata_json["batches"]["0:1"]["status"] == "RUNNING"
            return
        try:
            workflow.run_variant_analysis(analysis_id)
        except SystemExit as exc:
            assert str(exc.code) == "75"
        else:
            with LocalSession() as db:
                current = db.get(Analysis, analysis_id)
                evidence_step = db.scalar(select(WorkflowStep).where(
                    WorkflowStep.analysis_id == analysis_id,
                    WorkflowStep.step_id == "build_evidence",
                ))
            pytest.fail(
                "Evidence checkpoint hook was not reached; "
                f"analysis={current.status if current else None}, "
                f"step={evidence_step.status if evidence_step else None}, "
                f"error={evidence_step.error_code if evidence_step else None}, "
                f"message={evidence_step.error_message if evidence_step else None}, "
                f"clinvar_calls={clinvar_calls['count']}"
            )

        # Evidence stage must have run and committed its records before the
        # checkpoint hook is reached. The checkpoint remains RUNNING.
        with LocalSession() as db:
            evidence_rows = db.scalars(select(Evidence).where(
                Evidence.analysis_id == analysis_id,
            )).all()
            evidence_ids_before_replay = tuple(sorted(row.id for row in evidence_rows))
            evidence_step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "build_evidence",
            ))
            assert evidence_rows
            phenotype_evidence = next(
                row for row in evidence_rows
                if row.evidence_type == "PHENOTYPE"
                and row.source_name in {"HPO", "HPO_CASE_CONTEXT"}
            )
            assert [term["hpo_id"] for term in phenotype_evidence.payload["present_terms"]] == [
                "HP:0000002"
            ]
            assert [term["hpo_id"] for term in phenotype_evidence.payload["negative_terms"]] == [
                "HP:0000004"
            ]
            assert [term["hpo_id"] for term in phenotype_evidence.payload["excluded_terms"]] == [
                "HP:0000005"
            ]
            assert [term["hpo_id"] for term in phenotype_evidence.payload["uncertain_terms"]] == [
                "HP:0000006"
            ]
            assert [term["hpo_id"] for term in phenotype_evidence.payload["not_assessed_terms"]] == [
                "HP:0000007"
            ]
            if ontology_valid:
                assert phenotype_evidence.source_name == "HPO"
                assert phenotype_evidence.resource_id == hpo_resource_id
                assert phenotype_evidence.source_version == "2026-09-01"
                assert phenotype_evidence.payload["ontology_term_resolutions"][0]["status"] == "CURRENT"
            else:
                assert phenotype_evidence.source_name == "HPO_CASE_CONTEXT"
                assert phenotype_evidence.resource_id is None
                assert phenotype_evidence.payload["ontology_term_resolutions"] is None
            hpoa_evidence_rows = [row for row in evidence_rows if row.source_name == "HPOA"]
            hpoa_execution_rows = db.scalars(select(ResourceExecutionRecord).where(
                ResourceExecutionRecord.analysis_id == analysis_id,
                ResourceExecutionRecord.resource_id == hpoa_resource_id,
            )).all()
            if hpoa_license:
                hpoa_evidence = hpoa_evidence_rows[0]
                assert hpoa_evidence.evidence_type == "PHENOTYPE"
                assert hpoa_evidence.resource_id == hpoa_resource_id
                assert hpoa_evidence.source_version == "2026-09-02"
                assert hpoa_evidence.payload["disease_id"] == "MONDO:0000001"
                assert hpoa_evidence.payload["score"] is None
                assert hpoa_evidence.payload["clinical_prioritization_validated"] is False
                assert [row["qualifier"] for row in hpoa_evidence.payload["assertions"]] == ["", "NOT"]
                assert [row["frequency"] for row in hpoa_evidence.payload["assertions"]] == ["1/2", "0/3"]
                patient_comparison = hpoa_evidence.payload["patient_comparison"]
                assert patient_comparison["method"] == "HPOA_ASSERTION_COMPARISON_V1"
                assert patient_comparison["ontology_release"] == (
                    "2026-09-01" if ontology_valid else None
                )
                assert patient_comparison["score"] is None
                assert patient_comparison["clinical_prioritization_validated"] is False
                assert len(hpoa_evidence.request_fingerprint) == 64
                assert len(hpoa_evidence.response_sha256) == 64
                assert len(hpoa_execution_rows) == 1
                assert hpoa_execution_rows[0].status == "SUCCESS"
            else:
                assert hpoa_evidence_rows == []
                assert hpoa_execution_rows
                assert all(row.status == "FAILED" for row in hpoa_execution_rows)
                assert all(row.error_code == "HPOA_RESOURCE_INVALID" for row in hpoa_execution_rows)
            disease_evidence = next(
                row for row in evidence_rows
                if row.evidence_type == "GENE_DISEASE"
                and (row.payload or {}).get("phenotype_match")
            )
            if ontology_valid:
                assert disease_evidence.payload["phenotype_match"]["status"] == "CONTEXT_ONLY"
                assert disease_evidence.payload["phenotype_match"]["matched_terms"] == ["HP:0000002"]
                assert "score" not in disease_evidence.payload["phenotype_match"]
            else:
                assert disease_evidence.payload["phenotype_match"]["status"] == "REQUIRES_REVIEW"
                assert "score" not in disease_evidence.payload["phenotype_match"]
            hpo_executions = db.scalars(select(ResourceExecutionRecord).where(
                ResourceExecutionRecord.analysis_id == analysis_id,
                ResourceExecutionRecord.resource_id == hpo_resource_id,
            )).all()
            assert hpo_executions
            if ontology_valid:
                assert len(hpo_executions) == 1
                assert hpo_executions[0].status == "SUCCESS"
                assert len(hpo_executions[0].request_fingerprint) == 64
                assert len(hpo_executions[0].response_sha256) == 64
            else:
                assert all(row.status == "FAILED" for row in hpo_executions)
                assert all(row.error_code == "HPO_ONTOLOGY_RESOURCE_INVALID" for row in hpo_executions)
            assert evidence_step.metadata_json["batches"]["0:1"]["status"] == "RUNNING"
            assert clinvar_calls["count"] == 1
            hpo_execution_count = db.scalar(select(func.count(ResourceExecutionRecord.id)).where(
                ResourceExecutionRecord.analysis_id == analysis_id,
                ResourceExecutionRecord.resource_id == hpo_resource_id,
            ))
            if ontology_valid:
                assert hpo_execution_count == 1
            else:
                # This is the first pass, before the injected worker loss and
                # redelivery below. The retry must create the next attempt.
                assert hpo_execution_count == 1
        assert evidence_worker_loss["injected"]

        # On redelivery, the pending checkpoint causes evidence reconstruction;
        # row fingerprints prevent duplicates and persisted resource executions
        # are reused for any external evidence query.
        monkeypatch.setattr(workflow, "_step", lambda db, received_analysis_id, step_id: (
            (_ for _ in ()).throw(SystemExit(76))
            if step_id == "acmg_assessment"
            else real_step(db, received_analysis_id, step_id)
        ))
        with pytest.raises(SystemExit, match="76"):
            workflow.run_variant_analysis(analysis_id)

        with LocalSession() as db:
            population_step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "population",
            ))
            assert population_step.status == StepStatus.SUCCEEDED
            assert db.scalar(select(func.count(ResourceExecutionRecord.id)).where(
                ResourceExecutionRecord.analysis_id == analysis_id,
                ResourceExecutionRecord.step_id == "population",
            )) == 1 + int(clingen_enabled)
            assert db.scalar(select(func.count(PopulationObservation.id)).where(
                PopulationObservation.analysis_id == analysis_id,
            )) == (2 if no_match else 1 + int(secondary_match_expected))
            clinvar_execution_rows = db.scalars(select(ResourceExecutionRecord).where(
                ResourceExecutionRecord.analysis_id == analysis_id,
                ResourceExecutionRecord.step_id == "build_evidence",
                ResourceExecutionRecord.resource_id == clinvar_resource_id,
            )).all()
            assert len(clinvar_execution_rows) == 1
            assert clinvar_execution_rows[0].status == "NO_DATA"
            assert provider_calls["count"] == 1
            assert secondary_calls["count"] == int(clingen_enabled)
            population_step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "population",
            ))
            if clingen_enabled:
                assert population_step.metadata_json["profile_version"] == "2"
            assert clinvar_calls["count"] == 1
            replayed_evidence_ids = tuple(sorted(db.scalars(
                select(Evidence.id).where(Evidence.analysis_id == analysis_id)
            ).all()))
            assert replayed_evidence_ids == evidence_ids_before_replay
            if clingen_enabled:
                for resource_id, source_name, expected_type in (
                    (clingen_vp_resource_id, "Fixture ClinGen Variant Pathogenicity", "CLINICAL_DATABASE"),
                    (clingen_gdv_resource_id, "Fixture ClinGen Gene-Disease Validity", "GENE_DISEASE"),
                ):
                    executions = db.scalars(select(ResourceExecutionRecord).where(
                        ResourceExecutionRecord.analysis_id == analysis_id,
                        ResourceExecutionRecord.step_id == "build_evidence",
                        ResourceExecutionRecord.resource_id == resource_id,
                    )).all()
                    assert len(executions) == 1, (
                        source_name,
                        db.scalar(select(WorkflowStep).where(
                            WorkflowStep.analysis_id == analysis_id,
                            WorkflowStep.step_id == "build_evidence",
                        )).metadata_json.get("provider_limitations"),
                    )
                    assert executions[0].status == "SUCCESS"
                    assert len(executions[0].request_fingerprint) == 64
                    assert len(executions[0].response_sha256) == 64
                    source_evidence = db.scalars(select(Evidence).where(
                        Evidence.analysis_id == analysis_id,
                        Evidence.resource_id == resource_id,
                        Evidence.source_name == source_name,
                    )).all()
                    assert len(source_evidence) == 1
                    assert source_evidence[0].evidence_type == expected_type
                    assert source_evidence[0].source_version == "fixture-v1"
                    assert len(source_evidence[0].response_sha256) == 64
                assertions = db.scalars(select(ACMGSourceAssertion).where(
                    ACMGSourceAssertion.analysis_id == analysis_id,
                )).all()
                assert len(assertions) == 1
                assert assertions[0].criterion == "PM2"
                assert assertions[0].status == "MET"
                assert assertions[0].source_record_id
                assert assertions[0].evidence_id in {
                    row.id for row in evidence_rows
                    if row.source_name == "Fixture ClinGen Variant Pathogenicity"
                }
                assert len(replayed_evidence_ids) == len(evidence_ids_before_replay)
                return
            hpo_execution_rows = db.scalars(select(ResourceExecutionRecord).where(
                ResourceExecutionRecord.analysis_id == analysis_id,
                ResourceExecutionRecord.resource_id == hpo_resource_id,
            )).all()
            if ontology_valid:
                assert len(hpo_execution_rows) == 1
                assert hpo_execution_rows[0].status == "SUCCESS"
            else:
                assert len(hpo_execution_rows) >= 2
                assert all(row.status == "FAILED" for row in hpo_execution_rows)
                assert all(
                    row.error_code == "HPO_ONTOLOGY_RESOURCE_INVALID"
                    for row in hpo_execution_rows
                )
            replayed_hpoa_execution_rows = db.scalars(select(ResourceExecutionRecord).where(
                ResourceExecutionRecord.analysis_id == analysis_id,
                ResourceExecutionRecord.resource_id == hpoa_resource_id,
            )).all()
            if hpoa_license:
                assert len(replayed_hpoa_execution_rows) == 1
                assert replayed_hpoa_execution_rows[0].status == "SUCCESS"
            else:
                assert len(replayed_hpoa_execution_rows) >= 2
                assert all(row.status == "FAILED" for row in replayed_hpoa_execution_rows)

        if not no_match:
            # The real ACMG stage commits criterion/classification rows before
            # its successful batch checkpoint. Simulate worker loss in that gap,
            # then redeliver through the workflow entry point.
            monkeypatch.setattr(workflow, "_step", real_step)
            acmg_worker_loss = {"injected": False}
            acmg_persisted_ids = {"assessments": (), "classifications": ()}

            def crash_after_acmg_rows_commit(db, step, start, end, **kwargs):
                if (
                    step.step_id == "acmg_assessment"
                    and kwargs.get("status") == "SUCCEEDED"
                    and not acmg_worker_loss["injected"]
                ):
                    acmg_worker_loss["injected"] = True
                    acmg_persisted_ids["assessments"] = tuple(db.scalars(
                        select(ACMGAssessment.id).where(
                            ACMGAssessment.analysis_id == analysis_id,
                        ).order_by(ACMGAssessment.id)
                    ).all())
                    acmg_persisted_ids["classifications"] = tuple(db.scalars(
                        select(Classification.id).where(
                            Classification.analysis_id == analysis_id,
                        ).order_by(Classification.id)
                    ).all())
                    assert acmg_persisted_ids["assessments"]
                    assert acmg_persisted_ids["classifications"]
                    raise SystemExit(77)
                return real_save_batch_checkpoint(db, step, start, end, **kwargs)

            monkeypatch.setattr(
                workflow, "_save_batch_checkpoint", crash_after_acmg_rows_commit
            )
            try:
                workflow.run_variant_analysis(analysis_id)
            except SystemExit as exc:
                assert str(exc.code) == "77"
            else:
                with LocalSession() as db:
                    acmg_step = db.scalar(select(WorkflowStep).where(
                        WorkflowStep.analysis_id == analysis_id,
                        WorkflowStep.step_id == "acmg_assessment",
                    ))
                    assessment_count = db.scalar(select(func.count(ACMGAssessment.id)).where(
                        ACMGAssessment.analysis_id == analysis_id,
                    ))
                pytest.fail(
                    "ACMG success checkpoint hook was not reached; "
                    f"step={acmg_step.status if acmg_step else None}, "
                    f"error={acmg_step.error_code if acmg_step else None}, "
                    f"message={acmg_step.error_message if acmg_step else None}, "
                    f"assessments={assessment_count}"
                )

            with LocalSession() as db:
                acmg_step = db.scalar(select(WorkflowStep).where(
                    WorkflowStep.analysis_id == analysis_id,
                    WorkflowStep.step_id == "acmg_assessment",
                ))
                stage_event_count = db.scalar(select(func.count(AuditEvent.id)).where(
                    AuditEvent.analysis_id == analysis_id,
                    AuditEvent.event_type.in_((
                        "ACMG_ASSESSMENT_COMPLETED",
                        "ACMG_ASSESSMENT_REQUIRES_MANUAL_REVIEW",
                    )),
                ))
                assert acmg_step.metadata_json["batches"]["0:1"]["status"] == "RUNNING"
                assert stage_event_count == 0
                assert tuple(db.scalars(select(ACMGAssessment.id).where(
                    ACMGAssessment.analysis_id == analysis_id,
                ).order_by(ACMGAssessment.id)).all()) == acmg_persisted_ids["assessments"]

            workflow.run_variant_analysis(analysis_id)

            with LocalSession() as db:
                acmg_step = db.scalar(select(WorkflowStep).where(
                    WorkflowStep.analysis_id == analysis_id,
                    WorkflowStep.step_id == "acmg_assessment",
                ))
                final_assessment_ids = tuple(db.scalars(select(ACMGAssessment.id).where(
                    ACMGAssessment.analysis_id == analysis_id,
                ).order_by(ACMGAssessment.id)).all())
                final_classification_ids = tuple(db.scalars(select(Classification.id).where(
                    Classification.analysis_id == analysis_id,
                ).order_by(Classification.id)).all())
                stage_event_count = db.scalar(select(func.count(AuditEvent.id)).where(
                    AuditEvent.analysis_id == analysis_id,
                    AuditEvent.event_type.in_((
                        "ACMG_ASSESSMENT_COMPLETED",
                        "ACMG_ASSESSMENT_REQUIRES_MANUAL_REVIEW",
                    )),
                ))
                assert acmg_worker_loss["injected"]
                assert acmg_step.metadata_json["batches"]["0:1"]["status"] == "SUCCEEDED"
                assert final_assessment_ids == acmg_persisted_ids["assessments"]
                assert final_classification_ids == acmg_persisted_ids["classifications"]
                assert stage_event_count == 1
    finally:
        engine.dispose()
