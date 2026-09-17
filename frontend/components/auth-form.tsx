"use client";
import Link from "next/link";
import { FormEvent, useState } from "react";
import {
  createUserWithEmailAndPassword,
  sendEmailVerification,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
} from "firebase/auth";
import { firebaseAuth, firebaseConfigured, googleProvider } from "../lib/firebase";
import { resolveSessionDestination } from "../lib/session";

export function AuthForm({ mode, trial = true }: { mode: "login" | "signup"; trial?: boolean }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const onboardingHref = trial ? "/onboarding?trial=1" : "/onboarding?trial=0";

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!firebaseAuth) return setMessage("Firebase is not configured for this deployment.");
    setBusy(true);
    setMessage("");
    try {
      if (mode === "signup") {
        const credential = await createUserWithEmailAndPassword(firebaseAuth, email, password);
        await sendEmailVerification(credential.user);
        // A brand-new identity always needs onboarding; email verification happens there.
        window.location.assign(onboardingHref);
      } else {
        const credential = await signInWithEmailAndPassword(firebaseAuth, email, password);
        if (!credential.user.emailVerified) {
          window.location.assign("/onboarding");
          return;
        }
        const token = await credential.user.getIdToken();
        const destination = await resolveSessionDestination(token, "/onboarding");
        window.location.assign(destination);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Authentication could not be completed.");
    } finally {
      setBusy(false);
    }
  };

  const continueWithGoogle = async () => {
    if (!firebaseAuth) return setMessage("Firebase is not configured for this deployment.");
    setBusy(true);
    setMessage("");
    try {
      const credential = await signInWithPopup(firebaseAuth, googleProvider);
      const token = await credential.user.getIdToken();
      const fallback = mode === "signup" ? "/onboarding" : "/app/dashboard";
      const destination = await resolveSessionDestination(token, fallback);
      window.location.assign(destination === "/onboarding" ? onboardingHref : destination);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Google sign-in could not be completed.");
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (!firebaseAuth || !email) return setMessage("Enter your email address first.");
    try {
      await sendPasswordResetEmail(firebaseAuth, email);
      setMessage("Password-reset email sent.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to send reset email.");
    }
  };

  return (
    <form className="auth-card" onSubmit={submit}>
      <p className="eyebrow">SECURE ACCESS</p>
      <h1>{mode === "login" ? "Sign in to your workspace" : trial ? "Start your SIRALOOM trial" : "Create your SIRALOOM account"}</h1>
      <p>
        {mode === "login"
          ? "Use your laboratory-approved account."
          : trial
            ? "No payment method required. Your workspace is created automatically once you verify your identity."
            : "Your organization workspace is created automatically once you verify your identity."}
      </p>

      <button type="button" className="button secondary" onClick={continueWithGoogle} disabled={busy || !firebaseConfigured}>
        Continue with Google
      </button>
      <div className="divider" role="separator">or</div>

      <label>
        Email
        <input type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} required />
      </label>
      <label>
        Password
        <input
          type="password"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          minLength={8}
          value={password}
          onChange={e => setPassword(e.target.value)}
          required
        />
      </label>
      {message && <p className="form-message" role="status">{message}</p>}
      <button className="button" disabled={busy || !firebaseConfigured}>
        {busy ? "Working…" : mode === "login" ? "Sign in" : trial ? "Start Free Trial" : "Create account"}
      </button>
      {mode === "login" ? (
        <>
          <button type="button" className="text-button" onClick={reset}>Reset password</button>
          <p>New to SIRALOOM? <Link href="/signup">Start a free trial</Link></p>
        </>
      ) : (
        <p>Already have an account? <Link href="/login">Sign in</Link></p>
      )}
    </form>
  );
}
