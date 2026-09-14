"use client";
import Link from "next/link";
import { ReactNode, useEffect, useState } from "react";
import { onAuthStateChanged, signOut } from "firebase/auth";
import { firebaseAuth, firebaseConfigured } from "../lib/firebase";
import { Brand } from "./brand";

export function AppShell({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false); const [signedIn, setSignedIn] = useState(false);
  useEffect(() => { if (!firebaseAuth) { setReady(true); return; } return onAuthStateChanged(firebaseAuth, user => { setSignedIn(Boolean(user)); setReady(true); if (!user) window.location.assign("/login"); else if (!user.emailVerified) window.location.assign("/onboarding"); }); }, []);
  if (!ready) return <main className="loading">Checking secure session…</main>;
  if (firebaseConfigured && !signedIn) return null;
  return <div className="app-frame"><aside className="app-nav"><Brand /><span className="nav-label">WORKSPACE</span><Link href="/app/dashboard">Dashboard</Link><Link href="/app/cases">Cases</Link><Link href="/app/workspace">Variant workspace</Link><span className="nav-label">GOVERNANCE</span><Link href="/app/review">Review queue</Link><Link href="/app/reports">Reports</Link><a href="#">Audit</a><a href="#">Settings</a><button className="text-button" onClick={() => firebaseAuth && signOut(firebaseAuth)}>Sign out</button></aside><main className="app-content">{!firebaseConfigured && <div className="configuration-notice">Development mode: Firebase client configuration is absent. Production requires Firebase authentication and server-side membership provisioning.</div>}{children}</main></div>;
}
