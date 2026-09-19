"use client";

import { useEffect, useState } from "react";
import { onAuthStateChanged, reload, sendEmailVerification, signOut, User } from "firebase/auth";
import { Brand } from "../../../components/brand";
import { firebaseAuth, firebaseConfigured } from "../../../lib/firebase";
import { apiBase } from "../../../lib/session";

export default function Onboarding() {
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
        // Continue; Firebase will surface a real authentication error on the protected request.
      }

      setVerified(Boolean(currentUser.emailVerified));
      setChecking(false);
    });
  }, []);

  const startWorkspace = async () => {
    const currentUser = firebaseAuth?.currentUser;
    if (!currentUser) {
      window.location.assign("/login");
      return;
    }

    setBusy(true);
    setMessage("");

    try {
      await reload(currentUser);
      const refreshedUser = firebaseAuth?.currentUser;

      if (!refreshedUser) {
        window.location.assign("/login");
        return;
      }

      if (!refreshedUser.emailVerified) {
        setVerified(false);
        setMessage("Please verify your email first, then click “I’ve verified my email”.");
        return;
      }

      const token = await refreshedUser.getIdToken(true);
      const endpoint = isTrial ? "/auth/onboarding/trial" : "/auth/onboarding/organization";
      const body = isTrial
        ? JSON.stringify({ laboratory_name: name || undefined })
        : JSON.stringify({ organization_name: name });

      const response = await fetch(apiBase + endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + token,
        },
        body,
      });

      if (response.ok || response.status === 409) {
        window.location.assign("/app/dashboard");
        return;
      }

      const responseBody = await response.json().catch(() => null);
      setMessage(responseBody?.detail || "SIRALOOM could not create your workspace.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create your SIRALOOM workspace.");
    } finally {
      setBusy(false);
    }
  };

  const refreshVerification = async () => {
    const currentUser = firebaseAuth?.currentUser;
    if (!currentUser) {
      window.location.assign("/login");
      return;
    }

    setBusy(true);
    setMessage("");

    try {
      await reload(currentUser);
      const refreshedUser = firebaseAuth?.currentUser;
      const isVerified = Boolean(refreshedUser?.emailVerified);
      setVerified(isVerified);

      if (isVerified) {
        await startWorkspace();
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
    return <main className="loading">Preparing secure onboarding…</main>;
  }

  if (!firebaseConfigured || !user) {
    return (
      <main className="auth-page">
        <Brand />
        <section className="auth-card">
          <p className="eyebrow">SIRALOOM</p>
          <h1>Secure access required</h1>
          <p>{message || "Please sign in before starting your SIRALOOM workspace."}</p>
          <a className="button" href="/login">Return to sign in</a>
        </section>
      </main>
    );
  }

  return (
    <main className="auth-page">
      <Brand />
      <section className="auth-card">
        <p className="eyebrow">{isTrial ? "SIRALOOM FREE TRIAL" : "ORGANIZATION ONBOARDING"}</p>
        <h1>{isTrial ? "Your trial workspace is ready to be created" : "Set up your laboratory workspace"}</h1>
        <p>
          {isTrial
            ? "SIRALOOM will automatically create your private trial workspace. No payment method is required."
            : "SIRALOOM will create the organization and assign you the initial administrator role server-side."}
        </p>

        <div className="configuration-notice">
          <strong>{user.displayName || user.email}</strong>
          <br />
          {user.email}
        </div>

        {isTrial && (
          <label>
            Laboratory name (optional)
            <input value={name} onChange={e => setName(e.target.value)} disabled={busy} />
          </label>
        )}

        {!verified ? (
          <>
            <p>We need your verified email before creating the workspace. Check your inbox for the Firebase verification email.</p>
            <button className="button" onClick={refreshVerification} disabled={busy}>
              {busy ? "Checking…" : "I’ve verified my email"}
            </button>
            <button
              type="button"
              className="text-button"
              onClick={() =>
                firebaseAuth?.currentUser &&
                sendEmailVerification(firebaseAuth.currentUser)
                  .then(() => setMessage("Verification email sent."))
                  .catch(error => setMessage(error instanceof Error ? error.message : "Unable to send verification email."))
              }
              disabled={busy}
            >
              Resend verification email
            </button>
          </>
        ) : (
          <button className="button" onClick={startWorkspace} disabled={busy}>
            {busy ? "Creating workspace…" : isTrial ? "Start Free Trial" : "Create organization"}
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
