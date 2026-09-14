"use client";

import { useEffect, useState } from "react";
import { firebaseAuth } from "../../../../lib/firebase";

const API_BASE = (process.env.NEXT_PUBLIC_SIRALOOM_API_BASE ?? "http://localhost:8000/api/v1").replace(/\/$/, "");

type Decision = { decision_id: string; variant_id: string; classification_id: string; version: number; status: string; disposition: string; priority_score: number; priority_band: string; reasons: string[]; review_version: number; reviewed_by?: string | null; approved_at?: string | null };
type Report = { report_id: string; version: number; status: string; language: string; report_type: string; artifact_id?: string | null; approved_by?: string | null; approved_at?: string | null; supersedes_report_id?: string | null; created_at?: string | null };

async function apiFetch(path: string, init?: RequestInit) {
  const token = await firebaseAuth?.currentUser?.getIdToken();
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers: { ...(init?.headers ?? {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  const text = await response.text(); let body: any = null; try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!response.ok) throw new Error(body?.detail ? String(body.detail) : `HTTP ${response.status}`);
  return body;
}

const pretty = (v: string) => v.toLowerCase().replaceAll("_", " ").replace(/\b\w/g, x => x.toUpperCase());
const badgeClass = (v: string) => ["FINAL", "APPROVED", "REPORT"].includes(v) ? "success" : ["REVIEW", "PROPOSED", "DRAFT"].includes(v) ? "active" : ["DO_NOT_REPORT", "SUPERSEDED"].includes(v) ? "neutral" : "danger";

export default function ReportsPage() {
  const [analysisId, setAnalysisId] = useState("");
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [reports, setReports] = useState<Report[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [reason, setReason] = useState("");
  const [reportType, setReportType] = useState("CLINICAL_INTERPRETATION");
  const [language, setLanguage] = useState("en");
  const [selected, setSelected] = useState<Decision | null>(null);
  const [disposition, setDisposition] = useState("REPORT");

  useEffect(() => setAnalysisId(window.localStorage.getItem("siraloom.analysis_id") ?? ""), []);

  const load = async () => {
    if (!analysisId) { setMessage("Enter or open an Analysis ID first."); return; }
    setLoading(true); setMessage("");
    try {
      const [r, d] = await Promise.all([apiFetch(`/analyses/${analysisId}/reports`), apiFetch(`/analyses/${analysisId}/reportability`)]);
      setReports(r.items ?? []); setDecisions(d.items ?? []);
      setSelected((cur) => cur && (d.items ?? []).some((x: Decision) => x.decision_id === cur.decision_id) ? cur : (d.items?.[0] ?? null));
    } catch (e) { setMessage(e instanceof Error ? e.message : "Unable to load reporting workspace."); }
    finally { setLoading(false); }
  };

  useEffect(() => { if (analysisId) load(); }, [analysisId]);

  const evaluate = async () => {
    try { await apiFetch(`/analyses/${analysisId}/reportability/evaluate`, { method: "POST" }); await load(); setMessage("Reportability proposals evaluated. Final dispositions still require authorized human review."); }
    catch (e) { setMessage(e instanceof Error ? e.message : "Unable to evaluate reportability."); }
  };

  const finalizeDecision = async () => {
    if (!selected || !reason.trim()) { setMessage("A reportability review reason is required."); return; }
    try {
      await apiFetch(`/reportability/${selected.decision_id}/finalize`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ disposition, expected_version: selected.review_version, reason: reason.trim() }) });
      setReason(""); await load(); setMessage("Reportability disposition finalized and audited.");
    } catch (e) { setMessage(e instanceof Error ? e.message : "Unable to finalize reportability."); }
  };

  const generate = async () => {
    try { await apiFetch(`/analyses/${analysisId}/reports`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ report_type: reportType, language, include_full_evidence: reportType === "ANALYTICAL" }) }); await load(); setMessage("Immutable report artifact generated as a draft."); }
    catch (e) { setMessage(e instanceof Error ? e.message : "Unable to generate report."); }
  };

  const finalize = async (report: Report) => {
    if (!reason.trim()) { setMessage("Use the review reason field for report sign-out."); return; }
    try { await apiFetch(`/reports/${report.report_id}/finalize`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_version: 0, reason: reason.trim() }) }); setReason(""); await load(); setMessage("Report approved/sign-out recorded. A newer final report supersedes the prior final version."); }
    catch (e) { setMessage(e instanceof Error ? e.message : "Report finalization failed."); }
  };

  const download = async (artifactId?: string | null) => {
    if (!artifactId) return;
    const token = await firebaseAuth?.currentUser?.getIdToken();
    const response = await fetch(`${API_BASE}/artifacts/${artifactId}/download`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!response.ok) { setMessage(`Download failed: HTTP ${response.status}`); return; }
    const blob = await response.blob(); const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = `siraloom-report-${artifactId}.pdf`; a.click(); URL.revokeObjectURL(url);
  };

  const reportabilityReady = decisions.length > 0 && decisions.every(d => d.status === "FINAL");
  const reportableCount = decisions.filter(d => d.status === "FINAL" && d.disposition === "REPORT").length;

  return <main className="reports-page">
    <header className="reports-header"><div><p className="eyebrow">GOVERNED REPORTING</p><h1>Reports & sign-out</h1><p className="lead compact">Separate reportability from pathogenicity classification, preserve every decision version, and release only an authorized immutable report artifact.</p></div></header>
    <section className="panel reports-controls"><div className="control-grid reports-control-grid"><label>Analysis ID<input value={analysisId} onChange={e => setAnalysisId(e.target.value.trim())} placeholder="Analysis UUID" /></label><label>Report type<select value={reportType} onChange={e => setReportType(e.target.value)}><option value="CLINICAL_INTERPRETATION">Clinical interpretation</option><option value="ANALYTICAL">Complete analytical</option></select></label><label>Language<select value={language} onChange={e => setLanguage(e.target.value)}><option value="en">English</option><option value="ar">Arabic</option><option value="bilingual">Bilingual</option></select></label></div><div className="actions-row"><button className="primary" onClick={load} disabled={loading}>{loading ? "Loading…" : "Refresh"}</button><button className="secondary" onClick={evaluate} disabled={!analysisId}>Evaluate reportability</button><button className="secondary" onClick={generate} disabled={!analysisId}>Generate draft</button></div>{message && <div className="configuration-notice">{message}</div>}</section>

    <div className="reports-grid">
      <section className="panel"><div className="panel-head"><div><div className="section-kicker">REPORTABILITY</div><h3>{decisions.length} decisions · {reportableCount} reportable</h3></div><span className={`badge ${reportabilityReady ? "success" : "active"}`}>{reportabilityReady ? "FINALIZED" : "REVIEW REQUIRED"}</span></div>
        {!decisions.length ? <div className="empty"><strong>No reportability decisions</strong><p>Evaluate the analysis to create versioned policy proposals.</p></div> : <div className="decision-list">{decisions.map(d => <button className={`decision-item ${selected?.decision_id === d.decision_id ? "selected" : ""}`} key={d.decision_id} onClick={() => { setSelected(d); setDisposition(d.disposition); }}><div><strong>{d.variant_id}</strong><span>Priority {d.priority_score} · {pretty(d.priority_band)}</span></div><div><span className={`badge ${badgeClass(d.status)}`}>{pretty(d.status)}</span><span className={`badge ${badgeClass(d.disposition)}`}>{pretty(d.disposition)}</span></div></button>)}</div>}
      </section>

      <section className="panel"><div className="panel-head"><div><div className="section-kicker">HUMAN REPORTABILITY REVIEW</div><h3>{selected ? "Selected decision" : "Select a decision"}</h3></div></div>{!selected ? <div className="empty"><strong>No decision selected</strong><p>Choose a reportability record to review its policy rationale and finalize its disposition.</p></div> : <><div className="review-summary-grid"><div><span>Variant</span><strong>{selected.variant_id}</strong></div><div><span>Disposition</span><strong>{pretty(selected.disposition)}</strong></div><div><span>Priority</span><strong>{selected.priority_score} · {pretty(selected.priority_band)}</strong></div><div><span>Review version</span><strong>{selected.review_version}</strong></div></div><div className="context-section"><div className="section-kicker">POLICY RATIONALE</div><ul>{selected.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul></div><div className="form-grid"><label>Final disposition<select value={disposition} disabled={selected.status === "FINAL"} onChange={e => setDisposition(e.target.value)}><option>REPORT</option><option>REVIEW</option><option>DO_NOT_REPORT</option></select></label><label className="span-2">Reviewer rationale<textarea value={reason} disabled={selected.status === "FINAL"} onChange={e => setReason(e.target.value)} rows={4} placeholder="Document the laboratory basis for the final reportability decision." /></label></div>{selected.status !== "FINAL" && <button className="primary" onClick={finalizeDecision}>Finalize reportability</button>}</>}</section>
    </div>

    <section className="panel reports-list-panel"><div className="panel-head"><div><div className="section-kicker">REPORT VERSIONS</div><h3>Immutable report lineage</h3></div></div>{!reports.length ? <div className="empty"><strong>No reports generated</strong><p>Generate a clinical or analytical draft after the analysis is available.</p></div> : <div className="report-version-list">{reports.map(r => <article className="report-version" key={r.report_id}><div><strong>Version {r.version} · {pretty(r.report_type)}</strong><span>{pretty(r.status)} · {r.language} · {r.created_at ? new Date(r.created_at).toLocaleString() : "—"}</span>{r.supersedes_report_id && <small>Supersedes {r.supersedes_report_id}</small>}</div><div className="actions-row"><span className={`badge ${badgeClass(r.status)}`}>{pretty(r.status)}</span>{r.artifact_id && <button className="secondary" onClick={() => download(r.artifact_id)}>PDF</button>}{r.status === "DRAFT" && <button className="primary" disabled={!reportabilityReady} onClick={() => finalize(r)}>Approve / sign out</button>}</div></article>)}</div>}</section>
    <p className="reports-footnote">SIRALOOM software validation is distinct from clinical laboratory validation, accreditation, or regulatory authorization. Release remains subject to the laboratory's qualified signatory, policies, and jurisdictional requirements.</p>
  </main>;
}
