"use client";

import { useEffect, useState } from "react";
import { onAuthStateChanged, reload, signOut, User } from "firebase/auth";
import { firebaseAuth, firebaseConfigured } from "../../lib/firebase";
import { apiBase } from "../../lib/session";

export default function OnboardingPage() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [verified, setVerified] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!firebaseAuth) {
      setChecking(false);
      setMessage("Firebase is not configured for this deployment.");
      return;
    }

    return onAuthStateChanged(firebaseAuth, async (currentUser) => {
      if (!currentUser) {
        window.location.assign("/login");
        return;
      }

      setUser(currentUser);
      try {
        await reload(currentUser);
      } catch {
        // Firebase will surface an authentication error on the next protected request.
      }
      setVerified(Boolean(currentUser.emailVerified));
      setChecking(false);
    });
  }, []);

  const startTrial = async () => {
    if (!firebaseAuth?.currentUser) {
      window.location.assign("/login");
      return;
    }

    setBusy(true);
    setMessage("");

    try {
      await reload(firebaseAuth.currentUser);
      const currentUser = firebaseAuth.currentUser;

      if (!currentUser.emailVerified) {
        setVerified(false);
        setMessage("Please verify your email first, then click “I’ve verified my email”.");
        return;
      }

      const token = await currentUser.getIdToken(true);
      const response = await fetch(`${apiBase}/auth/onboarding/trial`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          display_name: currentUser.displayName || null,
          laboratory_name: null,
        }),
      });

      if (response.ok || response.status === 409) {
        window.location.assign("/app/dashboard");
        return;
      }

      const body = await response.json().catch(() => null);
      setMessage(body?.detail || "SIRALOOM could not create your trial workspace.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to start the SIRALOOM trial.");
    } finally {
      setBusy(false);
    }
  };

  const refreshVerification = async () => {
    if (!firebaseAuth?.currentUser) return;
    setBusy(true);
    setMessage("");
    try {
      await reload(firebaseAuth.currentUser);
      const isVerified = Boolean(firebaseAuth.currentUser.emailVerified);
      setVerified(isVerified);
      if (isVerified) {
        await startTrial();
      } else {
        setMessage("Your email is not verified yet. Open the Firebase verification email and try again.");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to refresh verification status.");
    } finally {
      setBusy(false);
    }
  };

  if (checking) {
    return <main className="loading">Preparing your SIRALOOM workspace…</main>;
  }

  if (!firebaseConfigured || !user) {
    return (
      <main className="auth-page">
        <section className="auth-card">
          <p className="eyebrow">SIRALOOM</p>
          <h1>Secure access required</h1>
          <p>{message || "Please sign in before starting a SIRALOOM trial."}</p>
          <a className="button" href="/login">Return to sign in</a>
        </section>
      </main>
    );
  }

  return (
    <main className="auth-page">
      <section className="auth-card">
        <p className="eyebrow">SIRALOOM FREE TRIAL</p>
        <h1>Your workspace is ready to be created</h1>
        <p>
          SIRALOOM will automatically create your private trial workspace.
          You do not need to create an organization or enter payment details.
        </p>

        <div className="configuration-notice">
          <strong>{user.displayName || user.email}</strong>
          <br />
          {user.email}
        </div>

        {!verified ? (
          <>
            <p>
              We need your verified email before creating the workspace.
              Check your inbox for the Firebase verification email.
            </p>
            <button className="button" onClick={refreshVerification} disabled={busy}>
              {busy ? "Checking…" : "I’ve verified my email"}
            </button>
          </>
        ) : (
          <button className="button" onClick={startTrial} disabled={busy}>
            {busy ? "Creating workspace…" : "Start Free Trial"}
          </button>
        )}

        {message && <p className="form-message" role="status">{message}</p>}

        <button
          type="button"
          className="text-button"
          onClick={() => firebaseAuth && signOut(firebaseAuth).then(() => window.location.assign("/login"))}
          disabled={busy}
        >
          Sign out
        </button>
      </section>
    </main>
  );
}
