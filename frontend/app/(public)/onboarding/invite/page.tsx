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
    if (!firebaseAuth) { setChecking(false); setMessage(t("invite.firebaseMissing")); return; }
    return onAuthStateChanged(firebaseAuth, async (currentUser) => {
      if (!currentUser) { setChecking(false); return; }
      try { await reload(currentUser); } catch {}
      setUser(currentUser); setChecking(false);
    });
  }, [t]);

  async function acceptInvitation() {
    const currentUser = firebaseAuth?.currentUser;
    if (!currentUser) { window.location.assign(`/login?redirect=${encodeURIComponent(window.location.pathname + window.location.search)}`); return; }
    if (!token) { setMessage(t("invite.tokenMissing")); return; }
    setBusy(true); setMessage("");
    try {
      await reload(currentUser);
      const refreshed = firebaseAuth?.currentUser;
      if (!refreshed) { window.location.assign("/login"); return; }
      if (!refreshed.emailVerified) { setMessage(t("invite.verifyRequired")); return; }
      const idToken = await refreshed.getIdToken(true);
      const response = await fetch(`${API_BASE}/auth/invitations/accept`, {
        method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${idToken}` }, body: JSON.stringify({ token }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail || `HTTP ${response.status}`);
      window.localStorage.removeItem("siraloom.case_id");
      window.localStorage.removeItem("siraloom.analysis_id");
      window.location.assign("/app/dashboard");
    } catch (error) { setMessage(error instanceof Error ? error.message : t("invite.acceptFailed")); }
    finally { setBusy(false); }
  }

  async function switchAccount() {
    const auth = firebaseAuth;
    if (!auth) return;
    setBusy(true);
    setMessage("");
    try {
      if (await attemptSignOut(() => signOut(auth))) window.location.reload();
      else setMessage(t("auth.signOutFailed"));
    } finally {
      setBusy(false);
    }
  }

  if (checking) return <main className="loading">{t("invite.checking")}</main>;
  if (!firebaseConfigured) return <main className="auth-page"><Brand /><section className="auth-card"><h1>{t("invite.unavailable")}</h1><p>{t("invite.firebaseMissing")}</p></section></main>;

  return (
    <main className="auth-page"><Brand /><section className="auth-card">
      <p className="eyebrow">{t("invite.eyebrow")}</p><h1>{t("invite.title")}</h1>
      <p>{t("invite.description")}</p>
      {user ? <div className="configuration-notice"><strong>{user.displayName || user.email}</strong><br />{user.email}</div> : <a className="button" href={`/login?redirect=${encodeURIComponent(window.location.pathname + window.location.search)}`}>{t("invite.signIn")}</a>}
      {user && !user.emailVerified && <button className="button" onClick={() => sendEmailVerification(user).then(() => setMessage(t("invite.verificationSent"))).catch(() => setMessage(t("invite.resendFailed")))}>{t("invite.resend")}</button>}
      {user && <button className="button" onClick={acceptInvitation} disabled={busy || !token || !user.emailVerified}>{busy ? t("invite.accepting") : t("invite.accept")}</button>}
      {message && <p className="form-message" role="status">{message}</p>}
      {user && <button type="button" className="text-button" onClick={() => void switchAccount()} disabled={busy}>{t("invite.switchAccount")}</button>}
    </section></main>
  );
}
