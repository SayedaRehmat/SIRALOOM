"use client";

import Link from "next/link";
import { ReactNode } from "react";
import { Brand } from "./brand";
import { LanguageSwitcher } from "./language-switcher";
import { useLanguage } from "../lib/i18n";

export function SiteShell({ children }: { children: ReactNode }) {
  const { t } = useLanguage();
  return (
    <>
      <header className="site-header">
        <Brand />
        <nav aria-label="Primary navigation">
          <Link href="/about">{t("public.about")}</Link>
          <Link href="/services">{t("public.services")}</Link>
          <Link href="/contact">{t("public.contact")}</Link>
        </nav>
        <div className="header-actions">
          <LanguageSwitcher />
          <Link className="text-link" href="/login">{t("public.signIn")}</Link>
          <Link className="button small" href="/signup">{t("public.startTrial")}</Link>
        </div>
      </header>
      {children}
      <footer className="site-footer">
        <Brand />
        <p>{t("public.home.lead")}</p>
        <div><Link href="/privacy">{t("public.privacy")}</Link><Link href="/terms">{t("public.terms")}</Link></div>
      </footer>
    </>
  );
}
