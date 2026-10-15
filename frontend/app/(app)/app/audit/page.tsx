"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { firebaseAuth } from "../../../../lib/firebase";
import { useLanguage } from "../../../../lib/i18n";
import { isWorkspaceCaseReady } from "../../../../lib/workspace-context.mjs";

const API_BASE = (process.env.NEXT_PUBLIC_SIRALOOM_API_BASE ?? "http://localhost:8000/api/v1").replace(/\/$/, "");

async function apiFetch(path: string) {
  const token = await firebaseAuth?.currentUser?.getIdToken();
  const response = await fetch(`${API_BASE}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  const text = await response.text();
  let body: any = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!response.ok) throw new Error(body?.detail ? String(body.detail) : `HTTP ${response.status}`);
  return body;
}

function pretty(value: string) { return String(value ?? "").toLowerCase().replaceAll("_", " ").replace(/\b\w/g, c => c.toUpperCase()); }

export default function AuditPage() {
  const { t } = useLanguage();
  const [cases, setCases] = useState<any[]>([]);
  const [selectedCase, setSelectedCase] = useState("");
  const [events, setEvents] = useState<any[]>([]);
  const [eventsCaseId, setEventsCaseId] = useState("");
  const [message, setMessage] = useState("");
  const casesRequest = useRef(0);
  const auditRequest = useRef(0);

  const loadCases = async () => {
    const request = ++auditRequest.current;
    try {
      const rows = await apiFetch("/cases");
      if (request !== casesRequest.current) return;
      setCases(Array.isArray(rows) ? rows : []);
      const stored = window.localStorage.getItem("siraloom.case_id") ?? "";
      const first = (Array.isArray(rows) ? rows : []).find((x: any) => x.case_id === stored) ?? rows?.[0];
      if (first) setSelectedCase(first.case_id);
      else setSelectedCase("");
    } catch (e) { if (request === casesRequest.current) setMessage(e instanceof Error ? e.message : "Unable to load cases."); }
  };

  useEffect(() => { loadCases(); }, []);
  useEffect(() => {
    const request = ++casesRequest.current;
    let cancelled = false;
    setEvents([]);
    setEventsCaseId("");
    if (!selectedCase) return () => { cancelled = true; };
    apiFetch(`/cases/${selectedCase}/audit`)
      .then((rows) => {
        if (cancelled || request !== auditRequest.current) return;
        setEvents(Array.isArray(rows) ? rows : []);
        setEventsCaseId(selectedCase);
      })
      .catch((e) => {
        if (!cancelled && request === auditRequest.current) setMessage(e instanceof Error ? e.message : "Unable to load audit history.");
      });
    return () => { cancelled = true; };
  }, [selectedCase]);

  const visibleEvents = selectedCase && isWorkspaceCaseReady(selectedCase, eventsCaseId) ? events : [];

  return <main className="audit-page">
    <header className="page-heading"><div><p className="eyebrow">{t("audit.eyebrow")}</p><h1>{t("audit.title")}</h1><p className="lead">{t("audit.lead")}</p></div><Link className="secondary link-button" href="/app/workspace">{t("audit.open")}</Link></header>
    {message && <div className="notice error-notice">{message}</div>}
    <section className="panel">
      <div className="panel-head"><div><p className="eyebrow">{t("audit.history")}</p><h2>{cases.length} cases</h2></div><button className="secondary" onClick={loadCases}>{t("audit.refresh")}</button></div>
      {!cases.length ? <div className="empty"><strong>{t("audit.none")}</strong><p>{t("audit.help")}</p><Link className="primary link-button" href="/app/cases">{t("audit.openCases")}</Link></div> :
      <div className="audit-case-grid">{cases.map(c => <button key={c.case_id} className={selectedCase === c.case_id ? "case-registry-item selected" : "case-registry-item"} onClick={() => { setSelectedCase(c.case_id); window.localStorage.setItem("siraloom.case_id", c.case_id); window.localStorage.setItem("siraloom.case_identifier", c.case_identifier); }}><span><strong>{c.case_identifier}</strong><small>{pretty(c.status)} · {c.analyses?.length ?? 0} analysis(es)</small></span><span><small>{c.updated_at ? new Date(c.updated_at).toLocaleString() : ""}</small></span></button>)}</div>}
    </section>
    <section className="panel"><div className="panel-head"><div><p className="eyebrow">{t("audit.timeline")}</p><h2>{visibleEvents.length} events</h2></div></div>
      {!visibleEvents.length ? <div className="empty"><strong>{t("audit.eventsNone")}</strong><p>{t("audit.selectHelp")}</p></div> :
      <div className="audit-timeline">{visibleEvents.slice().reverse().map((e: any) => <details className="audit-event" key={e.event_id}><summary><span>{e.occurred_at ? new Date(e.occurred_at).toLocaleString() : "—"}</span><strong>{pretty(e.event_type)}</strong><small>{e.actor_type ?? "SYSTEM"} · {e.actor_id ?? "siraloom"}{e.operation ? ` · ${e.operation}` : ""}</small></summary><pre className="audit-json">{JSON.stringify({ before_state:e.before_state, after_state:e.after_state, input_artifacts:e.input_artifacts, output_artifacts:e.output_artifacts, software:e.software, workflow:e.workflow, resource_versions:e.resource_versions, subject:{type:e.subject_type,id:e.subject_id}, reason:e.reason }, null, 2)}</pre></details>)}</div>}
    </section>
  </main>;
}
