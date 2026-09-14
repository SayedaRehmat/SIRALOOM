"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { firebaseAuth } from "../../../../lib/firebase";

type Step = {
  step_id: string;
  status: string;
  attempt: number;
  last_heartbeat?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  metadata?: Record<string, unknown>;
};

type Variant = {
  variant_id: string;
  genome_build: string;
  chromosome: string;
  position: number;
  reference: string;
  alternate: string;
};

type ReviewBundle = {
  review_status: string;
  classification?: {
    id?: string;
    result?: string;
    state?: string;
    review_status?: string;
    version?: number;
    review_version?: number;
  } | null;
  criteria: Array<{
    criterion: string;
    automated?: Record<string, unknown> | null;
    reviewed?: Record<string, unknown> | null;
    final?: Record<string, unknown> | null;
    state: string;
  }>;
  history: Array<{
    sequence_number?: number;
    action_type: string;
    reason: string;
    resulting_version?: number;
    created_at?: string;
  }>;
};

type CaseWorkspace = {
  case_id: string;
  case_identifier: string;
  status: string;
  language: string;
  clinical_context: Record<string, unknown>;
  specimens: Array<Record<string, unknown>>;
  analyses: Array<Record<string, unknown>>;
};

type AuditEvent = {
  event_id: string;
  event_type: string;
  analysis_id?: string | null;
  actor_type?: string;
  actor_id?: string;
  subject_type?: string | null;
  subject_id?: string | null;
  operation?: string | null;
  before_state?: Record<string, unknown> | null;
  after_state?: Record<string, unknown> | null;
  reason?: string | null;
  input_artifacts?: Array<Record<string, unknown>>;
  output_artifacts?: Array<Record<string, unknown>>;
  software?: Record<string, unknown>;
  workflow?: Record<string, unknown>;
  resource_versions?: Record<string, unknown>;
  occurred_at?: string;
};

type CompleteVariantRow = Record<string, string | number | null>;

type VariantDetail = {
  variant: Record<string, unknown>;
  annotations: Array<Record<string, unknown>>;
  population: Array<Record<string, unknown>>;
  evidence: Array<Record<string, unknown>>;
  acmg: Array<Record<string, unknown>>;
  classifications: Array<Record<string, unknown>>;
};

const API_BASE = (process.env.NEXT_PUBLIC_SIRALOOM_API_BASE ?? "http://localhost:8000/api/v1").replace(/\/$/, "");

const steps = [
  ["validate_input", "Input validation"],
  ["normalize", "Normalization"],
  ["annotate", "Annotation"],
  ["population", "Population context"],
  ["build_evidence", "Evidence"],
  ["acmg_assessment", "ACMG assessment"],
  ["review", "Human review"],
  ["report", "Report"],
  ["export_provenance", "Case history"],
] as const;

async function apiFetch(path: string, init?: RequestInit) {
  const token = await firebaseAuth?.currentUser?.getIdToken();
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!response.ok) {
    const message = typeof body === "object" && body && "detail" in body ? String((body as { detail: unknown }).detail) : `HTTP ${response.status}`;
    throw new Error(message);
  }
  return body as any;
}

function prettyStatus(status: string) {
  return status.toLowerCase().replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function statusTone(status: string) {
  if (["SUCCEEDED", "FINAL", "APPROVED", "COMPLETED"].includes(status)) return "success";
  if (["FAILED", "BLOCKED", "CANCELLED"].includes(status)) return "danger";
  if (["RUNNING", "QUEUED", "RETRYING", "IN_REVIEW", "PENDING"].includes(status)) return "active";
  return "neutral";
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

export default function Home() {
  const [caseId, setCaseId] = useState("");
  const [caseIdentifier, setCaseIdentifier] = useState("");
  const [caseWorkspace, setCaseWorkspace] = useState<CaseWorkspace | null>(null);
  const [specimenIdentifier, setSpecimenIdentifier] = useState("");
  const [specimenType, setSpecimenType] = useState("Blood");
  const [language, setLanguage] = useState<"en" | "ar" | "bilingual">("en");
  const [indication, setIndication] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [artifactId, setArtifactId] = useState("");
  const [analysisId, setAnalysisId] = useState("");
  const [analysis, setAnalysis] = useState<any>(null);
  const [variants, setVariants] = useState<Variant[]>([]);
  const [completeVariants, setCompleteVariants] = useState<CompleteVariantRow[]>([]);
  const [completeVariantColumns, setCompleteVariantColumns] = useState<string[]>([]);
  const [selectedVariantId, setSelectedVariantId] = useState("");
  const [variantDetail, setVariantDetail] = useState<VariantDetail | null>(null);
  const [review, setReview] = useState<ReviewBundle | null>(null);
  const [reportId, setReportId] = useState("");
  const [report, setReport] = useState<any>(null);
  const [exportId, setExportId] = useState("");
  const [exportStatus, setExportStatus] = useState("");
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [expandedAuditId, setExpandedAuditId] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
  const [connection, setConnection] = useState<"checking" | "online" | "offline">("checking");
  const [message, setMessage] = useState("");
  const [reviewReason, setReviewReason] = useState("");
  const [criterionReason, setCriterionReason] = useState("");
  const [expandedEvidence, setExpandedEvidence] = useState<string | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const currentStepIndex = useMemo(() => {
    const stepsFromApi: Step[] = analysis?.steps ?? [];
    let last = -1;
    steps.forEach(([id], index) => {
      const current = stepsFromApi.find((step) => step.step_id === id);
      if (current && ["SUCCEEDED", "RUNNING", "REQUIRES_REVIEW"].includes(current.status)) last = index;
    });
    return last;
  }, [analysis]);

  const annotationProgress = useMemo(() => {
    const annotation = (analysis?.steps as Step[] | undefined)?.find((step) => step.step_id === "annotate");
    const batches = annotation?.metadata?.batches;
    if (!batches || typeof batches !== "object") return null;
    const values = Object.values(batches as Record<string, unknown>).filter((value): value is Record<string, unknown> => !!value && typeof value === "object");
    const completed = values.filter((value) => value.status === "SUCCEEDED").length;
    return { completed, total: values.length };
  }, [analysis]);

  useEffect(() => {
    const storedCase = window.localStorage.getItem("siraloom.case_id") ?? "";
    const storedAnalysis = window.localStorage.getItem("siraloom.analysis_id") ?? "";
    const storedCaseIdentifier = window.localStorage.getItem("siraloom.case_identifier") ?? "";
    if (storedCase) setCaseId(storedCase);
    if (storedAnalysis) setAnalysisId(storedAnalysis);
    if (storedCaseIdentifier) setCaseIdentifier(storedCaseIdentifier);
    apiFetch("/health")
      .then(() => setConnection("online"))
      .catch(() => setConnection("offline"));
  }, []);

  useEffect(() => {
    if (!caseId) return;
    const loadCase = async () => {
      try {
        const data = await apiFetch(`/cases/${caseId}`);
        setCaseWorkspace(data);
        const indicationValue = data?.clinical_context?.indication;
        if (typeof indicationValue === "string") setIndication(indicationValue);
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "Unable to load case.");
      }
    };
    loadCase();
  }, [caseId]);

  useEffect(() => {
    if (!analysisId || !["SUCCEEDED", "REQUIRES_REVIEW"].includes(analysis?.status ?? "")) {
      setCompleteVariants([]);
      setCompleteVariantColumns([]);
      return;
    }
    apiFetch(`/analyses/${analysisId}/complete-variant-report`)
      .then((data) => {
        setCompleteVariants(data.variants ?? []);
        setCompleteVariantColumns(data.columns ?? []);
      })
      .catch((error) => setMessage(error instanceof Error ? error.message : "Unable to load complete variant report."));
  }, [analysisId, analysis?.status]);

  useEffect(() => {
    if (!analysisId) return;
    const loadAudit = async () => {
      try {
        const events = await apiFetch(`/cases/${caseId}/audit`);
        setAuditEvents(events);
      } catch {
        // Audit view is observational; analysis state remains authoritative.
      }
    };
    loadAudit();
    const timer = setInterval(loadAudit, 4000);
    return () => clearInterval(timer);
  }, [caseId, analysisId]);

  useEffect(() => {
    if (!analysisId) return;
    const poll = async () => {
      try {
        const next = await apiFetch(`/analyses/${analysisId}`);
        setAnalysis(next);
        setConnection("online");
        const completed = ["SUCCEEDED", "FAILED", "BLOCKED"].includes(next.status);
        if (completed && pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
        if (["SUCCEEDED", "REQUIRES_REVIEW"].includes(next.status)) {
          try {
            const vs = await apiFetch(`/analyses/${analysisId}/variants`);
            setVariants(vs);
            if (!selectedVariantId && vs.length) setSelectedVariantId(vs[0].variant_id);
          } catch {
            // Variant table can be unavailable during an intermediate step; the analysis state remains authoritative.
          }
        }
      } catch (error) {
        setConnection("offline");
        setMessage(`Backend reconnecting: ${error instanceof Error ? error.message : "connection unavailable"}`);
      }
    };
    poll();
    pollingRef.current = setInterval(poll, 2000);
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
      pollingRef.current = null;
    };
  }, [analysisId, selectedVariantId]);

  useEffect(() => {
    if (!exportId) return;
    let timer: ReturnType<typeof setInterval> | null = null;
    const pollExport = async () => {
      try {
        const result = await apiFetch(`/exports/${exportId}`);
        setExportStatus(result.status);
        if (["SUCCEEDED", "FAILED", "CANCELLED"].includes(result.status) && timer) {
          clearInterval(timer);
          timer = null;
        }
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "Unable to read export state.");
      }
    };
    pollExport();
    timer = setInterval(pollExport, 2000);
    return () => { if (timer) clearInterval(timer); };
  }, [exportId]);

  useEffect(() => {
    if (!analysisId || !selectedVariantId) return;
    const load = async () => {
      try {
        const [detail, reviewBundle] = await Promise.all([
          apiFetch(`/variants/${selectedVariantId}`),
          apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/review`).catch(() => null),
        ]);
        setVariantDetail(detail);
        setReview(reviewBundle);
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "Unable to load variant details.");
      }
    };
    load();
  }, [analysisId, selectedVariantId]);

  const createCase = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const result = await apiFetch("/cases", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          case_identifier: caseIdentifier.trim(),
          language,
          clinical_context: { indication: indication.trim() },
        }),
      });
      setCaseId(result.case_id);
      window.localStorage.setItem("siraloom.case_id", result.case_id);
      window.localStorage.setItem("siraloom.case_identifier", result.case_identifier);
      setMessage(result.created ? "Case created." : "Existing case loaded.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Case creation failed.");
    } finally {
      setBusy(false);
    }
  };

  const registerSpecimen = async () => {
    if (!caseId || !specimenIdentifier.trim()) {
      setMessage("A case and specimen identifier are required.");
      return;
    }
    setBusy(true);
    try {
      await apiFetch(`/cases/${caseId}/specimens`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ specimen_identifier: specimenIdentifier.trim(), specimen_type: specimenType }),
      });
      const next = await apiFetch(`/cases/${caseId}`);
      setCaseWorkspace(next);
      setSpecimenIdentifier("");
      setMessage("Specimen registered to the case.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Specimen registration failed.");
    } finally {
      setBusy(false);
    }
  };

  const uploadFile = async () => {
    if (!caseId || !file) {
      setMessage("Create/select a case and choose a VCF first.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const form = new FormData();
      form.append("file", file, file.name);
      const result = await apiFetch(`/cases/${caseId}/artifacts`, { method: "POST", body: form });
      setArtifactId(result.artifact_id);
      setMessage(`Input registered. SHA-256: ${result.sha256}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  };

  const createAndStart = async () => {
    if (!caseId || !artifactId) {
      setMessage("Case and uploaded VCF are required.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const created = await apiFetch(`/cases/${caseId}/analyses`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          input_artifact_id: artifactId,
          analysis_type: "VARIANT_INTERPRETATION",
          workflow_id: "variant-v1",
          workflow_version: "1.0",
          reference_build: "GRCh38",
        }),
      });
      setAnalysisId(created.analysis_id);
      window.localStorage.setItem("siraloom.analysis_id", created.analysis_id);
      await apiFetch(`/analyses/${created.analysis_id}/start`, { method: "POST" });
      setMessage("Analysis queued. You can close the browser; execution is server-side.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Analysis start failed.");
    } finally {
      setBusy(false);
    }
  };

  const startReview = async () => {
    if (!analysisId || !selectedVariantId) return;
    try {
      await apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/review/start`, { method: "POST" });
      const next = await apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/review`);
      setReview(next);
      setMessage("Review started.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to start review.");
    }
  };

  const reviewCriterion = async (criterion: string, decision: "ACCEPT" | "REJECT") => {
    const current = review?.criteria.find((item) => item.criterion === criterion);
    const expectedVersion = Number((current as any)?.review_version ?? 0);
    if (!analysisId || !selectedVariantId || !criterionReason.trim()) {
      setMessage("A review reason is required.");
      return;
    }
    try {
      await apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/acmg/${criterion}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          decision,
          reason: criterionReason.trim(),
          evidence_ids: [],
          expected_version: expectedVersion,
        }),
      });
      const next = await apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/review`);
      setReview(next);
      setCriterionReason("");
      setMessage(`${criterion} review saved.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Criterion review failed.");
    }
  };

  const requestMoreEvidence = async () => {
    const version = Number(review?.classification?.review_version ?? 0);
    if (!analysisId || !selectedVariantId || !reviewReason.trim()) {
      setMessage("A reason is required.");
      return;
    }
    try {
      await apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/review/more-evidence`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version: version, reason: reviewReason.trim() }),
      });
      const next = await apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/review`);
      setReview(next);
      setReviewReason("");
      setMessage("More evidence requested; classification remains pending.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Request for more evidence failed.");
    }
  };

  const approve = async () => {
    const version = Number(review?.classification?.review_version ?? 0);
    if (!analysisId || !selectedVariantId || !reviewReason.trim()) {
      setMessage("An approval reason is required.");
      return;
    }
    try {
      await apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/review/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version: version, reason: reviewReason.trim() }),
      });
      const next = await apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/review`);
      setReview(next);
      setReviewReason("");
      setMessage("Classification approved.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Approval failed.");
    }
  };

  const generateReport = async () => {
    if (!analysisId) return;
    setBusy(true);
    try {
      const result = await apiFetch(`/analyses/${analysisId}/reports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ report_type: "CLINICAL_INTERPRETATION", language, include_full_evidence: false }),
      });
      setReportId(result.report_id);
      const next = await apiFetch(`/reports/${result.report_id}`);
      setReport(next);
      setMessage(`Report draft ${result.version} generated.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Report generation failed.");
    } finally {
      setBusy(false);
    }
  };

  const finalize = async () => {
    if (!reportId) return;
    try {
      await apiFetch(`/reports/${reportId}/finalize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version: 0, reason: reviewReason || "Final report approved by reviewer." }),
      });
      const next = await apiFetch(`/reports/${reportId}`);
      setReport(next);
      setMessage("Report finalized.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Report finalization failed.");
    }
  };

  const exportHistory = async () => {
    if (!caseId) return;
    try {
      const result = await apiFetch(`/cases/${caseId}/exports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ include_artifacts: true, include_reports: true, include_evidence: true, include_audit: true, include_provenance: true }),
      });
      setExportId(result.export_id);
      setMessage("Complete case-history export queued. It is independent of the browser session.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Case export failed.");
    }
  };

  const handleFile = (event: ChangeEvent<HTMLInputElement>) => {
    setFile(event.target.files?.[0] ?? null);
  };

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">GENOMIC INTERPRETATION PLATFORM</div>
          <h1>SIRALOOM <span>Variant</span></h1>
          <p className="subtitle">VCF → evidence → review → report</p>
        </div>
        <div className="connection"><span className={`dot ${connection}`} />{connection === "online" ? "Backend connected" : connection === "checking" ? "Checking backend…" : "Reconnecting"}</div>
      </header>

      <section className="hero-grid">
        <div className="hero-card">
          <div className="hero-kicker">SERVICE 01</div>
          <h2>Explainable variant interpretation, built for long-running laboratory workflows.</h2>
          <p>Analysis state is persisted server-side. Closing the browser does not stop a running job.</p>
        </div>
        <div className="metric-card"><span>Pipeline</span><strong>{analysis?.status ? prettyStatus(analysis.status) : "Ready"}</strong></div>
        <div className="metric-card"><span>Case</span><strong>{caseIdentifier || "Not selected"}</strong></div>
      </section>

      {message && <div className="notice" role="status">{message}</div>}

      <section className="workspace-grid">
        <aside className="panel case-panel">
          <div className="panel-head"><div><div className="section-kicker">CASE</div><h3>Start a case</h3></div><span className={`badge ${statusTone(caseId ? "SUCCEEDED" : "READY")}`}>{caseId ? "Created" : "New"}</span></div>
          <form onSubmit={createCase} className="stack">
            <label>Case identifier<input value={caseIdentifier} onChange={(e: ChangeEvent<HTMLInputElement>) => setCaseIdentifier(e.target.value)} placeholder="LVP-2026-000184" required /></label>
            <label>Clinical indication<input value={indication} onChange={(e: ChangeEvent<HTMLInputElement>) => setIndication(e.target.value)} placeholder="Hereditary cancer evaluation" /></label>
            <label>Language<select value={language} onChange={(e: ChangeEvent<HTMLSelectElement>) => setLanguage(e.target.value as typeof language)}><option value="en">English</option><option value="ar">العربية</option><option value="bilingual">English + العربية</option></select></label>
            <button className="primary" disabled={busy || !caseIdentifier.trim()}>{caseId ? "Load case" : "Create case"}</button>
          </form>
          {caseId && <div className="keyline"><span>Case ID</span><code>{caseId}</code></div>}
          {caseId && <div className="case-context">
            <div className="section-kicker">SPECIMEN</div>
            <div className="specimen-form"><input value={specimenIdentifier} onChange={(e) => setSpecimenIdentifier(e.target.value)} placeholder="Specimen ID" /><select value={specimenType} onChange={(e) => setSpecimenType(e.target.value)}><option>Blood</option><option>Saliva</option><option>Buccal</option><option>Other</option></select><button className="secondary" onClick={registerSpecimen} disabled={busy || !specimenIdentifier.trim()}>Register specimen</button></div>
            {caseWorkspace?.specimens?.map((specimen, index) => <div className="keyline" key={String(specimen.specimen_id ?? index)}><span>{String(specimen.specimen_type ?? "Specimen")}</span><strong>{String(specimen.specimen_identifier ?? "—")}</strong></div>)}
          </div>}
        </aside>

        <section className="panel input-panel">
          <div className="panel-head"><div><div className="section-kicker">INPUT</div><h3>VCF intake</h3></div><span className="badge neutral">Phase 1</span></div>
          <div className="dropzone">
            <div className="drop-icon">VCF</div>
            <div><strong>{file?.name ?? "Choose a VCF / .vcf.gz"}</strong><p>Input is persisted before analysis begins.</p></div>
            <label className="secondary file-button">Choose<input type="file" accept=".vcf,.vcf.gz,.gz" onChange={handleFile} hidden /></label>
          </div>
          <div className="actions-row">
            <button className="secondary" onClick={uploadFile} disabled={busy || !caseId || !file}>Register input</button>
            <button className="primary" onClick={createAndStart} disabled={busy || !caseId || !artifactId}>Start analysis</button>
          </div>
          {artifactId && <div className="keyline"><span>Artifact ID</span><code>{artifactId}</code></div>}
        </section>

        <section className="panel workflow-panel">
          <div className="panel-head"><div><div className="section-kicker">EXECUTION</div><h3>Durable workflow</h3></div>{analysis?.status && <span className={`badge ${statusTone(analysis.status)}`}>{prettyStatus(analysis.status)}</span>}</div>
          <div className="timeline">
            {steps.map(([id, label], index) => {
              const step = (analysis?.steps as Step[] | undefined)?.find((item) => item.step_id === id);
              const status = step?.status ?? (index <= currentStepIndex ? "SUCCEEDED" : "PENDING");
              return <div key={id} className={`timeline-row ${statusTone(status)} ${index === currentStepIndex ? "current" : ""}`}>
                <div className="timeline-mark">{status === "SUCCEEDED" ? "✓" : status === "FAILED" || status === "BLOCKED" ? "!" : index === currentStepIndex ? "•" : "○"}</div>
                <div className="timeline-label"><strong>{label}</strong><span>{prettyStatus(status)}{step?.attempt ? ` · attempt ${step.attempt}` : ""}</span>{step?.error_message && <small>{step.error_message}</small>}</div>
              </div>;
            })}
          </div>
          {annotationProgress && <div className="run-meta"><span>Annotation checkpoints {annotationProgress.completed}/{annotationProgress.total} completed</span><span>Checkpoint state is persisted server-side</span></div>}
          {analysis?.started_at && <div className="run-meta"><span>Started {formatDate(analysis.started_at)}</span><span>Last state update {formatDate(analysis.completed_at ?? analysis.started_at)}</span></div>}
        </section>
      </section>

      <section className="panel variants-panel">
        <div className="panel-head"><div><div className="section-kicker">INTERPRETATION</div><h3>Prioritized variants</h3></div><span className="badge neutral">{variants.length} variants</span></div>
        {variants.length === 0 ? <div className="empty"><strong>Waiting for a completed analysis</strong><p>The table will populate from durable server state once annotation has produced variant records.</p></div> : <div className="table-wrap"><table><thead><tr><th>Variant</th><th>Position</th><th>Ref / Alt</th><th>Build</th><th>Review</th></tr></thead><tbody>{variants.map((v) => <tr key={v.variant_id} onClick={() => setSelectedVariantId(v.variant_id)} className={selectedVariantId === v.variant_id ? "selected" : ""}><td><code>{v.variant_id.slice(0, 12)}…</code></td><td>{v.chromosome}:{v.position.toLocaleString()}</td><td><code>{v.reference} → {v.alternate}</code></td><td>{v.genome_build}</td><td>{selectedVariantId === v.variant_id ? <span className="badge active">Selected</span> : <span className="badge neutral">Open</span>}</td></tr>)}</tbody></table></div>}
      </section>

      <section className="panel complete-report-panel">
        <div className="panel-head"><div><div className="section-kicker">COMPLETE VARIANT REPORT</div><h3>All analyzed variants</h3></div><span className="badge neutral">{completeVariants.length} rows</span></div>
        <div className="report-toolbar"><p>Inspection layer for the laboratory team. This is separate from the concise clinical report.</p><div className="actions-row"><a className="secondary link-button" href={analysisId ? `${API_BASE}/analyses/${analysisId}/complete-variant-report.csv` : "#"}>Download CSV</a><a className="secondary link-button" href={analysisId ? `${API_BASE}/analyses/${analysisId}/complete-variant-report.json` : "#"}>Download JSON</a></div></div>
        {completeVariants.length === 0 ? <div className="empty small"><strong>No complete variant dataset yet</strong><p>It becomes available after annotation has produced persistent variant records.</p></div> : <div className="table-wrap"><table><thead><tr>{completeVariantColumns.slice(0, 12).map((column) => <th key={column}>{column.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{completeVariants.slice(0, 100).map((row, index) => <tr key={String(row.variant_id ?? index)} onClick={() => typeof row.variant_id === "string" && setSelectedVariantId(row.variant_id)}>{completeVariantColumns.slice(0, 12).map((column) => <td key={column}><code>{String(row[column] ?? "—")}</code></td>)}</tr>)}</tbody></table>{completeVariants.length > 100 && <p className="table-note">Showing the first 100 rows for interactive inspection. Download the complete CSV/JSON for the full dataset.</p>}</div>}
      </section>

      <section className="detail-grid">
        <section className="panel evidence-panel">
          <div className="panel-head"><div><div className="section-kicker">EVIDENCE</div><h3>Variant evidence</h3></div></div>
          {!variantDetail ? <div className="empty"><strong>No variant selected</strong><p>Select a variant after analysis completion.</p></div> : <div className="evidence-stack">
            <div className="identity-card"><div><span>Canonical</span><strong>{String(variantDetail.variant.canonical_key ?? "—")}</strong></div><div><span>Normalization</span><strong>{String(variantDetail.variant.normalization_status ?? "—")}</strong></div></div>
            <div className="evidence-list">
              {variantDetail.population.map((item, index) => <div className="evidence-item" key={`pop-${index}`}><div><strong>Population · {String(item.label ?? item.population ?? "Unknown")}</strong><span>{String(item.availability ?? "—")}</span></div><code>{item.af == null ? "No data" : String(item.af)}</code></div>)}
              {variantDetail.evidence.map((item, index) => { const key = `ev-${index}`; const open = expandedEvidence === key; return <div className="evidence-item evidence-click" key={key} onClick={() => setExpandedEvidence(open ? null : key)}><div><strong>{String(item.type ?? "Evidence")}</strong><span>{String(item.source ?? "Unknown source")} · {String(item.source_version ?? "unversioned")}</span></div><span>{open ? "−" : "+"}</span>{open && <pre className="evidence-json">{JSON.stringify(item.payload ?? item.statement ?? {}, null, 2)}</pre>}</div>; })}
              {variantDetail.evidence.length === 0 && variantDetail.population.length === 0 && <div className="empty small"><strong>No evidence records yet</strong></div>}
            </div>
          </div>}
        </section>

        <section className="panel review-panel">
          <div className="panel-head"><div><div className="section-kicker">REVIEW</div><h3>Human decision workspace</h3></div>{review?.review_status && <span className={`badge ${statusTone(review.review_status)}`}>{prettyStatus(review.review_status)}</span>}</div>
          {!review ? <div className="empty"><strong>Review becomes available after interpretation</strong><p>Automated output remains proposed until a reviewer acts.</p></div> : <>
            <div className="classification-banner"><span>Proposed / current</span><strong>{String(review.classification?.result ?? "No classification")}</strong><small>Review revision {String(review.classification?.review_version ?? 0)}</small></div>
            <div className="actions-row"><button className="secondary" onClick={startReview} disabled={review.review_status === "APPROVED"}>Start review</button></div>
            <div className="criteria-grid">{review.criteria.map((item) => <div className="criterion-card" key={item.criterion}><div className="criterion-head"><strong>{item.criterion}</strong><span className={`badge ${statusTone(item.state)}`}>{prettyStatus(item.state)}</span></div><p>{String((item.automated as any)?.reason ?? "No automated rationale recorded.")}</p><div className="mini-actions"><button onClick={() => reviewCriterion(item.criterion, "ACCEPT")} className="ghost">Accept</button><button onClick={() => reviewCriterion(item.criterion, "REJECT")} className="ghost danger-text">Reject</button></div></div>)}</div>
            <label>Criterion review reason<input value={criterionReason} onChange={(e: ChangeEvent<HTMLInputElement>) => setCriterionReason(e.target.value)} placeholder="Why is this criterion accepted/rejected?" /></label>
            <label>Final approval reason<textarea value={reviewReason} onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setReviewReason(e.target.value)} placeholder="Explain the basis for the final reviewer decision." rows={3} /></label>
            <div className="actions-row"><button className="primary" onClick={approve} disabled={review.review_status !== "IN_REVIEW"}>Approve classification</button><button className="secondary" onClick={requestMoreEvidence} disabled={review.review_status !== "IN_REVIEW"}>Request more evidence</button><button className="secondary" onClick={generateReport} disabled={!analysisId || review.review_status !== "APPROVED"}>Generate report</button></div>
            <div className="history"><div className="section-kicker">DECISION HISTORY</div>{review.history.length === 0 ? <p>No review actions yet.</p> : review.history.map((item, index) => <div className="history-row" key={`${item.action_type}-${index}`}><span>{formatDate(item.created_at)}</span><strong>{item.action_type}</strong><p>{item.reason}</p></div>)}</div>
          </>}
        </section>
      </section>

      <section className="bottom-grid">
        <section className="panel report-panel"><div className="panel-head"><div><div className="section-kicker">REPORT</div><h3>Final report</h3></div>{report?.status && <span className={`badge ${statusTone(report.status)}`}>{prettyStatus(report.status)}</span>}</div>{!report ? <div className="empty"><strong>No report generated</strong><p>Report generation is downstream of reviewer-approved interpretation.</p></div> : <div className="report-preview"><div className="report-title">SIRALOOM Variant Report v{String(report.version)}</div><div className="report-summary">{String(report.content?.summary?.overall_result ?? "Interpretation available in report artifact.")}</div><div className="actions-row"><button className="primary" onClick={finalize} disabled={report.status === "FINAL"}>Finalize report</button>{report.artifact_id && <a className="secondary link-button" href={`${API_BASE}/artifacts/${report.artifact_id}/download`} target="_blank" rel="noreferrer">Open PDF</a>}</div></div>}</section>
        <section className="panel audit-panel"><div className="panel-head"><div><div className="section-kicker">AUDIT & PROVENANCE</div><h3>Case timeline</h3></div><span className="badge neutral">{auditEvents.length} events</span></div><div className="audit-callout"><strong>Every important action is reconstructable.</strong><p>Computational steps, resources, evidence, reviewer actions and report events are persisted to the case history.</p></div><div className="audit-timeline">{auditEvents.length === 0 ? <div className="empty small"><strong>No audit events yet</strong></div> : auditEvents.slice().reverse().slice(0, 20).map((event) => { const expanded = expandedAuditId === event.event_id; return <div className={`audit-event ${expanded ? "expanded" : ""}`} key={event.event_id} onClick={() => setExpandedAuditId(expanded ? null : event.event_id)}><span>{formatDate(event.occurred_at)}</span><div><strong>{prettyStatus(event.event_type)}</strong><small>{event.actor_type ?? "SYSTEM"} · {event.actor_id ?? "siraloom"}{event.operation ? ` · ${event.operation}` : ""}</small>{event.reason && <p>{event.reason}</p>}{expanded && <pre className="audit-json">{JSON.stringify({ before_state: event.before_state, after_state: event.after_state, input_artifacts: event.input_artifacts, output_artifacts: event.output_artifacts, software: event.software, workflow: event.workflow, resource_versions: event.resource_versions, subject: { type: event.subject_type, id: event.subject_id } }, null, 2)}</pre>}</div><span className="audit-toggle">{expanded ? "−" : "+"}</span></div>; })}</div><button className="secondary full" onClick={exportHistory} disabled={!caseId}>Export complete case history</button>{exportId && <><div className="keyline"><span>Export</span><code>{exportId}</code></div><div className="keyline"><span>Status</span><strong>{exportStatus ? prettyStatus(exportStatus) : "Queued"}</strong></div>{exportStatus === "SUCCEEDED" && <a className="secondary link-button full" href={`${API_BASE}/exports/${exportId}/download`} target="_blank" rel="noreferrer">Download case history ZIP</a>}</>}</section>
      </section>

      <footer className="footer"><span>SIRALOOM Variant v1</span><span>Scientific results remain subject to configured resources, review, validation scope, and laboratory governance.</span></footer>
    </main>
  );
}
