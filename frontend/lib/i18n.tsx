"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type AppLanguage = "en" | "ar" | "bilingual";

type TranslationKey =
  | "app.workspace"
  | "app.governance"
  | "nav.dashboard"
  | "nav.cases"
  | "nav.variantWorkspace"
  | "nav.reviewQueue"
  | "nav.reports"
  | "nav.audit"
  | "nav.settings"
  | "nav.signOut"
  | "language.label"
  | "language.english"
  | "language.arabic"
  | "language.bilingual"
  | "session.checking"
  | "development.notice";

const translations: Record<AppLanguage, Partial<Record<TranslationKey, string>>> = {
  en: {
    "app.workspace": "WORKSPACE",
    "app.governance": "GOVERNANCE",
    "nav.dashboard": "Dashboard",
    "nav.cases": "Cases",
    "nav.variantWorkspace": "Variant workspace",
    "nav.reviewQueue": "Review queue",
    "nav.reports": "Reports",
    "nav.audit": "Audit",
    "nav.settings": "Settings",
    "nav.signOut": "Sign out",
    "language.label": "Language",
    "language.english": "English",
    "language.arabic": "Arabic",
    "language.bilingual": "Bilingual",
    "session.checking": "Checking secure session…",
    "development.notice": "Development mode: Firebase client configuration is absent. Production requires Firebase authentication and server-side membership provisioning.",
  },
  ar: {
    "app.workspace": "مساحة العمل",
    "app.governance": "الحوكمة",
    "nav.dashboard": "لوحة المعلومات",
    "nav.cases": "الحالات",
    "nav.variantWorkspace": "مساحة تحليل المتغيرات",
    "nav.reviewQueue": "قائمة المراجعة",
    "nav.reports": "التقارير",
    "nav.audit": "التدقيق والسجل",
    "nav.settings": "الإعدادات",
    "nav.signOut": "تسجيل الخروج",
    "language.label": "اللغة",
    "language.english": "الإنجليزية",
    "language.arabic": "العربية",
    "language.bilingual": "ثنائي اللغة",
    "session.checking": "جارٍ التحقق من الجلسة الآمنة…",
    "development.notice": "وضع التطوير: إعدادات Firebase للعميل غير موجودة. يتطلب الإنتاج مصادقة Firebase وتوفير العضوية على الخادم.",
  },
  bilingual: {
    "app.workspace": "WORKSPACE · مساحة العمل",
    "app.governance": "GOVERNANCE · الحوكمة",
    "nav.dashboard": "Dashboard · لوحة المعلومات",
    "nav.cases": "Cases · الحالات",
    "nav.variantWorkspace": "Variant workspace · مساحة تحليل المتغيرات",
    "nav.reviewQueue": "Review queue · قائمة المراجعة",
    "nav.reports": "Reports · التقارير",
    "nav.audit": "Audit · التدقيق والسجل",
    "nav.settings": "Settings · الإعدادات",
    "nav.signOut": "Sign out · تسجيل الخروج",
    "language.label": "Language · اللغة",
    "language.english": "English",
    "language.arabic": "Arabic · العربية",
    "language.bilingual": "Bilingual · ثنائي اللغة",
    "session.checking": "Checking secure session · جارٍ التحقق من الجلسة الآمنة…",
    "development.notice": "Development mode · وضع التطوير: Firebase client configuration is absent. Production requires Firebase authentication and server-side membership provisioning.",
  },
};

const fallbackLanguage: AppLanguage = "en";
const storageKey = "siraloom.language";

function isAppLanguage(value: string | null): value is AppLanguage {
  return value === "en" || value === "ar" || value === "bilingual";
}

type LanguageContextValue = {
  language: AppLanguage;
  setLanguage: (language: AppLanguage) => void;
  t: (key: TranslationKey) => string;
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<AppLanguage>(fallbackLanguage);

  useEffect(() => {
    const stored = window.localStorage.getItem(storageKey);
    if (isAppLanguage(stored)) setLanguageState(stored);
  }, []);

  useEffect(() => {
    document.documentElement.lang = language === "ar" ? "ar" : "en";
    document.documentElement.dir = language === "ar" ? "rtl" : "ltr";
    window.localStorage.setItem(storageKey, language);
  }, [language]);

  const value = useMemo<LanguageContextValue>(() => ({
    language,
    setLanguage: (nextLanguage) => setLanguageState(nextLanguage),
    t: (key) => translations[language][key] ?? translations.en[key] ?? key,
  }), [language]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
  const context = useContext(LanguageContext);
  if (!context) throw new Error("useLanguage must be used within LanguageProvider");
  return context;
}
