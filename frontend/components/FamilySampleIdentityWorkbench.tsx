"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useLanguage } from "../lib/i18n";

type ApiFetch = (path: string, init?: RequestInit) => Promise<any>;
type Props = {
  caseId: string;
  variantId: string;
  canWrite: boolean;
  canReview: boolean;
  apiFetch: ApiFetch;
};
type Member = { id: string; member_identifier: string; is_proband?: boolean };
type Specimen = { specimen_id: string; specimen_identifier: string; specimen_type: string };
type CaseArtifact = { artifact_id: string; filename: string; artifact_type: string; sha256: string; validation_status?: string | null };
type SourceVcf = {
  artifact_id: string;
  filename: string;
  sha256: string;
  specimen_id?: string | null;
  validation_status?: string | null;
  genome_build?: string | null;
};
type AnalysisCandidate = {
  analysis_id: string;
  analysis_status: string;
  reference_build?: string | null;
  assay_id?: string | null;
  selected_sample_name?: string | null;
  source_vcf?: SourceVcf | null;
  binding_candidate_status: string;
};
type Binding = {
  binding_id: string;
  member_id: string;
  specimen_id: string;
  analysis_id: string;
  artifact_id: string;
  source_artifact_sha256: string;
  sample_name: string;
  binding_status: string;
  binding_method: string;
  evidence_reference?: string | null;
  review_reason?: string | null;
  version: number;
  supersedes_binding_id?: string | null;
  recorded_by: string;
  reviewed_by?: string | null;
};
type IdentityEvidence = {
  evidence_id: string;
  binding_id: string;
  evidence_type: string;
  result: string;
  method: string;
  method_version: string;
  evidence_reference: string;
  source_artifact_id?: string | null;
  metrics?: Record<string, unknown>;
  review_status: string;
  review_reason?: string | null;
  version: number;
  supersedes_evidence_id?: string | null;
  recorded_by: string;
  reviewed_by?: string | null;
};

export default function FamilySampleIdentityWorkbench({
  caseId,
  variantId,
  canWrite,
  canReview,
  apiFetch,
}: Props) {
  const { t } = useLanguage();
  const [members, setMembers] = useState<Member[]>([]);
  const [specimens, setSpecimens] = useState<Specimen[]>([]);
  const [analyses, setAnalyses] = useState<AnalysisCandidate[]>([]);
  const [artifacts, setArtifacts] = useState<CaseArtifact[]>([]);
  const [bindings, setBindings] = useState<Binding[]>([]);
  const [selectedBindingIds, setSelectedBindingIds] = useState<string[]>([]);
  const [matrix, setMatrix] = useState<any>(null);
  const [matrixLoading, setMatrixLoading] = useState(false);
  const [evidenceByBinding, setEvidenceByBinding] = useState<Record<string, IdentityEvidence[]>>({});
  const [memberId, setMemberId] = useState("");
  const [specimenId, setSpecimenId] = useState("");
  const [analysisId, setAnalysisId] = useState("");
  const [bindingMethod, setBindingMethod] = useState("LAB_SAMPLE_SHEET");
  const [bindingReference, setBindingReference] = useState("");
  const [successorOf, setSuccessorOf] = useState("");
  const [evidenceBindingId, setEvidenceBindingId] = useState("");
  const [evidenceType, setEvidenceType] = useState("CHAIN_OF_CUSTODY");
  const [evidenceResult, setEvidenceResult] = useState("PASS");
  const [evidenceMethod, setEvidenceMethod] = useState("");
  const [evidenceMethodVersion, setEvidenceMethodVersion] = useState("");
  const [evidenceReference, setEvidenceReference] = useState("");
  const [evidenceArtifactId, setEvidenceArtifactId] = useState("");
  const [correctingEvidenceId, setCorrectingEvidenceId] = useState("");
  const [reviewReason, setReviewReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    if (!caseId) return;
    setLoading(true);
    setError("");
    try {
      const [bindingResult, contextResult, pedigreeResult, caseResult, artifactResult] = await Promise.all([
        apiFetch(`/cases/${caseId}/pedigree/sample-bindings`),
        apiFetch(`/cases/${caseId}/pedigree/sample-binding-context`),
        apiFetch(`/cases/${caseId}/pedigree`),
        apiFetch(`/cases/${caseId}`),
        apiFetch(`/cases/${caseId}/artifacts`),
      ]);
      const nextBindings: Binding[] = bindingResult.bindings ?? [];
      const evidenceEntries = await Promise.all(nextBindings.map(async (binding) => {
        const result = await apiFetch(
          `/cases/${caseId}/pedigree/sample-bindings/${binding.binding_id}/identity-evidence`,
        );
        return [binding.binding_id, result.evidence ?? []] as const;
      }));
      setBindings(nextBindings);
      setEvidenceByBinding(Object.fromEntries(evidenceEntries));
      setAnalyses(contextResult.analyses ?? []);
      setMembers(pedigreeResult.members ?? []);
      setSpecimens(caseResult.specimens ?? []);
      setArtifacts(Array.isArray(artifactResult) ? artifactResult : artifactResult.items ?? []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("familyIdentity.errorLoad"));
    } finally {
      setLoading(false);
    }
  }, [apiFetch, caseId, t]);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    setSelectedBindingIds(bindings.filter((binding) => binding.binding_status === "VERIFIED" && !supersededBindingIds.has(binding.binding_id)).map((binding) => binding.binding_id));
    setMatrix(null);
  }, [bindings, supersededBindingIds, variantId]);

  const selectedAnalysis = useMemo(
    () => analyses.find((analysis) => analysis.analysis_id === analysisId) ?? null,
    [analyses, analysisId],
  );
  const selectedSampleName = selectedAnalysis?.selected_sample_name ?? "";
  const selectedSourceVcf = selectedAnalysis?.source_vcf ?? null;
  const supersededBindingIds = useMemo(
    () => new Set(bindings.map((binding) => binding.supersedes_binding_id).filter(Boolean)),
    [bindings],
  );

  const loadMatrix = async () => {
    if (!variantId || selectedBindingIds.length === 0) return;
    setMatrixLoading(true);
    setError("");
    try {
      const result = await apiFetch(`/cases/${caseId}/pedigree/genotype-matrix`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ binding_ids: selectedBindingIds, variant_ids: [variantId] }),
      });
      setMatrix(result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("familyIdentity.errorAction"));
      setMatrix(null);
    } finally {
      setMatrixLoading(false);
    }
  };

  const resetBindingForm = () => {
    setMemberId("");
    setSpecimenId("");
    setAnalysisId("");
    setBindingMethod("LAB_SAMPLE_SHEET");
    setBindingReference("");
    setSuccessorOf("");
  };

  const beginSuccessor = (binding: Binding) => {
    setSuccessorOf(binding.binding_id);
    setMemberId(binding.member_id);
    setSpecimenId(binding.specimen_id);
    setAnalysisId(binding.analysis_id);
    setBindingMethod(binding.binding_method);
    setBindingReference(binding.evidence_reference ?? "");
    setNotice("");
  };

  const saveBinding = async () => {
    if (!canWrite || !memberId || !specimenId || !selectedAnalysis || !selectedSourceVcf || !selectedSampleName) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const payload = {
        member_id: memberId,
        specimen_id: specimenId,
        analysis_id: analysisId,
        artifact_id: selectedSourceVcf.artifact_id,
        sample_name: selectedSampleName,
        binding_method: bindingMethod.trim(),
        evidence_reference: bindingReference.trim() || null,
      };
      const path = successorOf
        ? `/cases/${caseId}/pedigree/sample-bindings/${successorOf}/supersede`
        : `/cases/${caseId}/pedigree/sample-bindings`;
      await apiFetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      resetBindingForm();
      setNotice(t("familyIdentity.bindingRecorded"));
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("familyIdentity.errorAction"));
    } finally {
      setSaving(false);
    }
  };

  const beginEvidence = (binding: Binding, previous?: IdentityEvidence) => {
    setEvidenceBindingId(binding.binding_id);
    setCorrectingEvidenceId(previous?.evidence_id ?? "");
    setEvidenceType(previous?.evidence_type ?? "CHAIN_OF_CUSTODY");
    setEvidenceResult(previous?.result ?? "PASS");
    setEvidenceMethod(previous?.method ?? "");
    setEvidenceMethodVersion(previous?.method_version ?? "");
    setEvidenceReference(previous?.evidence_reference ?? "");
    setEvidenceArtifactId(previous?.source_artifact_id ?? "");
    setNotice("");
  };

  const saveEvidence = async () => {
    if (!canWrite || !evidenceBindingId || !evidenceMethod.trim() || !evidenceMethodVersion.trim() || !evidenceReference.trim()) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const payload = {
        evidence_type: evidenceType,
        result: evidenceResult,
        method: evidenceMethod.trim(),
        method_version: evidenceMethodVersion.trim(),
        evidence_reference: evidenceReference.trim(),
        source_artifact_id: evidenceArtifactId || null,
        metrics: {},
      };
      const path = correctingEvidenceId
        ? `/cases/${caseId}/pedigree/sample-bindings/${evidenceBindingId}/identity-evidence/${correctingEvidenceId}/supersede`
        : `/cases/${caseId}/pedigree/sample-bindings/${evidenceBindingId}/identity-evidence`;
      await apiFetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setEvidenceBindingId("");
      setCorrectingEvidenceId("");
      setEvidenceMethod("");
      setEvidenceMethodVersion("");
      setEvidenceReference("");
      setEvidenceArtifactId("");
      setNotice(t("familyIdentity.evidenceRecorded"));
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("familyIdentity.errorAction"));
    } finally {
      setSaving(false);
    }
  };

  const reviewEvidence = async (binding: Binding, evidence: IdentityEvidence, decision: "ACCEPTED" | "REJECTED") => {
    if (!canReview || !reviewReason.trim()) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await apiFetch(
        `/cases/${caseId}/pedigree/sample-bindings/${binding.binding_id}/identity-evidence/${evidence.evidence_id}/review`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision, reason: reviewReason.trim() }),
        },
      );
      setReviewReason("");
      setNotice(t("familyIdentity.evidenceStatus"));
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("familyIdentity.errorAction"));
    } finally {
      setSaving(false);
    }
  };

  const reviewBinding = async (binding: Binding, decision: "VERIFIED" | "REJECTED") => {
    if (!canReview || !reviewReason.trim()) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await apiFetch(
        `/cases/${caseId}/pedigree/sample-bindings/${binding.binding_id}/review`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision, reason: reviewReason.trim() }),
        },
      );
      setReviewReason("");
      setNotice(t("familyIdentity.bindingStatus"));
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("familyIdentity.errorAction"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="clinical-section" aria-labelledby="family-sample-identity-title">
      <div className="section-kicker" id="family-sample-identity-title">{t("familyIdentity.title")}</div>
      <div className="clinical-card">
        <p className="quiet">{t("familyIdentity.description")}</p>
        <p className="quiet"><strong>{t("familyIdentity.biologicalWarning")}</strong></p>
        <div className="panel-head">
          <h4>{t("familyIdentity.bindings")}</h4>
          <button className="secondary" type="button" onClick={() => void refresh()} disabled={loading || saving}>
            {loading ? t("familyIdentity.loading") : t("familyIdentity.refresh")}
          </button>
        </div>
        {error && <p className="danger-text" role="alert">{error}</p>}
        {notice && <p className="configuration-notice" role="status">{notice}</p>}
        {loading && <p className="quiet">{t("familyIdentity.loading")}</p>}
        {!loading && bindings.length === 0 && <p className="quiet">{t("familyIdentity.noBindings")}</p>}
        <div className="clinical-card">
          <h4>{t("familyIdentity.genotypeMatrix")}</h4>
          <p className="quiet">{t("familyIdentity.interpretationNotPerformed")}</p>
          <p className="context-row"><span>{t("familyIdentity.matrixVariant")}</span><strong>{variantId || "—"}</strong></p>
          {bindings.filter((binding) => binding.binding_status === "VERIFIED" && !supersededBindingIds.has(binding.binding_id)).length === 0
            ? <p className="quiet">{t("familyIdentity.noVerifiedBindings")}</p>
            : <div className="pedigree-member-list">
              {bindings.filter((binding) => binding.binding_status === "VERIFIED" && !supersededBindingIds.has(binding.binding_id)).map((binding) => (
                <label className="inline-check" key={binding.binding_id}>
                  <input
                    type="checkbox"
                    checked={selectedBindingIds.includes(binding.binding_id)}
                    onChange={(event) => setSelectedBindingIds((current) => event.target.checked
                      ? [...new Set([...current, binding.binding_id])]
                      : current.filter((id) => id !== binding.binding_id))}
                  />
                  {members.find((member) => member.id === binding.member_id)?.member_identifier ?? binding.member_id}
                  {" · "}{specimens.find((specimen) => specimen.specimen_id === binding.specimen_id)?.specimen_identifier ?? binding.specimen_id}
                  {" · "}{binding.sample_name}
                </label>
              ))}
            </div>}
          <button className="secondary" type="button" onClick={() => void loadMatrix()} disabled={matrixLoading || !variantId || selectedBindingIds.length === 0}>
            {matrixLoading ? t("familyIdentity.loading") : t("familyIdentity.loadMatrix")}
          </button>
          {matrix && <>
            <p className="quiet">{t("familyIdentity.callability")}: {matrix.callability_status} · {t("familyIdentity.matrixFingerprint")}: {matrix.matrix_fingerprint}</p>
            <div className="resources-table-wrap">
              <table className="resources-table">
                <thead><tr>
                  <th>{t("familyIdentity.member")}</th>
                  <th>{t("familyIdentity.specimen")}</th>
                  <th>{t("familyIdentity.sampleColumn")}</th>
                  <th>{t("familyIdentity.callState")}</th>
                  <th>{t("familyIdentity.genotype")}</th>
                  <th>{t("familyIdentity.sourceGenotype")}</th>
                  <th>{t("familyIdentity.zygosity")}</th>
                  <th>{t("familyIdentity.selectedAltDosage")}</th>
                  <th>{t("familyIdentity.normalizationStep")}</th>
                  <th>{t("familyIdentity.identityQcStatus")}</th>
                  <th>{t("familyIdentity.ploidyEvidence")}</th>
                  <th>{t("familyIdentity.phase")}</th>
                  <th>{t("familyIdentity.phaseSet")}</th>
                  <th>{t("familyIdentity.depth")}</th>
                  <th>{t("familyIdentity.genotypeQuality")}</th>
                  <th>{t("familyIdentity.alleleDepth")}</th>
                  <th>{t("familyIdentity.callability")}</th>
                </tr></thead>
                <tbody>
                  {(matrix.samples ?? []).flatMap((sample: any) => (sample.calls ?? []).map((call: any) => (
                    <tr key={`${sample.binding_id}-${call.variant_id}`}>
                      <td>{sample.member_identifier}</td>
                      <td>{specimens.find((specimen) => specimen.specimen_id === sample.specimen_id)?.specimen_identifier ?? sample.specimen_id}</td>
                      <td>{sample.vcf_sample_name}</td>
                      <td><span className="badge neutral">{call.call_state}</span></td>
                      <td>{call.projected_genotype ?? call.normalized_genotype ?? call.source_genotype ?? call.call_state}</td>
                      <td>{call.source_genotype ?? "—"}</td>
                      <td>{call.zygosity ?? "UNKNOWN"}</td>
                      <td>{call.selected_alt_dosage ?? "—"}</td>
                      <td>{sample.normalization_step_status ?? "—"}</td>
                      <td>{(sample.identity_evidence ?? []).map((item: any) => `${item.evidence_type}: ${item.review_status}/${item.result}`).join(" · ") || "—"}</td>
                      <td>{sample.ploidy_evidence?.status ?? "NOT_ASSESSED"}</td>
                      <td>{call.phase ?? "UNSPECIFIED"}</td>
                      <td>{call.phase_set ?? "—"}</td>
                      <td>{call.quality_metrics?.DP ?? "—"}</td>
                      <td>{call.quality_metrics?.GQ ?? "—"}</td>
                      <td>{Array.isArray(call.quality_metrics?.AD) ? call.quality_metrics.AD.join("/") : call.quality_metrics?.AD ?? "—"}</td>
                      <td>{call.callability ?? "NOT_ASSESSED"}</td>
                    </tr>
                  )))}
                </tbody>
              </table>
            </div>
          </>}
        </div>
        <div className="pedigree-member-list">
          {bindings.map((binding) => {
            const member = members.find((row) => row.id === binding.member_id);
            const specimen = specimens.find((row) => row.specimen_id === binding.specimen_id);
            const analysis = analyses.find((row) => row.analysis_id === binding.analysis_id);
            const evidence = evidenceByBinding[binding.binding_id] ?? [];
            const supersededEvidenceIds = new Set(evidence.map((row) => row.supersedes_evidence_id).filter(Boolean));
            const isActive = !supersededBindingIds.has(binding.binding_id);
            return (
              <article className="clinical-card" key={binding.binding_id}>
                <div className="panel-head">
                  <div>
                    <strong>{member?.member_identifier ?? binding.member_id}</strong>
                    <small>{specimen?.specimen_identifier ?? binding.specimen_id} · {analysis?.reference_build ?? "—"} · {binding.sample_name}</small>
                  </div>
                  <span className="badge neutral">{binding.binding_status} · {t("familyIdentity.revision")} {binding.version}</span>
                </div>
                <div className="context-row"><span>{t("familyIdentity.assay")}</span><strong>{analysis?.assay_id ?? "—"}</strong></div>
                <div className="context-row"><span>{t("familyIdentity.sourceVcf")}</span><strong>{analysis?.source_vcf?.filename ?? binding.artifact_id}</strong></div>
                <div className="context-row"><span>{t("familyIdentity.sourceDigest")}</span><strong>{binding.source_artifact_sha256}</strong></div>
                <div className="context-row"><span>{t("familyIdentity.analysisStatus")}</span><strong>{analysis?.analysis_status ?? "—"}</strong></div>
                <div className="context-row"><span>{t("familyIdentity.evidenceReference")}</span><strong>{binding.evidence_reference || "—"}</strong></div>
                <h5>{t("familyIdentity.identityEvidence")}</h5>
                {evidence.length === 0 && <p className="quiet">{t("familyIdentity.noEvidence")}</p>}
                {evidence.map((row) => (
                  <div className="context-row" key={row.evidence_id}>
                    <div>
                      <strong>{row.evidence_type} · {row.result}</strong>
                      <small>{row.method} v{row.method_version} · {row.evidence_reference} · {t("familyIdentity.revision")} {row.version}</small>
                    </div>
                    <span className="badge neutral">{row.review_status}{supersededEvidenceIds.has(row.evidence_id) ? ` · ${t("familyIdentity.superseded")}` : ""}</span>
                    {canReview && row.review_status === "PENDING" && !supersededEvidenceIds.has(row.evidence_id) && (
                      <div className="m10-form-grid">
                        <button className="secondary" type="button" disabled={saving || !reviewReason.trim()} onClick={() => void reviewEvidence(binding, row, "ACCEPTED")}>{t("familyIdentity.accept")}</button>
                        <button className="secondary" type="button" disabled={saving || !reviewReason.trim()} onClick={() => void reviewEvidence(binding, row, "REJECTED")}>{t("familyIdentity.reject")}</button>
                      </div>
                    )}
                    {canWrite && binding.binding_status === "UNVERIFIED" && !supersededEvidenceIds.has(row.evidence_id) && (
                      <button className="secondary" type="button" onClick={() => beginEvidence(binding, row)}>{t("familyIdentity.correctEvidence")}</button>
                    )}
                  </div>
                ))}
                {canWrite && binding.binding_status === "UNVERIFIED" && isActive && (
                  <button className="secondary" type="button" onClick={() => beginEvidence(binding)}>{t("familyIdentity.addEvidence")}</button>
                )}
                {canReview && binding.binding_status === "UNVERIFIED" && isActive && (
                  <div className="m10-form-grid">
                    <button className="primary" type="button" disabled={saving || !reviewReason.trim()} onClick={() => void reviewBinding(binding, "VERIFIED")}>{t("familyIdentity.verify")}</button>
                    <button className="secondary" type="button" disabled={saving || !reviewReason.trim()} onClick={() => void reviewBinding(binding, "REJECTED")}>{t("familyIdentity.rejectBinding")}</button>
                  </div>
                )}
                {canWrite && isActive && (
                  <button className="secondary" type="button" onClick={() => beginSuccessor(binding)}>{t("familyIdentity.createSuccessor")}</button>
                )}
              </article>
            );
          })}
        </div>
        {(canWrite || canReview) && (
          <label>{t("familyIdentity.reviewReason")}
            <textarea value={reviewReason} onChange={(event) => setReviewReason(event.target.value)} rows={2} maxLength={5000} />
          </label>
        )}
      </div>

      {canWrite && (
        <div className="clinical-card">
          <h4>{successorOf ? t("familyIdentity.createSuccessor") : t("familyIdentity.createBinding")}</h4>
          <div className="m10-form-grid">
            <label>{t("familyIdentity.member")}
              <select value={memberId} onChange={(event) => setMemberId(event.target.value)}>
                <option value="">—</option>
                {members.map((member) => <option key={member.id} value={member.id}>{member.member_identifier}{member.is_proband ? " · Proband" : ""}</option>)}
              </select>
            </label>
            <label>{t("familyIdentity.specimen")}
              <select value={specimenId} onChange={(event) => setSpecimenId(event.target.value)}>
                <option value="">—</option>
                {specimens.map((specimen) => <option key={specimen.specimen_id} value={specimen.specimen_id}>{specimen.specimen_identifier} · {specimen.specimen_type}</option>)}
              </select>
            </label>
            <label>{t("familyIdentity.analysis")}
              <select value={analysisId} onChange={(event) => {
                const value = event.target.value;
                setAnalysisId(value);
                const candidate = analyses.find((row) => row.analysis_id === value);
                if (candidate?.source_vcf?.specimen_id) setSpecimenId(candidate.source_vcf.specimen_id);
              }}>
                <option value="">—</option>
                {analyses.filter((analysis) => analysis.binding_candidate_status === "READY").map((analysis) => (
                  <option key={analysis.analysis_id} value={analysis.analysis_id}>{analysis.analysis_id} · {analysis.reference_build}</option>
                ))}
              </select>
            </label>
            <label>{t("familyIdentity.sampleColumn")}
              <input value={selectedSampleName} readOnly aria-readonly="true" />
            </label>
            <label>{t("familyIdentity.bindingMethod")}
              <input value={bindingMethod} onChange={(event) => setBindingMethod(event.target.value)} maxLength={100} />
            </label>
            <label>{t("familyIdentity.evidenceReference")}
              <input value={bindingReference} onChange={(event) => setBindingReference(event.target.value)} maxLength={1000} />
            </label>
          </div>
          {selectedAnalysis && selectedSourceVcf && (
            <div className="context-row">
              <span>{t("familyIdentity.sourceVcf")}</span>
              <strong>{selectedSourceVcf.filename} · SHA-256 {selectedSourceVcf.sha256}</strong>
            </div>
          )}
          {!analyses.some((analysis) => analysis.binding_candidate_status === "READY") && (
            <p className="quiet">{t("familyIdentity.noAnalysisCandidates")}</p>
          )}
          {selectedAnalysis && !selectedSampleName && (
            <p className="danger-text">{t("familyIdentity.selectedSampleMissing")}</p>
          )}
          <div className="m10-form-grid">
            <button className="primary" type="button" disabled={saving || !memberId || !specimenId || !selectedAnalysis || !selectedSourceVcf || !selectedSampleName || !bindingMethod.trim()} onClick={() => void saveBinding()}>
              {saving ? t("familyIdentity.saving") : successorOf ? t("familyIdentity.createSuccessor") : t("familyIdentity.createBinding")}
            </button>
            {successorOf && <button className="secondary" type="button" onClick={resetBindingForm}>{t("familyIdentity.reject")}</button>}
          </div>
        </div>
      )}

      {canWrite && evidenceBindingId && (
        <div className="clinical-card">
          <h4>{correctingEvidenceId ? t("familyIdentity.correctEvidence") : t("familyIdentity.addEvidence")}</h4>
          <div className="m10-form-grid">
            <label>{t("familyIdentity.evidenceType")}
              <select value={evidenceType} disabled={Boolean(correctingEvidenceId)} onChange={(event) => setEvidenceType(event.target.value)}>
                <option value="CHAIN_OF_CUSTODY">{t("familyIdentity.chainOfCustody")}</option>
                <option value="SAMPLE_IDENTITY_QC">{t("familyIdentity.sampleIdentityQc")}</option>
              </select>
            </label>
            <label>{t("familyIdentity.result")}
              <select value={evidenceResult} onChange={(event) => setEvidenceResult(event.target.value)}>
                <option value="PASS">PASS</option>
                <option value="FAIL">FAIL</option>
                <option value="INDETERMINATE">INDETERMINATE</option>
              </select>
            </label>
            <label>{t("familyIdentity.method")}<input value={evidenceMethod} onChange={(event) => setEvidenceMethod(event.target.value)} maxLength={200} /></label>
            <label>{t("familyIdentity.methodVersion")}<input value={evidenceMethodVersion} onChange={(event) => setEvidenceMethodVersion(event.target.value)} maxLength={100} /></label>
            <label>{t("familyIdentity.evidenceRef")}<input value={evidenceReference} onChange={(event) => setEvidenceReference(event.target.value)} maxLength={1000} /></label>
            <label>{t("familyIdentity.evidenceArtifact")}
              <select value={evidenceArtifactId} onChange={(event) => setEvidenceArtifactId(event.target.value)}>
                <option value="">{t("familyIdentity.noEvidenceArtifact")}</option>
                {artifacts.map((artifact) => <option key={artifact.artifact_id} value={artifact.artifact_id}>{artifact.filename} · {artifact.artifact_type} · {artifact.sha256.slice(0, 12)}</option>)}
              </select>
            </label>
          </div>
          <div className="m10-form-grid">
            <button className="primary" type="button" disabled={saving || !evidenceMethod.trim() || !evidenceMethodVersion.trim() || !evidenceReference.trim()} onClick={() => void saveEvidence()}>
              {saving ? t("familyIdentity.saving") : correctingEvidenceId ? t("familyIdentity.correctEvidence") : t("familyIdentity.addEvidence")}
            </button>
            <button className="secondary" type="button" onClick={() => { setEvidenceBindingId(""); setCorrectingEvidenceId(""); }}>{t("familyIdentity.reject")}</button>
          </div>
        </div>
      )}
      {!canWrite && !canReview && <p className="quiet">{t("familyIdentity.readOnlyRole")}</p>}
    </section>
  );
}
