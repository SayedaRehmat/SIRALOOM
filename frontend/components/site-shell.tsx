"use client";

import Link from "next/link";
import { ReactNode } from "react";
import { Brand } from "./brand";
import { useLanguage } from "../lib/i18n";
import { LanguageSwitcher } from "./language-switcher";

export function SiteShell({ children, showLanguageSwitcher = true }: { children: ReactNode; showLanguageSwitcher?: boolean }) {
  const { language } = useLanguage();
  const bilingual = (en: string, ar: string) => language === "ar" ? ar : language === "bilingual" ? `${en} · ${ar}` : en;

  return (
    <div className="public-site">
      <header className="site-header" role="banner">
        <Link href="/" className="site-brand-link" aria-label="SIRALOOM home"><Brand /></Link>
        <nav className="site-nav" aria-label="Primary navigation">
          <Link href="/services">{bilingual("Product", "المنتج")}</Link>
          <Link href="/about">{bilingual("For laboratories", "للمختبرات")}</Link>
          <Link href="/pricing">{bilingual("Plans", "الخطط")}</Link>
          <Link href="/contact">{bilingual("Contact", "تواصل")}</Link>
        </nav>
        <div className="header-actions">
          {showLanguageSwitcher && <LanguageSwitcher className="homepage-language-switcher" />}
          <Link className="text-link" href="/login">{bilingual("Sign in", "تسجيل الدخول")}</Link>
          <Link className="button small" href="/signup">{bilingual("Request access", "طلب الوصول")}</Link>
        </div>
      </header>
      {children}
      <footer className="site-footer">
        <div className="footer-main">
          <div>
            <Link href="/" className="site-brand-link" aria-label="SIRALOOM home"><Brand /></Link>
            <p>{bilingual("Case-based genomic workflow software for analysis, interpretation, review and reporting.", "منصة لإدارة سير العمل الجينومي القائم على الحالات للتحليل والتفسير والمراجعة وإصدار التقارير.")}</p>
          </div>
          <div className="footer-links">
            <div><strong>{bilingual("Product", "المنتج")}</strong><Link href="/services">{bilingual("SIRALOOM Variant", "SIRALOOM Variant")}</Link><Link href="/contact">{bilingual("Laboratory deployment", "نشر المختبر")}</Link></div>
            <div><strong>{bilingual("Governance", "الحوكمة")}</strong><Link href="/privacy">{bilingual("Privacy", "الخصوصية")}</Link><Link href="/terms">{bilingual("Terms", "الشروط")}</Link></div>
          </div>
        </div>
        <div className="footer-bottom">
          <span>© {new Date().getFullYear()} SIRALOOM</span>
          <span>{bilingual("Scientific software; laboratory validation and sign-out remain under the laboratory's governance.", "برنامج علمي؛ تبقى المصادقة المختبرية والإصدار النهائي للتقارير ضمن حوكمة المختبر.")}</span>
        </div>
      </footer>
    </div>
  );
}
