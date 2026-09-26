"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { createUserWithEmailAndPassword, sendEmailVerification, sendPasswordResetEmail, signInWithEmailAndPassword, signInWithPopup } from "firebase/auth";
import { firebaseAuth, firebaseConfigured, googleProvider } from "../lib/firebase";
import { resolveSessionDestination } from "../lib/session";
import { useLanguage } from "../lib/i18n";
import { LanguageSwitcher } from "./language-switcher";

export function AuthForm({ mode, trial = true }: { mode: "login" | "signup"; trial?: boolean }) {
  const { t } = useLanguage();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const onboardingHref = trial ? "/onboarding?trial=1" : "/onboarding?trial=0";

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!firebaseAuth) return setMessage(t("auth.firebaseMissing"));
    setBusy(true); setMessage("");
    try {
      if (mode === "signup") {
        const credential = await createUserWithEmailAndPassword(firebaseAuth, email, password);
        await sendEmailVerification(credential.user);
        window.location.assign(onboardingHref);
      } else {
        const credential = await signInWithEmailAndPassword(firebaseAuth, email, password);
        if (!credential.user.emailVerified) { window.location.assign("/onboarding"); return; }
        const token = await credential.user.getIdToken();
        const destination = await resolveSessionDestination(token, "/onboarding");
        window.location.assign(destination);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t("auth.failed"));
    } finally { setBusy(false); }
  };

  const continueWithGoogle = async () => {
    if (!firebaseAuth) return setMessage(t("auth.firebaseMissing"));
    setBusy(true); setMessage("");
    try {
      const credential = await signInWithPopup(firebaseAuth, googleProvider);
      const token = await credential.user.getIdToken();
      const fallback = mode === "signup" ? "/onboarding" : "/app/dashboard";
      const destination = await resolveSessionDestination(token, fallback);
      window.location.assign(destination === "/onboarding" ? onboardingHref : destination);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t("auth.googleFailed"));
    } finally { setBusy(false); }
  };

  const reset = async () => {
    if (!firebaseAuth || !email) return setMessage(t("auth.enterEmail"));
    try { await sendPasswordResetEmail(firebaseAuth, email); setMessage(t("auth.resetSent")); }
    catch (error) { setMessage(error instanceof Error ? error.message : t("auth.resetFailed")); }
  };

  return (
    <form className="auth-card" onSubmit={submit}>
      <LanguageSwitcher className="auth-language-inline" />
      <p className="eyebrow">{t("auth.secure")}</p>
      <h1>{mode === "login" ? t("auth.login.title") : trial ? t("auth.signup.trialTitle") : t("auth.signup.orgTitle")}</h1>
      <p>{mode === "login" ? t("auth.login.body") : trial ? t("auth.signup.trialBody") : t("auth.signup.orgBody")}</p>
      <button type="button" className="button secondary" onClick={continueWithGoogle} disabled={busy || !firebaseConfigured}>{t("auth.google")}</button>
      <div className="divider" role="separator">{t("auth.or")}</div>
      <label>{t("auth.email")}<input type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} required /></label>
      <label>{t("auth.password")}<input type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={8} value={password} onChange={e => setPassword(e.target.value)} required /></label>
      {message && <p className="form-message" role="status">{message}</p>}
      <button className="button" disabled={busy || !firebaseConfigured}>{busy ? t("auth.working") : mode === "login" ? t("auth.signIn") : trial ? t("auth.startTrial") : t("auth.createAccount")}</button>
      {mode === "login" ? <><button type="button" className="text-button" onClick={reset}>{t("auth.resetPassword")}</button><p>{t("auth.newUser")} <Link href="/signup">{t("auth.startFreeTrial")}</Link></p></> : <p>{t("auth.haveAccount")} <Link href="/login">{t("auth.signIn")}</Link></p>}
    </form>
  );
}
