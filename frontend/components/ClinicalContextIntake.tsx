"use client";

import { useCallback, useEffect, useState } from "react";

type ApiFetch = (path: string, init?: RequestInit) => Promise<any>;
type Props = { caseId: string; apiFetch: ApiFetch };
type PriorTest = {
  test_type: string;
  test_type_system: string;
  test_type_code: string;
  test_type_display: string;
  performed_at: string;
  laboratory: string;
  accession_reference: string;
  result_status: string;
  result_summary: string;
  source_reference: string;
  artifact_id: string;
};
type Differential = {
  system: string;
  code: string;
  display: string;
  certainty: string;
  clinical_status: string;
};
type Revision = {
  revision_id: string;
  version: number;
  intake_status: string;
  phenotype_review_status: string;
  family_history_review_status: string;
  phenotype_review_note: string | null;
  family_history_review_note: string | null;
  completion_note: string | null;
  context: Record<string, any>;
  recorded_at: string;
  recorded_by: string;
};

const REVIEW_STATES = ["PENDING", "COMPLETE", "NOT_ASSESSED", "NOT_APPLICABLE"];
const RESULT_STATES = ["UNKNOWN", "POSITIVE", "NEGATIVE", "INCONCLUSIVE", "PENDING", "NOT_AVAILABLE"];
const CERTAINTY = ["CONSIDERED", "SUSPECTED", "CONFIRMED", "RULED_OUT", "UNKNOWN"];
const CLINICAL_STATUS = ["ACTIVE", "RULED_OUT", "RESOLVED", "UNKNOWN"];

const emptyPriorTest = (): PriorTest => ({
  test_type: "",
  test_type_system: "",
  test_type_code: "",
  test_type_display: "",
  performed_at: "",
  laboratory: "",
  accession_reference: "",
  result_status: "UNKNOWN",
  result_summary: "",
  source_reference: "",
  artifact_id: "",
});
const emptyDifferential = (): Differential => ({
  system: "http://snomed.info/sct",
  code: "",
  display: "",
  certainty: "CONSIDERED",
  clinical_status: "ACTIVE",
});

export default function ClinicalContextIntake({ caseId, apiFetch }: Props) {
  const [latest, setLatest] = useState<Revision | null>(null);
  const [history, setHistory] = useState<Revision[]>([]);
  const [referralIndication, setReferralIndication] = useState("");
  const [referralQuestion, setReferralQuestion] = useState("");
  const [referralDate, setReferralDate] = useState("");
  const [referringClinician, setReferringClinician] = useState("");
  const [referringOrganization, setReferringOrganization] = useState("");
  const [clinicalService, setClinicalService] = useState("");
  const [clinicalEncounterDate, setClinicalEncounterDate] = useState("");
  const [clinicalSummary, setClinicalSummary] = useState("");
  const [ageValue, setAgeValue] = useState("");
  const [ageUnit, setAgeUnit] = useState("YEARS");
  const [ageAsOfDate, setAgeAsOfDate] = useState("");
  const [priorTests, setPriorTests] = useState<PriorTest[]>([]);
  const [differentials, setDifferentials] = useState<Differential[]>([]);
  const [sourceReferences, setSourceReferences] = useState("");
  const [phenotypeReviewStatus, setPhenotypeReviewStatus] = useState("PENDING");
  const [familyReviewStatus, setFamilyReviewStatus] = useState("PENDING");
  const [phenotypeReviewNote, setPhenotypeReviewNote] = useState("");
  const [familyReviewNote, setFamilyReviewNote] = useState("");
  const [completionNote, setCompletionNote] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const applyRevision = useCallback((revision: Revision | null, legacy: Record<string, any> = {}) => {
    setLatest(revision);
    const context = revision?.context ?? {};
    setReferralIndication(context.referral_indication ?? legacy.indication ?? "");
    setReferralQuestion(context.referral_question ?? "");
    setReferralDate(context.referral_date ?? "");
    setReferringClinician(context.referring_clinician ?? "");
    setReferringOrganization(context.referring_organization ?? "");
    setClinicalService(context.clinical_service ?? "");
    setClinicalEncounterDate(context.clinical_encounter_date ?? "");
    setClinicalSummary(context.clinical_summary ?? "");
    setAgeValue(context.age_at_assessment?.value?.toString() ?? "");
    setAgeUnit(context.age_at_assessment?.unit ?? "YEARS");
    setAgeAsOfDate(context.age_at_assessment?.as_of_date ?? "");
    setPriorTests((context.prior_testing ?? []).map((item: any) => ({
      test_type: item.test_type ?? "",
      test_type_system: item.test_type_system ?? "",
      test_type_code: item.test_type_code ?? "",
      test_type_display: item.test_type_display ?? "",
      performed_at: item.performed_at ?? "",
      laboratory: item.laboratory ?? "",
      accession_reference: item.accession_reference ?? "",
      result_status: item.result_status ?? "UNKNOWN",
      result_summary: item.result_summary ?? "",
      source_reference: item.source_reference ?? "",
      artifact_id: item.artifact_id ?? "",
    })));
    setDifferentials((context.differential_diagnoses ?? []).map((item: any) => ({
      system: item.system ?? "http://snomed.info/sct",
      code: item.code ?? "",
      display: item.display ?? "",
      certainty: item.certainty ?? "CONSIDERED",
      clinical_status: item.clinical_status ?? "ACTIVE",
    })));
    setSourceReferences((context.source_document_references ?? []).join("\n"));
    setPhenotypeReviewStatus(revision?.phenotype_review_status ?? "PENDING");
    setFamilyReviewStatus(revision?.family_history_review_status ?? "PENDING");
    setPhenotypeReviewNote(revision?.phenotype_review_note ?? "");
    setFamilyReviewNote(revision?.family_history_review_note ?? "");
    setCompletionNote(revision?.completion_note ?? "");
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await apiFetch(`/cases/${caseId}/clinical-intake`);
      setHistory(result.revisions ?? []);
      applyRevision(result.latest ?? null, result.legacy_clinical_context ?? {});
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load clinical context revisions");
    } finally {
      setLoading(false);
    }
  }, [apiFetch, caseId, applyRevision]);

  useEffect(() => { void refresh(); }, [refresh]);

  const updatePriorTest = (index: number, key: keyof PriorTest, value: string) => {
    setPriorTests(current => current.map((item, i) => i === index ? { ...item, [key]: value } : item));
  };
  const updateDifferential = (index: number, key: keyof Differential, value: string) => {
    setDifferentials(current => current.map((item, i) => i === index ? { ...item, [key]: value } : item));
  };

  const save = async (intakeStatus: "DRAFT" | "COMPLETE" | "NOT_APPLICABLE") => {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const priorTesting = priorTests
        .filter(item => item.test_type.trim())
        .map(item => ({
          test_type: item.test_type.trim(),
          test_type_system: item.test_type_system.trim() || undefined,
          test_type_code: item.test_type_code.trim() || undefined,
          test_type_display: item.test_type_display.trim() || undefined,
          performed_at: item.performed_at || undefined,
          laboratory: item.laboratory.trim() || undefined,
          accession_reference: item.accession_reference.trim() || undefined,
          result_status: item.result_status,
          result_summary: item.result_summary.trim() || undefined,
          source_reference: item.source_reference.trim() || undefined,
          artifact_id: item.artifact_id.trim() || undefined,
        }));
      const differentialDiagnoses = differentials
        .filter(item => item.code.trim() || item.display.trim())
        .map(item => ({
          system: item.system.trim(),
          code: item.code.trim(),
          display: item.display.trim(),
          certainty: item.certainty,
          clinical_status: item.clinical_status,
        }));
      const payload = {
        intake_status: intakeStatus,
        referral_indication: referralIndication.trim() || undefined,
        referral_question: referralQuestion.trim() || undefined,
        referral_date: referralDate || undefined,
        referring_clinician: referringClinician.trim() || undefined,
        referring_organization: referringOrganization.trim() || undefined,
        clinical_service: clinicalService.trim() || undefined,
        clinical_encounter_date: clinicalEncounterDate || undefined,
        clinical_summary: clinicalSummary.trim() || undefined,
        age_at_assessment: ageValue.trim() ? {
          value: Number(ageValue),
          unit: ageUnit,
          as_of_date: ageAsOfDate || undefined,
        } : undefined,
        prior_testing: priorTesting,
        differential_diagnoses: differentialDiagnoses,
        source_document_references: sourceReferences.split(/[;\n]/).map(item => item.trim()).filter(Boolean),
        phenotype_review_status: phenotypeReviewStatus,
        family_history_review_status: familyReviewStatus,
        phenotype_review_note: phenotypeReviewNote.trim() || undefined,
        family_history_review_note: familyReviewNote.trim() || undefined,
        completion_note: completionNote.trim() || undefined,
      };
      const result = await apiFetch(`/cases/${caseId}/clinical-intake/revisions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      await refresh();
      setNotice(`Clinical intake revision v${result.version} saved with status ${result.intake_status}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save clinical intake revision");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="panel" id="clinical-context-intake">
      <div className="panel-head">
        <div>
          <div className="section-kicker">PRE-ANALYSIS · VERSIONED CLINICAL CONTEXT</div>
          <h3>Referral and clinical assessment</h3>
          <p className="muted">Append a dated clinical-context revision. Completed reviews require explicit phenotype and family-history states; missing records are never interpreted as negative findings.</p>
        </div>
        <span className="badge neutral">
          {latest ? `Revision v${latest.version} · ${latest.intake_status}` : "No clinical revision"}
        </span>
      </div>

      {error && <p className="danger-text" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}

      <div className="clinical-card">
        <h4>Referral context</h4>
        <div className="m10-form-grid">
          <label>Referral indication
            <textarea rows={2} maxLength={2000} value={referralIndication} onChange={event => setReferralIndication(event.target.value)} placeholder="Reason for referral and clinical concern" />
          </label>
          <label>Referral question
            <textarea rows={2} maxLength={5000} value={referralQuestion} onChange={event => setReferralQuestion(event.target.value)} placeholder="Specific diagnostic question the laboratory is being asked to address" />
          </label>
          <label>Referral date
            <input type="date" value={referralDate} onChange={event => setReferralDate(event.target.value)} />
          </label>
          <label>Referring clinician
            <input maxLength={300} value={referringClinician} onChange={event => setReferringClinician(event.target.value)} placeholder="Name or professional identifier" />
          </label>
          <label>Referring organization
            <input maxLength={300} value={referringOrganization} onChange={event => setReferringOrganization(event.target.value)} placeholder="Referring hospital, clinic or service" />
          </label>
          <label>Clinical service
            <input maxLength={200} value={clinicalService} onChange={event => setClinicalService(event.target.value)} placeholder="e.g. clinical genetics, neurology, pediatrics" />
          </label>
          <label>Clinical encounter date
            <input type="date" value={clinicalEncounterDate} onChange={event => setClinicalEncounterDate(event.target.value)} />
          </label>
          <label>Clinical summary
            <textarea rows={4} maxLength={15000} value={clinicalSummary} onChange={event => setClinicalSummary(event.target.value)} placeholder="Clinician-authored history, course, relevant investigations and context" />
          </label>
        </div>
        <h4>Patient age at assessment</h4>
        <div className="m10-form-grid">
          <label>Age value
            <input type="number" min="0" step="any" value={ageValue} onChange={event => setAgeValue(event.target.value)} placeholder="Age at clinical assessment" />
          </label>
          <label>Age unit
            <select value={ageUnit} onChange={event => setAgeUnit(event.target.value)}>{["YEARS", "MONTHS", "WEEKS", "DAYS"].map(unit => <option key={unit}>{unit}</option>)}</select>
          </label>
          <label>Age recorded as of (required with age)
            <input type="date" value={ageAsOfDate} onChange={event => setAgeAsOfDate(event.target.value)} />
          </label>
        </div>
      </div>

      <div className="clinical-card">
        <div className="panel-head">
          <h4>Prior genetic and relevant laboratory testing</h4>
          <button type="button" className="secondary" onClick={() => setPriorTests(current => [...current, emptyPriorTest()])}>Add prior test</button>
        </div>
        {priorTests.map((item, index) => (
          <div className="clinical-card" key={index}>
            <div className="m10-form-grid">
              <label>Test / assay (human-readable)
                <input value={item.test_type} onChange={event => updatePriorTest(index, "test_type", event.target.value)} placeholder="e.g. chromosomal microarray, exome sequencing" />
              </label>
              <label>Test terminology system URI
                <input value={item.test_type_system} onChange={event => updatePriorTest(index, "test_type_system", event.target.value)} placeholder="http://loinc.org (or another explicit code system URI)" />
              </label>
              <label>Test code
                <input value={item.test_type_code} onChange={event => updatePriorTest(index, "test_type_code", event.target.value)} placeholder="LOINC code when available" />
              </label>
              <label>Coded test display
                <input value={item.test_type_display} onChange={event => updatePriorTest(index, "test_type_display", event.target.value)} placeholder="Official display for the selected code" />
              </label>
              <label>Performed on
                <input type="date" value={item.performed_at} onChange={event => updatePriorTest(index, "performed_at", event.target.value)} />
              </label>
              <label>Laboratory
                <input value={item.laboratory} onChange={event => updatePriorTest(index, "laboratory", event.target.value)} />
              </label>
              <label>Accession / report reference
                <input value={item.accession_reference} onChange={event => updatePriorTest(index, "accession_reference", event.target.value)} />
              </label>
              <label>Result status
                <select value={item.result_status} onChange={event => updatePriorTest(index, "result_status", event.target.value)}>{RESULT_STATES.map(value => <option key={value}>{value}</option>)}</select>
              </label>
              <label>Linked SIRALOOM artifact ID (optional)
                <input value={item.artifact_id} onChange={event => updatePriorTest(index, "artifact_id", event.target.value)} placeholder="UUID of report artifact in this case" />
              </label>
              <label>Source reference
                <input value={item.source_reference} onChange={event => updatePriorTest(index, "source_reference", event.target.value)} placeholder="Report identifier or external source" />
              </label>
              <label>Result summary
                <textarea rows={2} value={item.result_summary} onChange={event => updatePriorTest(index, "result_summary", event.target.value)} placeholder="Clinician-recorded result summary; do not infer missing findings" />
              </label>
            </div>
            <button type="button" className="secondary" onClick={() => setPriorTests(current => current.filter((_, i) => i !== index))}>Remove prior test entry</button>
          </div>
        ))}
        <p className="quiet">Use a terminology code such as LOINC when a governed code is available. The system URI, code and display must be supplied together; free-text assay names remain available when no suitable code exists. Codes are stored as supplied and are not yet validated against a pinned terminology release.</p>
        {priorTests.length === 0 && <p className="quiet">No prior tests recorded. This is not interpreted as evidence that prior testing was not performed.</p>}
      </div>

      <div className="clinical-card">
        <div className="panel-head">
          <h4>Clinician-entered differential diagnoses</h4>
          <button type="button" className="secondary" onClick={() => setDifferentials(current => [...current, emptyDifferential()])}>Add differential</button>
        </div>
        {differentials.map((item, index) => (
          <div className="m10-form-grid" key={index}>
            <label>Terminology system URI
              <input value={item.system} onChange={event => updateDifferential(index, "system", event.target.value)} placeholder="e.g. http://snomed.info/sct" />
            </label>
            <label>Code
              <input value={item.code} onChange={event => updateDifferential(index, "code", event.target.value)} />
            </label>
            <label>Display
              <input value={item.display} onChange={event => updateDifferential(index, "display", event.target.value)} />
            </label>
            <label>Certainty
              <select value={item.certainty} onChange={event => {
                const value = event.target.value;
                updateDifferential(index, "certainty", value);
                if (value === "RULED_OUT") updateDifferential(index, "clinical_status", "RULED_OUT");
                else if (item.clinical_status === "RULED_OUT") updateDifferential(index, "clinical_status", "ACTIVE");
              }}>{CERTAINTY.map(value => <option key={value}>{value}</option>)}</select>
            </label>
            <label>Clinical status
              <select value={item.clinical_status} onChange={event => {
                const value = event.target.value;
                updateDifferential(index, "clinical_status", value);
                if (value === "RULED_OUT") updateDifferential(index, "certainty", "RULED_OUT");
                else if (item.certainty === "RULED_OUT") updateDifferential(index, "certainty", "CONSIDERED");
              }}>{CLINICAL_STATUS.map(value => <option key={value}>{value}</option>)}</select>
            </label>
            <button type="button" className="secondary" onClick={() => setDifferentials(current => current.filter((_, i) => i !== index))}>Remove differential</button>
          </div>
        ))}
        {differentials.length === 0 && <p className="quiet">No clinician-entered differential diagnoses recorded. SIRALOOM does not generate or infer this list.</p>}
      </div>

      <div className="clinical-card">
        <h4>Clinical review attestations</h4>
        <div className="m10-form-grid">
          <label>Phenotype review status
            <select value={phenotypeReviewStatus} onChange={event => setPhenotypeReviewStatus(event.target.value)}>{REVIEW_STATES.map(value => <option key={value}>{value}</option>)}</select>
          </label>
          <label>Family-history review status
            <select value={familyReviewStatus} onChange={event => setFamilyReviewStatus(event.target.value)}>{REVIEW_STATES.map(value => <option key={value}>{value}</option>)}</select>
          </label>
          <label>Phenotype review note / rationale
            <textarea rows={2} maxLength={5000} value={phenotypeReviewNote} onChange={event => setPhenotypeReviewNote(event.target.value)} placeholder="Required for NOT_ASSESSED/NOT_APPLICABLE, or when no proband findings are recorded" />
          </label>
          <label>Family-history review note / rationale
            <textarea rows={2} maxLength={5000} value={familyReviewNote} onChange={event => setFamilyReviewNote(event.target.value)} placeholder="Required for NOT_ASSESSED/NOT_APPLICABLE, or when no family findings are recorded" />
          </label>
          <label>Reason if the entire intake is not applicable
            <textarea rows={2} maxLength={5000} value={completionNote} onChange={event => setCompletionNote(event.target.value)} placeholder="Required only when marking this intake NOT_APPLICABLE" />
          </label>
          <label>Source document references (one per line)
            <textarea rows={2} value={sourceReferences} onChange={event => setSourceReferences(event.target.value)} placeholder="Accession, referral letter, clinical note or report identifiers" />
          </label>
        </div>
        <div className="actions-row">
          <button type="button" className="secondary" onClick={() => void save("DRAFT")} disabled={saving}>{saving ? "Saving…" : "Save draft revision"}</button>
          <button type="button" className="primary" onClick={() => void save("COMPLETE")} disabled={saving}>Complete clinical intake</button>
          <button type="button" className="secondary" onClick={() => void save("NOT_APPLICABLE")} disabled={saving}>Mark not applicable</button>
          <button type="button" className="secondary" onClick={() => void refresh()} disabled={loading}>{loading ? "Refreshing…" : "Refresh history"}</button>
        </div>
      </div>

      <div className="clinical-card">
        <h4>Immutable clinical intake revision history ({history.length})</h4>
        {history.length === 0 ? <p className="quiet">No clinical intake revision has been recorded. The case-level legacy indication remains available but is not treated as a completed clinical intake attestation.</p> : (
          <div className="stack">
            {history.map(revision => (
              <article className="keyline" key={revision.revision_id}>
                <div>
                  <strong>Revision v{revision.version} · {revision.intake_status}</strong>
                  <div>Phenotype review: {revision.phenotype_review_status} · Family history review: {revision.family_history_review_status}</div>
                  <small>{new Date(revision.recorded_at).toLocaleString()} · Recorded by {revision.recorded_by}</small>
                  {revision.context?.referral_indication && <p>{revision.context.referral_indication}</p>}
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
