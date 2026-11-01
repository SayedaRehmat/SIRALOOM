"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type ApiFetch = (path: string, init?: RequestInit) => Promise<any>;
type Props = { caseId: string; apiFetch: ApiFetch };
type PhenotypeRow = {
  phenotype_id: string;
  hpo_id: string;
  canonical_hpo_id?: string | null;
  label?: string | null;
  phenotype_status: string;
  subject_member_id?: string | null;
  observed_at?: string | null;
  onset?: string | null;
  severity?: string | null;
  clinical_attributes?: Record<string, any>;
  ontology_resolution?: Record<string, any>;
  source?: string;
  evidence?: Record<string, any>;
};
type Term = { hpo_id: string; label: string };
type Member = {
  id: string;
  member_identifier: string;
  relationship_to_proband?: string | null;
  is_proband?: boolean;
  affected_status?: string;
};

const STATUSES = ["PRESENT", "ABSENT", "EXCLUDED", "UNKNOWN", "NOT_ASSESSED"];
const AGE_UNITS = ["YEARS", "MONTHS", "WEEKS", "DAYS"];
const LATERALITY = ["UNKNOWN", "LEFT", "RIGHT", "BILATERAL", "UNILATERAL", "MIDLINE", "NOT_APPLICABLE"];
const TEMPORAL = ["UNKNOWN", "CONTINUOUS", "EPISODIC", "RECURRENT", "PROGRESSIVE", "REGRESSIVE", "STATIC"];

function toIso8601Duration(value: string, unit: string): string {
  const numeric = value.trim();
  if (!/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(numeric) || !Number.isFinite(Number(numeric)) || Number(numeric) < 0) {
    throw new Error("Age values must be finite and non-negative.");
  }
  const suffix: Record<string, string> = { YEARS: "Y", MONTHS: "M", WEEKS: "W", DAYS: "D" };
  const component = suffix[unit];
  if (!component) throw new Error("Unsupported age unit.");
  return `P${numeric}${component}`;
}


export default function PhenotypeIntake({ caseId, apiFetch }: Props) {
  const [rows, setRows] = useState<PhenotypeRow[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [termQuery, setTermQuery] = useState("");
  const [terms, setTerms] = useState<Term[]>([]);
  const [ontologyAvailability, setOntologyAvailability] = useState("CHECKING");
  const [hpoId, setHpoId] = useState("");
  const [label, setLabel] = useState("");
  const [status, setStatus] = useState("PRESENT");
  const [subjectMemberId, setSubjectMemberId] = useState("");
  const [observedAt, setObservedAt] = useState("");
  const [onset, setOnset] = useState("");
  const [severity, setSeverity] = useState("");
  const [ageValue, setAgeValue] = useState("");
  const [ageUnit, setAgeUnit] = useState("YEARS");
  const [resolutionAgeValue, setResolutionAgeValue] = useState("");
  const [resolutionAgeUnit, setResolutionAgeUnit] = useState("YEARS");
  const [severityHpoId, setSeverityHpoId] = useState("");
  const [laterality, setLaterality] = useState("UNKNOWN");
  const [temporalPattern, setTemporalPattern] = useState("UNKNOWN");
  const [courseHpoId, setCourseHpoId] = useState("");
  const [modifierIds, setModifierIds] = useState("");
  const [siteSystem, setSiteSystem] = useState("");
  const [siteCode, setSiteCode] = useState("");
  const [siteDisplay, setSiteDisplay] = useState("");
  const [episodeCount, setEpisodeCount] = useState("");
  const [episodePeriod, setEpisodePeriod] = useState("");
  const [episodeUnit, setEpisodeUnit] = useState("WEEKS");
  const [source, setSource] = useState("CLINICAL_INPUT");
  const [evidenceReference, setEvidenceReference] = useState("");
  const [clinicalNote, setClinicalNote] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    if (!caseId) return;
    setLoading(true);
    setError("");
    try {
      const [phenotypeResult, pedigreeResult] = await Promise.all([
        apiFetch(`/cases/${caseId}/phenotypes`),
        apiFetch(`/cases/${caseId}/pedigree`),
      ]);
      setRows(phenotypeResult.phenotypes ?? []);
      setMembers(pedigreeResult.members ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load clinical phenotype intake");
    } finally {
      setLoading(false);
    }
  }, [apiFetch, caseId]);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    const query = termQuery.trim();
    if (query.length < 2) {
      setTerms([]);
      setOntologyAvailability("NOT_CHECKED");
      return;
    }
    let cancelled = false;
    const handle = window.setTimeout(async () => {
      try {
        const result = await apiFetch(`/cases/${caseId}/phenotype-terms?q=${encodeURIComponent(query)}&limit=20`);
        if (cancelled) return;
        setOntologyAvailability(result.availability ?? "UNAVAILABLE");
        setTerms(result.terms ?? []);
      } catch {
        if (cancelled) return;
        setOntologyAvailability("UNAVAILABLE");
        setTerms([]);
      }
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [apiFetch, caseId, termQuery]);

  const selectedMember = useMemo(
    () => members.find(member => member.id === subjectMemberId),
    [members, subjectMemberId],
  );

  const selectTerm = (term: Term) => {
    setHpoId(term.hpo_id);
    setLabel(term.label);
    setTermQuery(`${term.hpo_id} · ${term.label}`);
    setTerms([]);
  };

  const resetForm = () => {
    setHpoId("");
    setLabel("");
    setTermQuery("");
    setStatus("PRESENT");
    setObservedAt("");
    setOnset("");
    setSeverity("");
    setAgeValue("");
    setResolutionAgeValue("");
    setResolutionAgeUnit("YEARS");
    setSeverityHpoId("");
    setLaterality("UNKNOWN");
    setTemporalPattern("UNKNOWN");
    setCourseHpoId("");
    setModifierIds("");
    setSiteSystem("");
    setSiteCode("");
    setSiteDisplay("");
    setEpisodeCount("");
    setEpisodePeriod("");
    setEvidenceReference("");
    setClinicalNote("");
  };

  const save = async () => {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const clinicalAttributes: Record<string, any> = {
        laterality,
        temporal_pattern: temporalPattern,
      };
      if (ageValue.trim()) clinicalAttributes.onset_age_iso8601 = toIso8601Duration(ageValue, ageUnit);
      if (resolutionAgeValue.trim()) clinicalAttributes.resolution_age_iso8601 = toIso8601Duration(resolutionAgeValue, resolutionAgeUnit);
      if (severityHpoId.trim()) clinicalAttributes.severity_hpo_id = severityHpoId.trim();
      if (courseHpoId.trim()) clinicalAttributes.clinical_course_hpo_id = courseHpoId.trim();
      const modifiers = modifierIds.split(/[;,\s]+/).map(value => value.trim()).filter(Boolean);
      if (modifiers.length) clinicalAttributes.modifier_hpo_ids = modifiers;
      if (siteSystem.trim() || siteCode.trim() || siteDisplay.trim()) {
        clinicalAttributes.anatomical_site = {
          system: siteSystem.trim(),
          code: siteCode.trim(),
          display: siteDisplay.trim() || undefined,
        };
      }
      if (episodeCount.trim() || episodePeriod.trim()) {
        clinicalAttributes.episode_frequency = {
          count: Number(episodeCount),
          period_value: Number(episodePeriod),
          period_unit: episodeUnit,
        };
      }
      const evidence: Record<string, string> = {};
      if (evidenceReference.trim()) evidence.source_reference = evidenceReference.trim();
      if (clinicalNote.trim()) evidence.clinical_note = clinicalNote.trim();

      const saved = await apiFetch(`/cases/${caseId}/phenotypes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          hpo_id: hpoId.trim(),
          label: label.trim() || undefined,
          phenotype_status: status,
          subject_member_id: subjectMemberId || undefined,
          observed_at: observedAt ? new Date(observedAt).toISOString() : undefined,
          onset: onset.trim() || undefined,
          severity: severity.trim() || undefined,
          clinical_attributes: clinicalAttributes,
          source,
          evidence,
        }),
      });
      await refresh();
      const resolution = saved?.ontology_resolution?.primary_term?.status ?? "UNKNOWN";
      setNotice(
        resolution === "CURRENT" || resolution === "ALTERNATE_ID"
          ? `Observation saved; HPO term resolution: ${resolution}.`
          : `Observation saved, but HPO term resolution is ${resolution}. It remains visible for review and is not silently treated as a validated term.`,
      );
      resetForm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save phenotype observation");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="panel" id="clinical-phenotype-intake">
      <div className="panel-head">
        <div>
          <div className="section-kicker">PRE-ANALYSIS · CLINICAL PHENOTYPE INTAKE</div>
          <h3>Patient and family phenotype observations</h3>
          <p className="muted">Record observed clinical findings before variant interpretation. Present, absent, excluded, unknown and not-assessed states remain distinct.</p>
        </div>
        <span className={`badge ${ontologyAvailability === "AVAILABLE" ? "success" : "neutral"}`}>
          HPO ontology: {ontologyAvailability}
        </span>
      </div>

      {error && <p className="danger-text" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}

      <div className="clinical-card">
        <h4>Phenotype term and subject</h4>
        <div className="m10-form-grid">
          <label>HPO term search or identifier
            <input value={termQuery} onChange={event => { setTermQuery(event.target.value); setHpoId(""); setLabel(""); }} placeholder="Search a clinical feature or enter HP:0000000" />
          </label>
          <label>HPO identifier
            <input value={hpoId} onChange={event => setHpoId(event.target.value.toUpperCase())} placeholder="HP:0000000" />
          </label>
          <label>Term label (clinical display)
            <input value={label} onChange={event => setLabel(event.target.value)} maxLength={500} placeholder="Resolved HPO label or clinician wording" />
          </label>
          <label>Observation subject
            <select value={subjectMemberId} onChange={event => setSubjectMemberId(event.target.value)}>
              <option value="">Proband / primary patient</option>
              {members.map(member => <option key={member.id} value={member.id}>{member.member_identifier}{member.relationship_to_proband ? ` · ${member.relationship_to_proband}` : ""}{member.is_proband ? " · proband" : ""}</option>)}
            </select>
          </label>
          <label>Clinical status
            <select value={status} onChange={event => setStatus(event.target.value)}>
              {STATUSES.map(value => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}
            </select>
          </label>
          <label>Observed at
            <input type="datetime-local" value={observedAt} onChange={event => setObservedAt(event.target.value)} />
          </label>
        </div>
        {terms.length > 0 && (
          <div className="stack" role="listbox" aria-label="HPO search results">
            {terms.map(term => (
              <button type="button" className="secondary" key={term.hpo_id} onClick={() => selectTerm(term)}>
                <strong>{term.hpo_id}</strong> · {term.label}
              </button>
            ))}
          </div>
        )}
        {ontologyAvailability === "UNAVAILABLE" && <p className="quiet">No single approved, technically qualified HPO ontology is available for this case. You may preserve the entered identifier, but SIRALOOM will mark its resolution unavailable and require review.</p>}
        {selectedMember && <p className="quiet">This observation belongs to family member {selectedMember.member_identifier}; it will not be merged into the proband's phenotype set.</p>}
      </div>

      <div className="clinical-card">
        <h4>Clinical characterization</h4>
        <div className="m10-form-grid">
          <label>Onset description
            <input value={onset} onChange={event => setOnset(event.target.value)} maxLength={200} placeholder="e.g. since infancy; first noted at age 4" />
          </label>
          <label>Onset age value
            <input type="number" min="0" step="any" value={ageValue} onChange={event => setAgeValue(event.target.value)} placeholder="Age at onset" />
          </label>
          <label>Age unit
            <select value={ageUnit} onChange={event => setAgeUnit(event.target.value)}>{AGE_UNITS.map(unit => <option key={unit}>{unit}</option>)}</select>
          </label>
          <label>Resolution age value (if resolved)
            <input type="number" min="0" step="any" value={resolutionAgeValue} onChange={event => setResolutionAgeValue(event.target.value)} placeholder="Age when feature resolved" />
          </label>
          <label>Resolution age unit
            <select value={resolutionAgeUnit} onChange={event => setResolutionAgeUnit(event.target.value)}>{AGE_UNITS.map(unit => <option key={unit}>{unit}</option>)}</select>
          </label>
          <label>Severity (clinician wording)
            <input value={severity} onChange={event => setSeverity(event.target.value)} maxLength={100} placeholder="Clinician-recorded severity" />
          </label>
          <label>Severity HPO ID
            <input value={severityHpoId} onChange={event => setSeverityHpoId(event.target.value.toUpperCase())} placeholder="Optional HP:... severity term" />
          </label>
          <label>Laterality
            <select value={laterality} onChange={event => setLaterality(event.target.value)}>{LATERALITY.map(value => <option key={value}>{value}</option>)}</select>
          </label>
          <label>Temporal pattern
            <select value={temporalPattern} onChange={event => setTemporalPattern(event.target.value)}>{TEMPORAL.map(value => <option key={value}>{value}</option>)}</select>
          </label>
          <label>Clinical course HPO ID
            <input value={courseHpoId} onChange={event => setCourseHpoId(event.target.value.toUpperCase())} placeholder="Optional HP:..." />
          </label>
          <label>HPO modifier IDs (comma-separated)
            <input value={modifierIds} onChange={event => setModifierIds(event.target.value.toUpperCase())} placeholder="Optional HP:... modifiers" />
          </label>
        </div>
        <h4>Anatomical site and episodic frequency (optional)</h4>
        <div className="m10-form-grid">
          <label>Terminology system URI
            <input value={siteSystem} onChange={event => setSiteSystem(event.target.value)} placeholder="e.g. SNOMED CT system URI" />
          </label>
          <label>Site code
            <input value={siteCode} onChange={event => setSiteCode(event.target.value)} placeholder="Code" />
          </label>
          <label>Site display
            <input value={siteDisplay} onChange={event => setSiteDisplay(event.target.value)} placeholder="Human-readable site" />
          </label>
          <label>Episodes per period
            <input type="number" min="1" step="1" value={episodeCount} onChange={event => setEpisodeCount(event.target.value)} placeholder="Count" />
          </label>
          <label>Period value
            <input type="number" min="0.001" step="any" value={episodePeriod} onChange={event => setEpisodePeriod(event.target.value)} placeholder="Period" />
          </label>
          <label>Period unit
            <select value={episodeUnit} onChange={event => setEpisodeUnit(event.target.value)}>{["HOURS", "DAYS", "WEEKS", "MONTHS", "YEARS"].map(unit => <option key={unit}>{unit}</option>)}</select>
          </label>
        </div>
      </div>

      <div className="clinical-card">
        <h4>Evidence and source provenance</h4>
        <div className="m10-form-grid">
          <label>Observation source
            <select value={source} onChange={event => setSource(event.target.value)}>
              <option>CLINICAL_INPUT</option><option>CLINICIAN_EXAMINATION</option><option>MEDICAL_RECORD</option><option>FAMILY_HISTORY</option><option>LABORATORY_REPORT</option><option>PATIENT_REPORTED</option><option>OTHER</option>
            </select>
          </label>
          <label>Source document / accession / reference
            <input value={evidenceReference} onChange={event => setEvidenceReference(event.target.value)} maxLength={1000} placeholder="Document identifier or source reference" />
          </label>
        </div>
        <label>Clinical note / evidence context
          <textarea value={clinicalNote} onChange={event => setClinicalNote(event.target.value)} rows={3} maxLength={5000} placeholder="Record the source and context; avoid unsupported interpretation." />
        </label>
        <div className="actions-row">
          <button type="button" className="primary" onClick={save} disabled={saving || !hpoId.trim()}>{saving ? "Saving…" : "Save phenotype observation"}</button>
          <button type="button" className="secondary" onClick={resetForm} disabled={saving}>Clear form</button>
          <button type="button" className="secondary" onClick={() => void refresh()} disabled={loading}>{loading ? "Refreshing…" : "Refresh observations"}</button>
        </div>
      </div>

      <div className="clinical-card">
        <h4>Recorded phenotype observations ({rows.length})</h4>
        {loading ? <p className="quiet">Loading observations…</p> : rows.length === 0 ? <p className="quiet">No phenotype observations have been recorded. Absence of records is not interpreted as absence of clinical features.</p> : (
          <div className="stack">
            {rows.map(row => {
              const resolution = row.ontology_resolution?.primary_term?.status ?? "NOT_RECORDED";
              const member = members.find(item => item.id === row.subject_member_id);
              return (
                <article className="keyline" key={row.phenotype_id}>
                  <div>
                    <strong>{row.canonical_hpo_id || row.hpo_id} · {row.label || row.ontology_resolution?.primary_term?.label || "Unresolved term"}</strong>
                    <div>{row.phenotype_status.replaceAll("_", " ")} · {member ? member.member_identifier : "Proband / primary patient"} · HPO {resolution}</div>
                    <small>{row.observed_at ? new Date(row.observed_at).toLocaleString() : "Observation time not supplied"}{row.onset ? ` · Onset: ${row.onset}` : ""}{row.severity ? ` · Severity: ${row.severity}` : ""}{row.clinical_attributes?.severity_hpo_id ? ` · Severity term: ${row.clinical_attributes.severity_hpo_id}` : ""}</small>
                    {resolution !== "CURRENT" && resolution !== "ALTERNATE_ID" && <small className="danger-text">Requires terminology review; not treated as a validated HPO term.</small>}
                    {row.clinical_attributes && Object.keys(row.clinical_attributes).length > 0 && <details><summary>Clinical attributes</summary><pre>{JSON.stringify(row.clinical_attributes, null, 2)}</pre></details>}
                    {row.evidence && Object.keys(row.evidence).length > 0 && <details><summary>Source evidence</summary><pre>{JSON.stringify(row.evidence, null, 2)}</pre></details>}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
