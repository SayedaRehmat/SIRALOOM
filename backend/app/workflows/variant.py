                # provider identity or local resource location.
                reference_execution = resolve_resource_execution(
                    db,
                    resource=selected_reference_resource,
                )
                if reference_execution.contract.access_method in {"LOCAL", "FILE", "LOCAL_ONLY"}:
                    contract_location = reference_execution.contract.location or ""
                    normalized_contract_location = str(Path(contract_location.removeprefix("file://")).resolve())
                    normalized_reference_location = str(reference_fasta_path.resolve())
                    if normalized_contract_location != normalized_reference_location:
                        raise ResourceExecutionError(
                            "Qualified reference execution location does not match the "
                            f"validated FASTA location: {contract_location!r} != "
                            f"{str(reference_fasta_path)!r}."
                        )

                toolchain = dict(reference_execution.contract.toolchain or {})
                bcftools_contract = toolchain.get("bcftools")
                if not isinstance(bcftools_contract, dict) or not str(bcftools_contract.get("version") or "").strip():
                    raise ResourceExecutionError("Qualified reference execution contract does not declare a bcftools version.")
                expected_bcftools_version = str(bcftools_contract["version"]).strip()
                reference_contigs = {item["name"] for item in reference_package["contigs"]}

                # Re-validate against the selected package so build/contig compatibility
                # is established before bcftools is allowed to transform the VCF.
                package_profile = validate_vcf_strict(
                    str(input_path),
                    reference_contigs=reference_contigs,
                )
            except ReferencePackageError as exc:
                mark_step(
                    db,
                    normalization_step,
                    StepStatus.BLOCKED,
                    error_code=exc.code,
                    error_message=str(exc),
                )
                analysis.status = AnalysisStatus.BLOCKED
                db.commit()
                audit.record(
                    event_type="WORKFLOW_BLOCKED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="reference-package",
                    reason=str(exc),
                    payload={"error_code": exc.code, "reference_build": reference_build},
                )
                db.commit()
                return
            except StrictVCFValidationError as exc:
                mark_step(
                    db,
                    normalization_step,
                    StepStatus.BLOCKED,
                    error_code=exc.code,
                    error_message=str(exc),
                    metadata={"next_step": "VALID_VCF_REQUIRED"},
                )
                analysis.status = AnalysisStatus.BLOCKED
                db.commit()
                audit.record(
                    event_type="NORMALIZATION_BLOCKED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="vcf-validator",
                    reason=str(exc),
                    payload={
                        "error_code": exc.code,
                        "reference_build": reference_build,
                        "next_step": "VALID_VCF_REQUIRED",
                    },
                )
                db.commit()
                return
            except ResourceExecutionError as exc:
                mark_step(
                    db,
                    normalization_step,
                    StepStatus.RESOURCE_FAILURE,
                    error_code="REFERENCE_EXECUTION_CONTRACT_INVALID",
                    error_message=str(exc),
                    metadata={
                        "resource_id": str(selected_reference_resource.id),
                        "requested_resource_id": str(reference_resource_id),
                        "fallback_used": resolution.used_fallback,
                        "next_action": WorkflowAction.REQUEST_LAB_ACTION.value,
                    },
                )
                analysis.status = AnalysisStatus.RESOURCE_FAILURE
                analysis.completed_at = None
                db.commit()
                audit.record(
                    event_type="NORMALIZATION_RESOURCE_EXECUTION_INVALID",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="reference-resource",
                    reason=str(exc),
                    payload={
                        "error_code": "REFERENCE_EXECUTION_CONTRACT_INVALID",
                        "resource_id": str(selected_reference_resource.id),
                        "requested_resource_id": str(reference_resource_id),
                        "fallback_used": resolution.used_fallback,
                    },
                )
                db.commit()
                return

            temp_path: Path | None = None
            try:
                suffix = ".vcf.gz" if input_path.name.endswith(".gz") else ".vcf"
                with NamedTemporaryFile(prefix="siraloom-normalized-", suffix=suffix, delete=False) as temp:
                    temp_path = Path(temp.name)

                profile = classify_records(input_path)
                if profile["gvcf_markers"]:
                    raise UnsupportedVariantError(
                        "GVCF input detected. Phase 1 requires a genotyped VCF; "
                        "GVCF reference blocks must first pass the appropriate "
                        "genotyping/joint-genotyping workflow.",
                        code="UNSUPPORTED_GVCF_INPUT",
                    )
                if profile["symbolic_records"]:
                    raise UnsupportedVariantError(
                        "Symbolic/breakend variants detected. Phase 1 currently "
                        "normalizes SNVs and short indels; SV/CNV records require "
                        "the dedicated structural-variant workflow.",
                        code="UNSUPPORTED_STRUCTURAL_VARIANT",
                    )

                request_material = {
                    "input_artifact_sha256": input_artifact.sha256,
                    "reference_package_checksum": reference_package["package_checksum"],
                    "reference_fasta_sha256": reference_package["fasta_sha256"],
                    "bcftools_version": expected_bcftools_version,
                    "execution_contract_hash": reference_execution.contract_hash,
                }
                request_fingerprint = hashlib.sha256(
                    json.dumps(request_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()

                execution_record = start_resource_execution(
                    db,
                    analysis_id=analysis.id,
                    step_id="normalize",
                    attempt=normalization_step.attempt,
                    resolved=reference_execution,
                    requested_resource_id=resolution.requested_resource_id,
                    fallback_resource_id=resolution.fallback_resource_id,