"use client";

import { useEffect, useState } from "react";
import { firebaseAuth } from "../../../../lib/firebase";
import { useLanguage } from "../../../../lib/i18n";

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
  const { language, t } = useLanguage();
  const [selected, setSelected] = useState<Decision | null>(null);
  const [disposition, setDisposition] = useState("REPORT");

  useEffect(() => {
    const bootstrapAnalysis = async () => {
      const caseId = window.localStorage.getItem("siraloom.case_id") ?? "";
      const storedAnalysis = window.localStorage.getItem("siraloom.analysis_id") ?? "";
      try {
        if (caseId) {
          const caseData = await apiFetch(`/cases/${caseId}`);
          const latest = Array.isArray(caseData?.analyses) && caseData.analyses.length
            ? caseData.analyses[0]
            : null;
          if (latest?.analysis_id) {
            const id = String(latest.analysis_id);
            setAnalysisId(id);
            window.localStorage.setItem("siraloom.analysis_id", id);
          } else {
            setAnalysisId("");
            window.localStorage.removeItem("siraloom.analysis_id");
          }
          return;
        }
      } catch (e) {
        setMessage(e instanceof Error ? e.message : "Unable to resolve the selected case.");
      }
      if (storedAnalysis) setAnalysisId(storedAnalysis);
    };
    bootstrapAnalysis();
  }, []);

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
    try { await apiFetch(`/analyses/${analysisId}/reports`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ report_type: reportType, language: language === "ar" ? "ar" : "en", include_full_evidence: reportType === "ANALYTICAL" }) }); await load(); setMessage("Immutable report artifact generated as a draft."); }
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
    <header className="reports-header"><div><p className="eyebrow">{t("reports.eyebrow")}</p><h1>{t("reports.title")}</h1><p className="lead compact">{t("reports.lead")}</p></div></header>
    <section className="panel reports-controls"><div className="control-grid reports-control-grid"><label>{t("reports.analysisId")}<input value={analysisId} onChange={e => setAnalysisId(e.target.value.trim())} placeholder={t("reports.analysisId")} /></label><label>{t("reports.type")}<select value={reportType} onChange={e => setReportType(e.target.value)}><option value="CLINICAL_INTERPRETATION">{t("reports.clinical")}</option><option value="ANALYTICAL">{t("reports.analytical")}</option></select></label></div><div className="actions-row"><button className="primary" onClick={load} disabled={loading}>{loading ? "Loading…" : "Refresh"}</button><button className="secondary" onClick={evaluate} disabled={!analysisId}>{t("reports.evaluate")}</button><button className="secondary" onClick={generate} disabled={!analysisId}>{t("reports.generate")}</button></div>{message && <div className="configuration-notice">{message}</div>}</section>

    <div className="reports-grid">
      <section className="panel"><div className="panel-head"><div><div className="section-kicker">{t("reports.section")}</div><h3>{decisions.length} decisions · {reportableCount} reportable</h3></div><span className={`badge ${reportabilityReady ? "success" : "active"}`}>{reportabilityReady ? "FINALIZED" : "REVIEW REQUIRED"}</span></div>
        {!decisions.length ? <div className="empty"><strong>{t("reports.none")}</strong><p>{t("reports.help")}</p></div> : <div className="decision-list">{decisions.map(d => <button className={`decision-item ${selected?.decision_id === d.decision_id ? "selected" : ""}`} key={d.decision_id} onClick={() => { setSelected(d); setDisposition(d.disposition); }}><div><strong>{d.variant_id}</strong><span>Priority {d.priority_score} · {pretty(d.priority_band)}</span></div><div><span className={`badge ${badgeClass(d.status)}`}>{pretty(d.status)}</span><span className={`badge ${badgeClass(d.disposition)}`}>{pretty(d.disposition)}</span></div></button>)}</div>}
      </section>

      <section className="panel"><div className="panel-head"><div><div className="section-kicker">{t("reports.human")}</div><h3>{selected ? "Selected decision" : "Select a decision"}</h3></div></div>{!selected ? <div className="empty"><strong>{t("reports.noSelected")}</strong><p>{t("reports.selectHelp")}</p></div> : <><div className="review-summary-grid"><div><span>{t("reports.variant")}</span><strong>{selected.variant_id}</strong></div><div><span>{t("reports.disposition")}</span><strong>{pretty(selected.disposition)}</strong></div><div><span>{t("reports.priority")}</span><strong>{selected.priority_score} · {pretty(selected.priority_band)}</strong></div><div><span>{t("reports.reviewVersion")}</span><strong>{selected.review_version}</strong></div></div><div className="context-section"><div className="section-kicker">{t("reports.policy")}</div><ul>{selected.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul></div><div className="form-grid"><label>{t("reports.finalDisposition")}<select value={disposition} disabled={selected.status === "FINAL"} onChange={e => setDisposition(e.target.value)}><option>REPORT</option><option>REVIEW</option><option>DO_NOT_REPORT</option></select></label><label className="span-2">{t("reports.rationale")}<textarea value={reason} disabled={selected.status === "FINAL"} onChange={e => setReason(e.target.value)} rows={4} placeholder={t("reports.rationalePlaceholder")} /></label></div>{selected.status !== "FINAL" && <button className="primary" onClick={finalizeDecision}>{t("reports.finalize")}</button>}</>}</section>
    </div>

    <section className="panel reports-list-panel"><div className="panel-head"><div><div className="section-kicker">{t("reports.versions")}</div><h3>{t("reports.lineage")}</h3></div></div>{!reports.length ? <div className="empty"><strong>{t("reports.noReports")}</strong><p>{t("reports.reportHelp")}</p></div> : <div className="report-version-list">{reports.map(r => <article className="report-version" key={r.report_id}><div><strong>Version {r.version} · {pretty(r.report_type)}</strong><span>{pretty(r.status)} · {r.language} · {r.created_at ? new Date(r.created_at).toLocaleString() : "—"}</span>{r.supersedes_report_id && <small>Supersedes {r.supersedes_report_id}</small>}</div><div className="actions-row"><span className={`badge ${badgeClass(r.status)}`}>{pretty(r.status)}</span>{r.artifact_id && <button className="secondary" onClick={() => download(r.artifact_id)}>{t("reports.pdf")}</button>}{r.status === "DRAFT" && <button className="primary" disabled={!reportabilityReady} onClick={() => finalize(r)}>{t("reports.signout")}</button>}</div></article>)}</div>}</section>
<p className="reports-footnote">{t("reports.validationDisclaimer")}</p>
  </main>;
}
