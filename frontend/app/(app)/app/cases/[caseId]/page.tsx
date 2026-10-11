"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { firebaseAuth } from "../../../../../lib/firebase";
import { useLanguage } from "../../../../../lib/i18n";

const API_BASE = (process.env.NEXT_PUBLIC_SIRALOOM_API_BASE ?? "http://localhost:8000/api/v1").replace(/\/$/, "");
const LARGE_DOWNLOAD_BYTES = 512 * 1024 * 1024;

type Specimen = { specimen_id: string; specimen_identifier: string; specimen_type?: string | null; status?: string };
type Analysis = { analysis_id: string; status: string; analysis_type?: string; workflow_id?: string; workflow_version?: string; reference_build?: string; analysis_version?: number; created_at?: string };
type CaseRecord = { case_id: string; case_identifier: string; status: string; language?: string; clinical_context?: Record<string, unknown>; created_at?: string; updated_at?: string; specimens?: Specimen[]; analyses?: Analysis[] };
type Artifact = { artifact_id: string; filename: string; artifact_type: string; size_bytes: number; sha256: string; genome_build?: string | null; specimen_id?: string | null; validation_status: string; created_at?: string; metadata?: Record<string, unknown> };
type Report = { report_id: string; analysis_id: string; version: number; status: string; language?: string; report_type?: string; artifact_id?: string | null; signed_artifact_id?: string | null; signed_sha256?: string | null; approved_at?: string | null; created_at?: string | null };

async function apiFetch(path: string, init?: RequestInit) {
  const token = await firebaseAuth?.currentUser?.getIdToken();
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...(init?.headers ?? {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  const text = await response.text();
  let body: any = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!response.ok) throw new Error(body?.detail ? String(body.detail) : `HTTP ${response.status}`);
  return body;
}

function pretty(value?: string | null) {
  return String(value ?? "—").toLowerCase().replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatBytes(value?: number | null) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "—";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let amount = value / 1024;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
  return `${amount.toFixed(amount >= 100 ? 0 : amount >= 10 ? 1 : 2)} ${units[unit]}`;
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

export default function CaseDossierPage() {
  const params = useParams<{ caseId: string }>();
  const caseId = String(params.caseId ?? "");
  const { t } = useLanguage();
  const [record, setRecord] = useState<CaseRecord | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [reports, setReports] = useState<Report[]>([]);
  const [reportError, setReportError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  const load = useCallback(async (quiet = false) => {
    if (!caseId) return;
    if (quiet) setRefreshing(true); else setLoading(true);
    setError("");
    try {
      const [caseData, fileRows] = await Promise.all([
        apiFetch(`/cases/${caseId}`),
        apiFetch(`/cases/${caseId}/artifacts`),
      ]);
      const analysisRows: Analysis[] = Array.isArray(caseData.analyses) ? caseData.analyses : [];
      const reportGroups = await Promise.all(analysisRows.map(async (analysis) => {
        try {
          const result = await apiFetch(`/analyses/${analysis.analysis_id}/reports`);
          return {
            items: (Array.isArray(result?.items) ? result.items : []).map((report: Omit<Report, "analysis_id">) => ({ ...report, analysis_id: analysis.analysis_id })),
            error: "",
          };
        } catch (e) {
          return { items: [], error: e instanceof Error ? e.message : "Report list could not be loaded." };
        }
      }));
      setRecord(caseData);
      setArtifacts(Array.isArray(fileRows) ? fileRows : []);
      setReports(reportGroups.flatMap(group => group.items));
      setReportError(reportGroups.find(group => group.error)?.error ?? "");
      window.localStorage.setItem("siraloom.case_id", caseData.case_id);
      window.localStorage.setItem("siraloom.case_identifier", caseData.case_identifier);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("cases.actionFailed"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [caseId, t]);

  useEffect(() => { void load(); }, [load]);

  const selectAnalysis = (analysis: Analysis) => {
    if (!record) return;
    window.localStorage.setItem("siraloom.case_id", record.case_id);
    window.localStorage.setItem("siraloom.case_identifier", record.case_identifier);
    window.localStorage.setItem("siraloom.analysis_id", analysis.analysis_id);
  };

  const downloadArtifact = async (artifact: Artifact) => {
    setDownloadingId(artifact.artifact_id);
    setMessage("");
    try {
      const token = await firebaseAuth?.currentUser?.getIdToken();
      const response = await fetch(`${API_BASE}/artifacts/${artifact.artifact_id}/download`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) {
        const body = await response.text();
        let detail = `HTTP ${response.status}`;
        try { const parsed = body ? JSON.parse(body) : null; if (parsed?.detail) detail = String(parsed.detail); } catch {}
        throw new Error(detail);
      }
      const picker = (window as any).showSaveFilePicker as undefined | ((options: any) => Promise<any>);
      if (response.body && picker) {
        const handle = await picker({ suggestedName: artifact.filename });
        const writable = await handle.createWritable();
        const reader = response.body.getReader();
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            await writable.write(value);
          }
          await writable.close();
        } catch (e) {
          await writable.abort?.();
          throw e;
        }
      } else {
        if (artifact.size_bytes > LARGE_DOWNLOAD_BYTES) {
          throw new Error("This file is larger than 512 MiB. Use a browser with save-to-disk streaming support to avoid buffering the entire file in memory.");
        }
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = artifact.filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
      setMessage(`${artifact.filename}: ${t("workspace.downloadArtifact")}`);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : t("workspace.downloadFailed"));
    } finally {
      setDownloadingId(null);
    }
  };

  if (loading) return <div className="case-dossier-page"><div className="empty"><strong>{t("session.checking")}</strong></div></div>;

  if (!record) return (
    <div className="case-dossier-page">
      <div className="page-heading"><div><p className="eyebrow">{t("cases.registry")}</p><h1>{t("cases.dossierTitle")}</h1></div><Link className="secondary link-button" href="/app/cases">{t("cases.back")}</Link></div>
      <div className="notice error-notice" role="alert">{error || t("cases.dossierNotFound")}</div>
    </div>
  );

  const analyses = record.analyses ?? [];
  const clinicalContext = record.clinical_context ?? {};

  return (
    <main className="case-dossier-page">
      <header className="page-heading case-dossier-heading">
        <div>
          <p className="eyebrow">{t("cases.registry")} / {record.case_identifier}</p>
          <h1>{record.case_identifier}</h1>
          <p className="lead">{t("cases.dossierTitle")} · {pretty(record.status)}</p>
        </div>
        <div className="case-dossier-actions">
          <Link className="secondary link-button" href="/app/cases">{t("cases.back")}</Link>
          <button className="secondary" type="button" onClick={() => void load(true)} disabled={refreshing}>{refreshing ? t("cases.refreshing") : t("cases.refresh")}</button>
        </div>
      </header>

      {error && <div className="notice error-notice" role="alert">{error}</div>}
      {message && <div className="notice" role="status">{message}</div>}

      <section className="case-dossier-summary">
        <div><span>{t("workspace.status")}</span><strong>{pretty(record.status)}</strong></div>
        <div><span>{t("cases.specimenCount")}</span><strong>{record.specimens?.length ?? 0}</strong></div>
        <div><span>{t("cases.analysis")}</span><strong>{analyses.length}</strong></div>
        <div><span>{t("workspace.files")}</span><strong>{artifacts.length}</strong></div>
        <div><span>{t("workspace.reportSection")}</span><strong>{reports.length}</strong></div>
      </section>

      <section className="panel case-dossier-panel">
        <div className="panel-head"><div><p className="eyebrow">{t("workspace.caseSection")}</p><h2>{t("workspace.caseSection")}</h2></div></div>
        <div className="case-dossier-detail-grid">
          <div><span>{t("cases.caseIdentifier")}</span><strong>{record.case_identifier}</strong></div>
          <div><span>{t("settings.caseId")}</span><code>{record.case_id}</code></div>
          <div><span>{t("workspace.createdAt")}</span><strong>{formatDate(record.created_at)}</strong></div>
          <div><span>{t("workspace.updatedAt")}</span><strong>{formatDate(record.updated_at)}</strong></div>
          <div className="wide"><span>{t("cases.clinicalIndication")}</span><strong>{String(clinicalContext.indication ?? "—")}</strong></div>
        </div>
        <div className="case-dossier-subsection">
          <h3>{t("workspace.specimenSection")}</h3>
          {!record.specimens?.length ? <p className="muted">{t("cases.dossierNoSpecimens")}</p> : <div className="case-dossier-list">
            {record.specimens.map(specimen => <article key={specimen.specimen_id}>
              <div><strong>{specimen.specimen_identifier}</strong><small>{pretty(specimen.specimen_type)} · {pretty(specimen.status)}</small></div>
              <code>{specimen.specimen_id}</code>
            </article>)}
          </div>}
        </div>
      </section>

      <section className="panel case-dossier-panel">
        <div className="panel-head"><div><p className="eyebrow">{t("workspace.files")}</p><h2>{t("workspace.files")}</h2><p className="muted">{t("workspace.filesLead")}</p></div><span className="badge neutral">{artifacts.length}</span></div>
        {!artifacts.length ? <div className="empty small"><strong>{t("cases.dossierNoFiles")}</strong></div> : <div className="case-dossier-list">
          {artifacts.map(artifact => <article key={artifact.artifact_id}>
            <div className="case-dossier-artifact-main">
              <strong>{artifact.filename}</strong>
              <small>{pretty(artifact.artifact_type)} · {formatBytes(artifact.size_bytes)} · {pretty(artifact.validation_status)}</small>
              <code>{artifact.sha256}</code>
              <small>{t("cases.build")}: {artifact.genome_build ?? "—"} · {formatDate(artifact.created_at)}</small>
            </div>
            <button className="secondary small" type="button" disabled={downloadingId === artifact.artifact_id} onClick={() => void downloadArtifact(artifact)}>{downloadingId === artifact.artifact_id ? t("workspace.downloading") : t("workspace.downloadArtifact")}</button>
          </article>)}
        </div>}
      </section>

      <section className="panel case-dossier-panel">
        <div className="panel-head"><div><p className="eyebrow">{t("workspace.executionSection")}</p><h2>{t("workspace.executionSection")}</h2></div><span className="badge neutral">{analyses.length}</span></div>
        {!analyses.length ? <div className="empty small"><strong>{t("cases.dossierNoAnalyses")}</strong><p>{t("cases.dossierStartFromWorkspace")}</p><Link className="primary link-button" href="/app/workspace">{t("cases.openWorkspace")}</Link></div> : <div className="case-dossier-list">
          {analyses.map(analysis => <article key={analysis.analysis_id}>
            <div>
              <strong>{pretty(analysis.analysis_type ?? "VARIANT_INTERPRETATION")} · v{analysis.analysis_version ?? 1}</strong>
              <small>{pretty(analysis.status)} · {analysis.reference_build ?? "—"} · {analysis.workflow_id ?? "—"} v{analysis.workflow_version ?? "—"}</small>
              <small>{t("workspace.createdAt")}: {formatDate(analysis.created_at)}</small>
              <code>{analysis.analysis_id}</code>
            </div>
            <div className="case-dossier-actions">
              <Link className="secondary link-button" href="/app/workspace" onClick={() => selectAnalysis(analysis)}>{t("cases.openWorkspace")}</Link>
              <Link className="secondary link-button" href="/app/reports" onClick={() => selectAnalysis(analysis)}>{t("nav.reports")}</Link>
            </div>
          </article>)}
        </div>}
      </section>

      <section className="panel case-dossier-panel">
        <div className="panel-head"><div><p className="eyebrow">{t("workspace.reportSection")}</p><h2>{t("workspace.reportSection")}</h2></div><span className="badge neutral">{reports.length}</span></div>
        {reportError && <div className="notice error-notice" role="status">{t("cases.dossierReportsUnavailable")}: {reportError}</div>}
        {!reports.length ? <div className="empty small"><strong>{t("cases.dossierNoReports")}</strong><p>{t("cases.dossierReportsLead")}</p></div> : <div className="case-dossier-list">
          {reports.map(report => {
            const reportArtifactId = report.signed_artifact_id ?? report.artifact_id;
            const reportArtifact = reportArtifactId ? artifacts.find(item => item.artifact_id === reportArtifactId) : undefined;
            return <article key={report.report_id}>
              <div>
                <strong>{pretty(report.report_type ?? "CLINICAL_INTERPRETATION")} · v{report.version}</strong>
                <small>{pretty(report.status)} · {report.language ?? "—"} · {formatDate(report.created_at)}</small>
                {report.signed_sha256 && <code>{t("cases.dossierSignedHash")}: {report.signed_sha256}</code>}
                <code>{report.report_id}</code>
              </div>
              <div className="case-dossier-actions">
                {reportArtifact && <button className="secondary small" type="button" disabled={downloadingId === reportArtifact.artifact_id} onClick={() => void downloadArtifact(reportArtifact)}>{downloadingId === reportArtifact.artifact_id ? t("workspace.downloading") : t("workspace.downloadPdf")}</button>}
                <Link className="secondary link-button" href="/app/reports" onClick={() => {
                  const analysis = analyses.find(item => item.analysis_id === report.analysis_id);
                  if (analysis) selectAnalysis(analysis);
                }}>{t("cases.dossierOpenReports")}</Link>
              </div>
            </article>;
          })}
        </div>}
      </section>

      <section className="case-dossier-footer">
        <p>{t("cases.dossierProvenanceNote")}</p>
        <Link className="secondary link-button" href="/app/audit" onClick={() => {
          window.localStorage.setItem("siraloom.case_id", record.case_id);
          window.localStorage.setItem("siraloom.case_identifier", record.case_identifier);
        }}>{t("nav.audit")}</Link>
      </section>
    </main>
  );
}
