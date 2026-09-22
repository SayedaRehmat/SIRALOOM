"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { firebaseAuth } from "../../../../lib/firebase";

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
  const [cases, setCases] = useState<any[]>([]);
  const [selectedCase, setSelectedCase] = useState("");
  const [events, setEvents] = useState<any[]>([]);
  const [message, setMessage] = useState("");

  const loadCases = async () => {
    try {
      const rows = await apiFetch("/cases");
      setCases(Array.isArray(rows) ? rows : []);
      const stored = window.localStorage.getItem("siraloom.case_id") ?? "";
      const first = (Array.isArray(rows) ? rows : []).find((x: any) => x.case_id === stored) ?? rows?.[0];
      if (first) setSelectedCase(first.case_id);
    } catch (e) { setMessage(e instanceof Error ? e.message : "Unable to load cases."); }
  };

  const loadAudit = async (id: string) => {
    if (!id) return;
    try { setEvents(await apiFetch(`/cases/${id}/audit`)); }
    catch (e) { setMessage(e instanceof Error ? e.message : "Unable to load audit history."); }
  };

  useEffect(() => { loadCases(); }, []);
  useEffect(() => { if (selectedCase) loadAudit(selectedCase); }, [selectedCase]);

  return <main className="audit-page">
    <header className="page-heading"><div><p className="eyebrow">GOVERNANCE · AUDIT</p><h1>Audit & provenance</h1><p className="lead">Tenant-scoped case history with persisted workflow, evidence, reviewer, report, and provenance events.</p></div><Link className="secondary link-button" href="/app/workspace">Open workspace</Link></header>
    {message && <div className="notice error-notice">{message}</div>}
    <section className="panel">
      <div className="panel-head"><div><p className="eyebrow">CASE HISTORY</p><h2>{cases.length} cases</h2></div><button className="secondary" onClick={loadCases}>Refresh</button></div>
      {!cases.length ? <div className="empty"><strong>No cases</strong><p>Create or load a case from the Cases page.</p><Link className="primary link-button" href="/app/cases">Open cases</Link></div> :
      <div className="audit-case-grid">{cases.map(c => <button key={c.case_id} className={selectedCase === c.case_id ? "case-registry-item selected" : "case-registry-item"} onClick={() => { setSelectedCase(c.case_id); window.localStorage.setItem("siraloom.case_id", c.case_id); window.localStorage.setItem("siraloom.case_identifier", c.case_identifier); }}><span><strong>{c.case_identifier}</strong><small>{pretty(c.status)} · {c.analyses?.length ?? 0} analysis(es)</small></span><span><small>{c.updated_at ? new Date(c.updated_at).toLocaleString() : ""}</small></span></button>)}</div>}
    </section>
    <section className="panel"><div className="panel-head"><div><p className="eyebrow">TIMELINE</p><h2>{events.length} events</h2></div></div>
      {!events.length ? <div className="empty"><strong>No audit events</strong><p>Select a case with persisted activity.</p></div> :
      <div className="audit-timeline">{events.slice().reverse().map((e: any) => <details className="audit-event" key={e.event_id}><summary><span>{e.occurred_at ? new Date(e.occurred_at).toLocaleString() : "—"}</span><strong>{pretty(e.event_type)}</strong><small>{e.actor_type ?? "SYSTEM"} · {e.actor_id ?? "siraloom"}{e.operation ? ` · ${e.operation}` : ""}</small></summary><pre className="audit-json">{JSON.stringify({ before_state:e.before_state, after_state:e.after_state, input_artifacts:e.input_artifacts, output_artifacts:e.output_artifacts, software:e.software, workflow:e.workflow, resource_versions:e.resource_versions, subject:{type:e.subject_type,id:e.subject_id}, reason:e.reason }, null, 2)}</pre></details>)}</div>}
    </section>
  </main>;
}
