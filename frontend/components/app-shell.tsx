"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";
import { onAuthStateChanged, signOut } from "firebase/auth";
import { firebaseAuth, firebaseConfigured } from "../lib/firebase";
import { useLanguage } from "../lib/i18n";
import { Brand } from "./brand";
import { LanguageSwitcher } from "./language-switcher";

export function AppShell({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const pathname = usePathname();
  const { t } = useLanguage();
  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);

  useEffect(() => {
    if (!firebaseAuth) {
      setReady(true);
      return;
    }

    return onAuthStateChanged(firebaseAuth, (user) => {
      setSignedIn(Boolean(user));
      setReady(true);
      if (!user) window.location.assign("/login");
      else if (!user.emailVerified) window.location.assign("/onboarding");
    });
  }, []);

  if (!ready) return <main className="loading">{t("session.checking")}</main>;
  if (firebaseConfigured && !signedIn) return null;

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
          <button className="text-button" onClick={() => firebaseAuth && signOut(firebaseAuth)}>{t("nav.signOut")}</button>
        </div>
      </aside>
      <main className="app-content">
        {!firebaseConfigured && <div className="configuration-notice">{t("development.notice")}</div>}
        {children}
      </main>
    </div>
  );
}
