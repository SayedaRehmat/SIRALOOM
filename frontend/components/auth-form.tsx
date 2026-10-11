"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { createUserWithEmailAndPassword, sendEmailVerification, sendPasswordResetEmail, signInWithEmailAndPassword, signInWithPopup } from "firebase/auth";
import { firebaseAuth, firebaseConfigured, googleProvider } from "../lib/firebase";
import { resolveSessionDestination } from "../lib/session";
import { useLanguage } from "../lib/i18n";

export function AuthForm({ mode, trial = true }: { mode: "login" | "signup"; trial?: boolean }) {
  const { language } = useLanguage();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const onboardingHref = trial ? "/onboarding?trial=1" : "/onboarding?trial=0";
  const copy = (en: string, ar: string) => language === "ar" ? ar : language === "bilingual" ? `${en} · ${ar}` : en;
  const text = mode === "login" ? {
    eyebrow: copy("SECURE WORKSPACE ACCESS", "دخول آمن إلى مساحة العمل"),
    title: copy("Sign in to your laboratory workspace", "سجّل الدخول إلى مساحة عمل مختبرك"),
    body: copy("Use your laboratory-approved account to continue a case, review interpretation, or access reports.", "استخدم حساب المختبر المعتمد لمتابعة حالة أو مراجعة التفسير أو الوصول إلى التقارير."),
    submit: copy("Sign in", "تسجيل الدخول"),
    secondary: copy("New to SIRALOOM?", "جديد على SIRALOOM؟"),
    reset: copy("Reset password", "إعادة تعيين كلمة المرور")
  } : {
    eyebrow: copy("LABORATORY ACCESS", "وصول المختبر"),
    title: trial ? copy("Create a SIRALOOM workspace", "أنشئ مساحة عمل SIRALOOM") : copy("Create laboratory access", "أنشئ وصول المختبر"),
    body: trial ? copy("Create an account to evaluate the workflow before laboratory deployment.", "أنشئ حساباً لتقييم سير العمل قبل نشره في المختبر.") : copy("Create your account and continue to laboratory onboarding.", "أنشئ حسابك وتابع إعداد المختبر."),
    submit: trial ? copy("Create account", "إنشاء الحساب") : copy("Continue", "متابعة"),
    secondary: copy("Already have an account?", "لديك حساب بالفعل؟"),
    reset: ""
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!firebaseAuth) return setMessage(copy("Authentication is not configured.", "المصادقة غير مهيأة."));
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
      setMessage(error instanceof Error ? error.message : copy("Unable to complete authentication.", "تعذر إكمال المصادقة."));
    } finally { setBusy(false); }
  };

  const continueWithGoogle = async () => {
    if (!firebaseAuth) return setMessage(copy("Authentication is not configured.", "المصادقة غير مهيأة."));
    setBusy(true); setMessage("");
    try {
      const credential = await signInWithPopup(firebaseAuth, googleProvider);
      const token = await credential.user.getIdToken();
      const fallback = mode === "signup" ? "/onboarding" : "/app/dashboard";
      const destination = await resolveSessionDestination(token, fallback);
      window.location.assign(destination === "/onboarding" ? onboardingHref : destination);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : copy("Unable to continue with Google.", "تعذر المتابعة باستخدام Google."));
    } finally { setBusy(false); }
  };

  const reset = async () => {
    if (!firebaseAuth || !email) return setMessage(copy("Enter your email address first.", "أدخل بريدك الإلكتروني أولاً."));
    try { await sendPasswordResetEmail(firebaseAuth, email); setMessage(copy("Password reset instructions sent.", "تم إرسال تعليمات إعادة تعيين كلمة المرور.")); }
    catch (error) { setMessage(error instanceof Error ? error.message : copy("Unable to send reset instructions.", "تعذر إرسال تعليمات إعادة التعيين.")); }
  };

  return (
    <form className="auth-card" onSubmit={submit}>
      <p className="eyebrow">{text.eyebrow}</p>
      <h1>{text.title}</h1>
      <p>{text.body}</p>
      <button type="button" className="button secondary" onClick={continueWithGoogle} disabled={busy || !firebaseConfigured}>{copy("Continue with Google", "المتابعة باستخدام Google")}</button>
      <div className="divider" role="separator">{copy("or", "أو")}</div>
      <label>{copy("Email", "البريد الإلكتروني")}<input type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} required /></label>
      <label>{copy("Password", "كلمة المرور")}<input type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={8} value={password} onChange={e => setPassword(e.target.value)} required /></label>
      {message && <p className="form-message" role="status">{message}</p>}
      <button className="button" disabled={busy || !firebaseConfigured}>{busy ? copy("Working…", "جارٍ التنفيذ…") : text.submit}</button>
      {mode === "login" ? <><button type="button" className="text-button" onClick={reset}>{text.reset}</button><p>{text.secondary} <Link href="/signup">{copy("Request access", "طلب الوصول")}</Link></p></> : <p>{text.secondary} <Link href="/login">{copy("Sign in", "تسجيل الدخول")}</Link></p>}
    </form>
  );
}
