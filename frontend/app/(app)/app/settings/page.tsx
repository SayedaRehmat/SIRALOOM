"use client";

import { useEffect, useState } from "react";
import { firebaseAuth } from "../../../../lib/firebase";
import { useLanguage } from "../../../../lib/i18n";

const API_BASE = (process.env.NEXT_PUBLIC_SIRALOOM_API_BASE ?? "http://localhost:8000/api/v1").replace(/\/$/, "");
const INVITATION_ROLES = [
  "lab_director",
  "clinical_geneticist",
  "reviewer",
  "bioinformatician",
  "lab_scientist",
  "read_only",
] as const;

async function apiFetch(path: string, init: RequestInit = {}) {
  const token = await firebaseAuth?.currentUser?.getIdToken();
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      "Content-Type": "application/json",
    },
  });
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
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<(typeof INVITATION_ROLES)[number]>("lab_scientist");
  const [inviteDays, setInviteDays] = useState(7);
  const [invitationLink, setInvitationLink] = useState("");
  const [inviting, setInviting] = useState(false);

  useEffect(() => {
    Promise.all([apiFetch("/auth/session"), apiFetch("/health")])
      .then(([s, h]) => { setSession(s); setHealth(h); })
      .catch((e) => setMessage(e instanceof Error ? e.message : t("settings.unableToLoad")));
  }, [t]);

  const canManageMembers = session?.role === "organization_admin" || session?.role === "lab_director";

  async function inviteMember() {
    setMessage("");
    setInvitationLink("");
    if (!inviteEmail.trim()) { setMessage("Enter the staff member's email address."); return; }
    setInviting(true);
    try {
      const result = await apiFetch("/auth/invitations", {
        method: "POST",
        body: JSON.stringify({ email: inviteEmail.trim(), role: inviteRole, expires_in_days: inviteDays }),
      });
      const link = `${window.location.origin}/onboarding/invite?token=${encodeURIComponent(result.invitation_token)}`;
      setInvitationLink(link);
      setMessage("Invitation created. Share the secure invitation link with the intended recipient.");
      setInviteEmail("");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Unable to create invitation.");
    } finally {
      setInviting(false);
    }
  }

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

        {canManageMembers && <section className="panel">
          <p className="eyebrow">Organization access</p>
          <h2>Invite laboratory staff</h2>
          <p className="muted">Invitations are tenant-scoped and the recipient must authenticate with the exact invited Firebase email.</p>
          <div className="form-stack">
            <label>Email<input value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} type="email" placeholder="staff@laboratory.org" /></label>
            <label>Role<select value={inviteRole} onChange={(e) => setInviteRole(e.target.value as (typeof INVITATION_ROLES)[number])}>{INVITATION_ROLES.map((role) => <option key={role} value={role}>{role}</option>)}</select></label>
            <label>Expires in<select value={inviteDays} onChange={(e) => setInviteDays(Number(e.target.value))}><option value={1}>1 day</option><option value={7}>7 days</option><option value={14}>14 days</option><option value={30}>30 days</option></select></label>
            <button type="button" onClick={inviteMember} disabled={inviting}>{inviting ? "Creating…" : "Create invitation"}</button>
          </div>
          {invitationLink && <div className="notice">
            <strong>Invitation link — show/share this once:</strong>
            <code style={{ display: "block", marginTop: 8, overflowWrap: "anywhere" }}>{invitationLink}</code>
            <p className="muted">The token is not stored in plaintext by SIRALOOM. Treat this link as a bearer credential until it is accepted or expires.</p>
          </div>}
        </section>}

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
