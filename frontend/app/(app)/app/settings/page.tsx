"use client";

import { useEffect, useState } from "react";
import { firebaseAuth } from "../../../../lib/firebase";
import { useLanguage } from "../../../../lib/i18n";

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
  const { t } = useLanguage();
  const [session, setSession] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    Promise.all([apiFetch("/auth/session"), apiFetch("/health")])
      .then(([s, h]) => { setSession(s); setHealth(h); })
      .catch((e) => setMessage(e instanceof Error ? e.message : t("settings.unableToLoad")));
  }, [t]);

  return (
    <main className="settings-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">{t("settings.eyebrow")}</p>
          <h1>{t("settings.title")}</h1>
          <p className="lead">{t("settings.lead")}</p>
        </div>
      </header>
      {message && <div className="notice error-notice">{message}</div>}
      <div className="feature-grid">
        <section className="panel">
          <p className="eyebrow">{t("settings.identity")}</p>
          <h2>{t("settings.currentSession")}</h2>
          {session ? <div className="context-list">
            <div className="keyline"><span>{t("settings.email")}</span><strong>{session.email ?? "—"}</strong></div>
            <div className="keyline"><span>{t("settings.role")}</span><strong>{session.role ?? "—"}</strong></div>
            <div className="keyline"><span>{t("settings.userId")}</span><code>{session.user_id}</code></div>
            <div className="keyline"><span>{t("settings.organization")}</span><code>{session.organization_id}</code></div>
            <div className="keyline"><span>{t("settings.entitlement")}</span><strong>{session.entitlement?.plan ?? "—"} · {session.entitlement?.status ?? "—"}</strong></div>
          </div> : <p className="muted">{t("settings.loadingSession")}</p>}
        </section>
        <section className="panel">
          <p className="eyebrow">{t("settings.service")}</p>
          <h2>{t("settings.backendConnection")}</h2>
          <div className="keyline"><span>{t("settings.api")}</span><code>{API_BASE}</code></div>
          <div className="keyline"><span>{t("settings.health")}</span><strong>{health?.status ?? "Checking…"}</strong></div>
          <p className="muted">{t("settings.serverControlled")}</p>
        </section>
        <section className="panel">
          <p className="eyebrow">{t("settings.activeContext")}</p>
          <h2>{t("settings.browserContext")}</h2>
          <div className="keyline"><span>{t("settings.caseId")}</span><code>{typeof window !== "undefined" ? window.localStorage.getItem("siraloom.case_id") ?? "—" : "—"}</code></div>
          <div className="keyline"><span>{t("settings.analysisId")}</span><code>{typeof window !== "undefined" ? window.localStorage.getItem("siraloom.analysis_id") ?? "—" : "—"}</code></div>
          <p className="muted">{t("settings.contextNote")}</p>
        </section>
      </div>
    </main>
  );
}
