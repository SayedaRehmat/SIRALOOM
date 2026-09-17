"use client";
import { FormEvent, useEffect, useState } from "react";
import { sendEmailVerification } from "firebase/auth";
import { Brand } from "../../../components/brand";
import { firebaseAuth } from "../../../lib/firebase";
import { apiBase } from "../../../lib/session";

export default function Onboarding() {
  // Read the query param directly rather than via useSearchParams(): this page is
  // entirely client-rendered already (it depends on firebaseAuth.currentUser), so this
  // avoids requiring a Suspense boundary for what is otherwise a one-line lookup.
  const [isTrial, setIsTrial] = useState(true);
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setIsTrial(params.get("trial") !== "0" && params.get("mode") !== "organization");
    const user = firebaseAuth?.currentUser;
    if (!user) {
      window.location.assign("/login");
      return;
    }
    setReady(true);
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const user = firebaseAuth?.currentUser;
    if (!user) return;
    if (!user.emailVerified) {
      setMessage("Verify your email first, then refresh this page.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const token = await user.getIdToken(true);
      const endpoint = isTrial ? "/auth/onboarding/trial" : "/auth/onboarding/organization";
      const body = isTrial
        ? JSON.stringify({ laboratory_name: name || undefined })
        : JSON.stringify({ organization_name: name });
      const res = await fetch(`${apiBase}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body,
      });
      const responseBody = await res.json();
      if (!res.ok) throw new Error(responseBody.detail ?? "Onboarding failed");
      window.location.assign("/app/dashboard");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Onboarding failed");
    } finally {
      setBusy(false);
    }
  };

  if (!ready) return <main className="loading">Preparing secure onboarding…</main>;

  return (
    <main className="auth-page">
      <Brand />
      <form className="auth-card" onSubmit={submit}>
        <p className="eyebrow">{isTrial ? "FREE TRIAL" : "ORGANIZATION ONBOARDING"}</p>
        <h1>{isTrial ? "Your SIRALOOM trial workspace" : "Set up your laboratory workspace"}</h1>
        <p>
          {isTrial
            ? "14 days, 5 trial analyses, sample data included. Workspace access is created server-side; your browser cannot choose a role."
            : "Organization access is created server-side. Your browser cannot choose a role."}
        </p>
        <label>
          {isTrial ? "Laboratory name (optional)" : "Organization name"}
          <input value={name} onChange={e => setName(e.target.value)} required={!isTrial} />
        </label>
        {message && <p className="form-message">{message}</p>}
        <button className="button" disabled={busy}>{busy ? "Working…" : isTrial ? "Start Free Trial" : "Create organization"}</button>
        <button
          type="button"
          className="text-button"
          onClick={() => firebaseAuth?.currentUser && sendEmailVerification(firebaseAuth.currentUser).then(() => setMessage("Verification email sent."))}
        >
          Resend verification email
        </button>
      </form>
    </main>
  );
}
