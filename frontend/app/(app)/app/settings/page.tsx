"use client";

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

export default function SettingsPage() {
  const [session, setSession] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    Promise.all([apiFetch("/auth/session"), apiFetch("/health")])
      .then(([s, h]) => { setSession(s); setHealth(h); })
      .catch((e) => setMessage(e instanceof Error ? e.message : "Unable to load settings."));
  }, []);

  return <main className="settings-page">
    <header className="page-heading">
      <div><p className="eyebrow">GOVERNANCE · CONFIGURATION</p><h1>Settings</h1><p className="lead">Authenticated workspace identity, entitlement, service connection, and active workflow context.</p></div>
    </header>
    {message && <div className="notice error-notice">{message}</div>}
    <div className="feature-grid">
      <section className="panel"><p className="eyebrow">IDENTITY</p><h2>Current session</h2>
        {session ? <div className="context-list">
          <div className="keyline"><span>Email</span><strong>{session.email ?? "—"}</strong></div>
          <div className="keyline"><span>Role</span><strong>{session.role ?? "—"}</strong></div>
          <div className="keyline"><span>User ID</span><code>{session.user_id}</code></div>
          <div className="keyline"><span>Organization</span><code>{session.organization_id}</code></div>
          <div className="keyline"><span>Entitlement</span><strong>{session.entitlement?.plan ?? "—"} · {session.entitlement?.status ?? "—"}</strong></div>
        </div> : <p className="muted">Loading authenticated session…</p>}
      </section>
      <section className="panel"><p className="eyebrow">SERVICE</p><h2>Backend connection</h2>
        <div className="keyline"><span>API</span><code>{API_BASE}</code></div>
        <div className="keyline"><span>Health</span><strong>{health?.status ?? "Checking…"}</strong></div>
        <p className="muted">Scientific resources and workflow configuration remain server-controlled. This page does not expose unsafe client-side overrides.</p>
      </section>
      <section className="panel"><p className="eyebrow">ACTIVE CONTEXT</p><h2>Browser workflow context</h2>
        <div className="keyline"><span>Case ID</span><code>{typeof window !== "undefined" ? window.localStorage.getItem("siraloom.case_id") ?? "—" : "—"}</code></div>
        <div className="keyline"><span>Analysis ID</span><code>{typeof window !== "undefined" ? window.localStorage.getItem("siraloom.analysis_id") ?? "—" : "—"}</code></div>
        <p className="muted">Selecting a case from the Cases registry updates this context automatically.</p>
      </section>
    </div>
  </main>;
}
