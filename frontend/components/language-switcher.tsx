"use client";

import { useLanguage } from "../lib/i18n";

export function LanguageSwitcher({ className = "" }: { className?: string }) {
  const { language, setLanguage, t } = useLanguage();
  return (
    <div className={className ? `language-switcher ${className}` : "language-switcher"} role="group" aria-label={t("language.label")}>
      <span>{t("language.label")}</span>
      <button type="button" className={language === "en" ? "active" : ""} onClick={() => setLanguage("en")} aria-pressed={language === "en"}>{t("language.english")}</button>
      <button type="button" className={language === "ar" ? "active" : ""} onClick={() => setLanguage("ar")} aria-pressed={language === "ar"}>{t("language.arabic")}</button>
      <button type="button" className={language === "bilingual" ? "active" : ""} onClick={() => setLanguage("bilingual")} aria-pressed={language === "bilingual"}>{t("language.bilingual")}</button>
    </div>
  );
}
