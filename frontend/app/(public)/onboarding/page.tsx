"use client";

import { useEffect, useState } from "react";
import { onAuthStateChanged, reload, sendEmailVerification, signOut, User } from "firebase/auth";
import { Brand } from "../../../components/brand";
import { LanguageSwitcher } from "../../../components/language-switcher";
import { firebaseAuth, firebaseConfigured } from "../../../lib/firebase";
import { apiBase } from "../../../lib/session";
import { useLanguage } from "../../../lib/i18n";

export default function Onboarding() {
  const { t } = useLanguage();
  const [isTrial, setIsTrial] = useState(true);
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [verified, setVerified] = useState(false);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setIsTrial(params.get("trial") !== "0" && params.get("mode") !== "organization");
    if (!firebaseAuth) { setChecking(false); setMessage(t("onboarding.firebaseMissing")); return; }
    return onAuthStateChanged(firebaseAuth, async (currentUser) => {
      if (!currentUser) { window.location.assign("/login"); return; }
      setUser(currentUser);
      try { await reload(currentUser); } catch {}
      setVerified(Boolean(currentUser.emailVerified)); setChecking(false);
    });
  }, [t]);

  const startWorkspace = async () => {
    const currentUser = firebaseAuth?.currentUser;
    if (!currentUser) { window.location.assign("/login"); return; }
    setBusy(true); setMessage("");
    try {
      await reload(currentUser);
      const refreshedUser = firebaseAuth?.currentUser;
      if (!refreshedUser) { window.location.assign("/login"); return; }
      if (!refreshedUser.emailVerified) { setVerified(false); setMessage(t("onboarding.notVerified")); return; }
      const token = await refreshedUser.getIdToken(true);
      const endpoint = isTrial ? "/auth/onboarding/trial" : "/auth/onboarding/organization";
      const body = isTrial ? JSON.stringify({ laboratory_name: name || undefined }) : JSON.stringify({ organization_name: name });
      const response = await fetch(apiBase + endpoint, { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token }, body });
      if (response.ok || response.status === 409) { window.location.assign("/app/dashboard"); return; }
      const responseBody = await response.json().catch(() => null);
      setMessage(responseBody?.detail || t("onboarding.createFailed"));
    } catch (error) { setMessage(error instanceof Error ? error.message : t("onboarding.createFailed")); }
    finally { setBusy(false); }
  };

  const refreshVerification = async () => {
    const currentUser = firebaseAuth?.currentUser;
    if (!currentUser) { window.location.assign("/login"); return; }
    setBusy(true); setMessage("");
    try {
      await reload(currentUser);
      const refreshedUser = firebaseAuth?.currentUser;
      const isVerified = Boolean(refreshedUser?.emailVerified);
      setVerified(isVerified);
      if (isVerified) await startWorkspace();
      else setMessage(t("onboarding.notVerified"));
    } catch (error) { setMessage(error instanceof Error ? error.message : t("onboarding.createFailed")); }
    finally { setBusy(false); }
  };

  if (checking) return <main className="loading"><LanguageSwitcher />{t("onboarding.checking")}</main>;

  if (!firebaseConfigured || !user) return (
    <main className="auth-page">
      <LanguageSwitcher />
      <Brand />
      <section className="auth-card">
        <p className="eyebrow">{t("onboarding.secure")}</p>
        <h1>{t("onboarding.accessRequired")}</h1>
        <p>{message || t("onboarding.signInFirst")}</p>
        <a className="button" href="/login">{t("onboarding.returnSignIn")}</a>
      </section>
    </main>
  );

  return (
    <main className="auth-page">
      <LanguageSwitcher />
      <Brand />
      <section className="auth-card">
        <p className="eyebrow">{isTrial ? t("onboarding.trialEyebrow") : t("onboarding.orgEyebrow")}</p>
        <h1>{isTrial ? t("onboarding.trialTitle") : t("onboarding.orgTitle")}</h1>
        <p>{isTrial ? t("onboarding.trialBody") : t("onboarding.orgBody")}</p>
        <div className="configuration-notice"><strong>{user.displayName || user.email}</strong><br />{user.email}</div>
        {isTrial && <label>{t("onboarding.labName")} ({t("onboarding.optional")})<input value={name} onChange={e => setName(e.target.value)} disabled={busy} /></label>}
        {!verified ? <><p>{t("onboarding.verifyBody")}</p><button className="button" onClick={refreshVerification} disabled={busy}>{busy ? t("onboarding.checking") : t("onboarding.verified")}</button><button type="button" className="text-button" onClick={() => firebaseAuth?.currentUser && sendEmailVerification(firebaseAuth.currentUser).then(() => setMessage(t("onboarding.verifySent"))).catch(error => setMessage(error instanceof Error ? error.message : t("onboarding.createFailed")))} disabled={busy}>{t("onboarding.resend")}</button></> : <button className="button" onClick={startWorkspace} disabled={busy}>{busy ? t("onboarding.creating") : isTrial ? t("onboarding.create") : t("onboarding.createOrg")}</button>}
        {message && <p className="form-message" role="status">{message}</p>}
        <button type="button" className="text-button" onClick={() => firebaseAuth && signOut(firebaseAuth).then(() => window.location.assign("/login"))} disabled={busy}>{t("onboarding.signOut")}</button>
      </section>
    </main>
  );
}
