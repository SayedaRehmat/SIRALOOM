"use client";

import { useEffect, useState } from "react";
import { onAuthStateChanged, reload, sendEmailVerification, signOut, User } from "firebase/auth";
import { Brand } from "../../../../components/brand";
import { firebaseAuth, firebaseConfigured } from "../../../../lib/firebase";
import { useLanguage } from "../../../../lib/i18n";
import { attemptSignOut } from "../../../../lib/signout.mjs";

const API_BASE = (process.env.NEXT_PUBLIC_SIRALOOM_API_BASE ?? "http://localhost:8000/api/v1").replace(/\/$/, "");

export default function InvitationAcceptancePage() {
  const { t } = useLanguage();
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [token, setToken] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setToken(params.get("token") ?? "");
    if (!firebaseAuth) { setChecking(false); setMessage("Firebase authentication is not configured."); return; }
    return onAuthStateChanged(firebaseAuth, async (currentUser) => {
      if (!currentUser) { setChecking(false); return; }
      try { await reload(currentUser); } catch {}
      setUser(currentUser); setChecking(false);
    });
  }, []);

  async function acceptInvitation() {
    const currentUser = firebaseAuth?.currentUser;
    if (!currentUser) { window.location.assign(`/login?redirect=${encodeURIComponent(window.location.pathname + window.location.search)}`); return; }
    if (!token) { setMessage("This invitation link is missing its token."); return; }
    setBusy(true); setMessage("");
    try {
      await reload(currentUser);
      const refreshed = firebaseAuth?.currentUser;
      if (!refreshed) { window.location.assign("/login"); return; }
      if (!refreshed.emailVerified) { setMessage("Verify your Firebase email before accepting the invitation."); return; }
      const idToken = await refreshed.getIdToken(true);
      const response = await fetch(`${API_BASE}/auth/invitations/accept`, {
        method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${idToken}` }, body: JSON.stringify({ token }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail || `HTTP ${response.status}`);
      window.localStorage.removeItem("siraloom.case_id");
      window.localStorage.removeItem("siraloom.analysis_id");
      window.location.assign("/app/dashboard");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Unable to accept invitation."); }
    finally { setBusy(false); }
  }

  async function switchAccount() {
    if (!firebaseAuth) return;
    setBusy(true);
    setMessage("");
    try {
      if (await attemptSignOut(() => signOut(firebaseAuth))) window.location.reload();
      else setMessage(t("auth.signOutFailed"));
    } finally {
      setBusy(false);
    }
  }

  if (checking) return <main className="loading">Checking invitation…</main>;
  if (!firebaseConfigured) return <main className="auth-page"><Brand /><section className="auth-card"><h1>Invitation unavailable</h1><p>Firebase authentication is not configured for this deployment.</p></section></main>;

  return (
    <main className="auth-page"><Brand /><section className="auth-card">
      <p className="eyebrow">SIRALOOM organization access</p><h1>Accept laboratory invitation</h1>
      <p>This invitation can only be accepted by the verified Firebase account whose email address was invited.</p>
      {user ? <div className="configuration-notice"><strong>{user.displayName || user.email}</strong><br />{user.email}</div> : <a className="button" href={`/login?redirect=${encodeURIComponent(window.location.pathname + window.location.search)}`}>Sign in to continue</a>}
      {user && !user.emailVerified && <button className="button" onClick={() => sendEmailVerification(user).then(() => setMessage("Verification email sent. Verify your address, then return to this invitation." )).catch(error => setMessage(error instanceof Error ? error.message : "Unable to send verification email."))}>Resend verification email</button>}
      {user && <button className="button" onClick={acceptInvitation} disabled={busy || !token || !user.emailVerified}>{busy ? "Accepting…" : "Accept invitation"}</button>}
      {message && <p className="form-message" role="status">{message}</p>}
      {user && <button type="button" className="text-button" onClick={() => void switchAccount()} disabled={busy}>Use a different account</button>}
    </section></main>
  );
}
