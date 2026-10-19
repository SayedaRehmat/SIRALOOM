"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";
import { onAuthStateChanged, signOut, type User } from "firebase/auth";
import { firebaseAuth, firebaseConfigured } from "../lib/firebase";
import { useLanguage } from "../lib/i18n";
import { apiBase } from "../lib/session";
import { canShowProtectedContent, verifyBackendSession } from "../lib/backend-session.mjs";
import { syncWorkspaceContext, workspaceIdentityKey } from "../lib/workspace-context.mjs";
import { Brand } from "./brand";
import { LanguageSwitcher } from "./language-switcher";

export function AppShell({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [backendSession, setBackendSession] = useState<"CHECKING" | "ACTIVE" | "UNAVAILABLE" | "RESTRICTED">("CHECKING");
  const [sessionRetry, setSessionRetry] = useState(0);
  const [authUid, setAuthUid] = useState<string | null>(null);
  const [signOutError, setSignOutError] = useState(false);
  const pathname = usePathname();
  const { t } = useLanguage();
  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);

  useEffect(() => {
    const auth = firebaseAuth;
    if (!auth) {
      setReady(true);
      setBackendSession("ACTIVE");
      return;
    }

    let mounted = true;
    let validationInProgress = false;

    const validateSession = async (user: User, maskContent = false) => {
      if (validationInProgress) return;
      validationInProgress = true;
      if (maskContent) setBackendSession("CHECKING");
      try {
        const token = await user.getIdToken();
        const result = await verifyBackendSession(token, { apiBase });
        if (!mounted || auth.currentUser?.uid !== user.uid) return;
        if (result === "RESTRICTED") {
          setBackendSession("RESTRICTED");
          await signOut(auth).catch(() => undefined);
          window.location.assign("/login?access=restricted");
          return;
        }
        setBackendSession(result);
      } catch {
        if (mounted && auth.currentUser?.uid === user.uid) {
          setBackendSession("UNAVAILABLE");
        }
      } finally {
        validationInProgress = false;
        const latestUser = auth.currentUser;
        if (mounted && latestUser?.emailVerified && latestUser.uid !== user.uid) {
          void validateSession(latestUser, true);
        } else if (mounted) {
          setReady(true);
        }
      }
    };

    const unsubscribe = onAuthStateChanged(auth, (user) => {
      try {
        syncWorkspaceContext(window.localStorage, user?.uid ?? null);
      } catch {
        // Authentication and protected routing must work if browser storage is disabled.
      }
      setAuthUid(user?.uid ?? null);
      setSignedIn(Boolean(user));
      setBackendSession("CHECKING");
      setReady(false);
      if (!user) {
        setBackendSession("RESTRICTED");
        setReady(true);
        window.location.assign("/login");
      } else if (!user.emailVerified) {
        setBackendSession("RESTRICTED");
        setReady(true);
        window.location.assign("/onboarding");
      } else {
        void validateSession(user, true);
      }
    });

    const refreshWhenVisible = () => {
      const user = auth.currentUser;
      if (document.visibilityState === "visible" && user?.emailVerified) {
        void validateSession(user, true);
      }
    };
    document.addEventListener("visibilitychange", refreshWhenVisible);
    const interval = window.setInterval(() => {
      const user = auth.currentUser;
      if (document.visibilityState === "visible" && user?.emailVerified) {
        void validateSession(user);
      }
    }, 60_000);

    return () => {
      mounted = false;
      unsubscribe();
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      window.clearInterval(interval);
    };
  }, [sessionRetry]);

  async function handleSignOut() {
    if (!firebaseAuth) return;
    setSignOutError(false);
    try {
      await signOut(firebaseAuth);
    } catch {
      setSignOutError(true);
    }
  }

  if (!ready) return <main className="loading">{t("session.checking")}</main>;
  if (firebaseConfigured && backendSession === "UNAVAILABLE") {
    return (
      <main className="loading" role="alert">
        <p>{t("session.unavailable")}</p>
        <button className="button" onClick={() => {
          setReady(false);
          setBackendSession("CHECKING");
          setSessionRetry((attempt) => attempt + 1);
        }}>{t("session.retry")}</button>
      </main>
    );
  }
  if (!canShowProtectedContent({ firebaseConfigured, signedIn, backendSession })) return null;

  return (
    <div className="app-frame siraloom-workspace">
      <aside className="app-nav">
        <div className="app-nav-brand">
          <Brand />
          <span className="app-nav-context">{t("app.workspace")}</span>
        </div>
        <nav className="app-nav-links" aria-label={t("app.workspace")}>
          <span className="nav-label">{t("app.workspace")}</span>
          <Link href="/app/dashboard" className={isActive("/app/dashboard") ? "active" : undefined} aria-current={isActive("/app/dashboard") ? "page" : undefined}>{t("nav.dashboard")}</Link>
          <Link href="/app/operations" className={isActive("/app/operations") ? "active" : undefined} aria-current={isActive("/app/operations") ? "page" : undefined}>{t("nav.operations")}</Link>
          <Link href="/app/cases" className={isActive("/app/cases") ? "active" : undefined} aria-current={isActive("/app/cases") ? "page" : undefined}>{t("nav.cases")}</Link>
          <Link href="/app/workspace" className={isActive("/app/workspace") ? "active" : undefined} aria-current={isActive("/app/workspace") ? "page" : undefined}>{t("nav.variantWorkspace")}</Link>
          <span className="nav-label">{t("app.governance")}</span>
          <Link href="/app/review" className={isActive("/app/review") ? "active" : undefined} aria-current={isActive("/app/review") ? "page" : undefined}>{t("nav.reviewQueue")}</Link>
          <Link href="/app/resources" className={isActive("/app/resources") ? "active" : undefined} aria-current={isActive("/app/resources") ? "page" : undefined}>{t("nav.resources")}</Link>
          <Link href="/app/reports" className={isActive("/app/reports") ? "active" : undefined} aria-current={isActive("/app/reports") ? "page" : undefined}>{t("nav.reports")}</Link>
          <Link href="/app/audit" className={isActive("/app/audit") ? "active" : undefined} aria-current={isActive("/app/audit") ? "page" : undefined}>{t("nav.audit")}</Link>
          <Link href="/app/settings" className={isActive("/app/settings") ? "active" : undefined} aria-current={isActive("/app/settings") ? "page" : undefined}>{t("nav.settings")}</Link>
        </nav>
        <div className="app-nav-footer">
          <LanguageSwitcher className="workspace-language-switcher" />
          {signOutError && <p role="alert">{t("nav.signOutFailed")}</p>}
          <button className="text-button" onClick={handleSignOut}>{t("nav.signOut")}</button>
        </div>
      </aside>
      <main className="app-content">
        {!firebaseConfigured && <div className="configuration-notice">{t("development.notice")}</div>}
        <div key={workspaceIdentityKey(authUid)}>{children}</div>
      </main>
    </div>
  );
}
