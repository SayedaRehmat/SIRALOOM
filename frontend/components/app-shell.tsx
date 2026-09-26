"use client";

import Link from "next/link";
import { ReactNode, useEffect, useState } from "react";
import { onAuthStateChanged, signOut } from "firebase/auth";
import { firebaseAuth, firebaseConfigured } from "../lib/firebase";
import { useLanguage } from "../lib/i18n";
import { Brand } from "./brand";

export function AppShell({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const { language, setLanguage, t } = useLanguage();

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
    <div className="app-frame">
      <aside className="app-nav">
        <Brand />
        <span className="nav-label">{t("app.workspace")}</span>
        <Link href="/app/dashboard">{t("nav.dashboard")}</Link>
        <Link href="/app/cases">{t("nav.cases")}</Link>
        <Link href="/app/workspace">{t("nav.variantWorkspace")}</Link>
        <span className="nav-label">{t("app.governance")}</span>
        <Link href="/app/review">{t("nav.reviewQueue")}</Link>
        <Link href="/app/reports">{t("nav.reports")}</Link>
        <Link href="/app/audit">{t("nav.audit")}</Link>
        <Link href="/app/settings">{t("nav.settings")}</Link>
        <button className="text-button" onClick={() => firebaseAuth && signOut(firebaseAuth)}>{t("nav.signOut")}</button>
      </aside>
      <main className="app-content">
        <div className="global-language-bar">
          <span className="global-language-label">{t("language.label")}</span>
          <div className="global-language-options" role="group" aria-label={t("language.label")}>
            <button type="button" className={language === "en" ? "language-option active" : "language-option"} onClick={() => setLanguage("en")} aria-pressed={language === "en"}>
              {t("language.english")}
            </button>
            <button type="button" className={language === "ar" ? "language-option active" : "language-option"} onClick={() => setLanguage("ar")} aria-pressed={language === "ar"}>
              {t("language.arabic")}
            </button>
            <button type="button" className={language === "bilingual" ? "language-option active" : "language-option"} onClick={() => setLanguage("bilingual")} aria-pressed={language === "bilingual"}>
              {t("language.bilingual")}
            </button>
          </div>
        </div>
        {!firebaseConfigured && <div className="configuration-notice">{t("development.notice")}</div>}
        {children}
      </main>
    </div>
  );
}
