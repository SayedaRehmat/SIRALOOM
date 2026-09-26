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
  | "development.notice"
  | "dashboard.eyebrow"
  | "dashboard.title"
  | "dashboard.lead"
  | "dashboard.cases.title"
  | "dashboard.cases.body"
  | "dashboard.cases.link"
  | "dashboard.variant.title"
  | "dashboard.variant.body"
  | "dashboard.variant.link"
  | "dashboard.review.title"
  | "dashboard.review.body"
  | "dashboard.review.link"
  | "settings.eyebrow"
  | "settings.title"
  | "settings.lead"
  | "settings.identity"
  | "settings.currentSession"
  | "settings.email"
  | "settings.role"
  | "settings.userId"
  | "settings.organization"
  | "settings.entitlement"
  | "settings.loadingSession"
  | "settings.service"
  | "settings.backendConnection"
  | "settings.api"
  | "settings.health"
  | "settings.serverControlled"
  | "settings.activeContext"
  | "settings.browserContext"
  | "settings.caseId"
  | "settings.analysisId"
  | "settings.contextNote"
  | "settings.unableToLoad";;

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
    "dashboard.eyebrow": "DASHBOARD",
    "dashboard.title": "Laboratory workspace",
    "dashboard.lead": "Start with a case, then use the existing Variant workspace to inspect durable workflow state.",
    "dashboard.cases.title": "Cases",
    "dashboard.cases.body": "Case-centered intake and longitudinal analysis history.",
    "dashboard.cases.link": "Open cases →",
    "dashboard.variant.title": "Variant service",
    "dashboard.variant.body": "Existing implementation workspace for analysis, review, reports, and audit.",
    "dashboard.variant.link": "Open workspace →",
    "dashboard.review.title": "Clinical review",
    "dashboard.review.body": "Prioritized interpretation queue with evidence-linked ACMG review and versioned decisions.",
    "dashboard.review.link": "Open review queue →",
    "settings.eyebrow": "GOVERNANCE · CONFIGURATION",
    "settings.title": "Settings",
    "settings.lead": "Authenticated workspace identity, entitlement, service connection, and active workflow context.",
    "settings.identity": "IDENTITY",
    "settings.currentSession": "Current session",
    "settings.email": "Email",
    "settings.role": "Role",
    "settings.userId": "User ID",
    "settings.organization": "Organization",
    "settings.entitlement": "Entitlement",
    "settings.loadingSession": "Loading authenticated session…",
    "settings.service": "SERVICE",
    "settings.backendConnection": "Backend connection",
    "settings.api": "API",
    "settings.health": "Health",
    "settings.serverControlled": "Scientific resources and workflow configuration remain server-controlled. This page does not expose unsafe client-side overrides.",
    "settings.activeContext": "ACTIVE CONTEXT",
    "settings.browserContext": "Browser workflow context",
    "settings.caseId": "Case ID",
    "settings.analysisId": "Analysis ID",
    "settings.contextNote": "Selecting a case from the Cases registry updates this context automatically.",
    "settings.unableToLoad": "Unable to load settings.",
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
    "dashboard.eyebrow": "لوحة المعلومات",
    "dashboard.title": "مساحة عمل المختبر",
    "dashboard.lead": "ابدأ بحالة، ثم استخدم مساحة تحليل المتغيرات لمراجعة حالة سير العمل المحفوظة بشكل مستمر.",
    "dashboard.cases.title": "الحالات",
    "dashboard.cases.body": "استقبال متمحور حول الحالة وسجل التحليل الطولي.",
    "dashboard.cases.link": "فتح الحالات ←",
    "dashboard.variant.title": "خدمة المتغيرات",
    "dashboard.variant.body": "مساحة العمل الحالية للتحليل والمراجعة والتقارير والتدقيق.",
    "dashboard.variant.link": "فتح مساحة العمل ←",
    "dashboard.review.title": "المراجعة السريرية",
    "dashboard.review.body": "قائمة انتظار لتفسير المتغيرات مرتبة حسب الأولوية مع مراجعة ACMG المرتبطة بالأدلة وقرارات ذات إصدارات.",
    "dashboard.review.link": "فتح قائمة المراجعة ←",
    "settings.eyebrow": "الحوكمة · الإعدادات",
    "settings.title": "الإعدادات",
    "settings.lead": "هوية مساحة العمل الموثقة، والاستحقاق، واتصال الخدمة، وسياق سير العمل النشط.",
    "settings.identity": "الهوية",
    "settings.currentSession": "الجلسة الحالية",
    "settings.email": "البريد الإلكتروني",
    "settings.role": "الدور",
    "settings.userId": "معرّف المستخدم",
    "settings.organization": "المؤسسة",
    "settings.entitlement": "الاستحقاق",
    "settings.loadingSession": "جارٍ تحميل الجلسة الموثقة…",
    "settings.service": "الخدمة",
    "settings.backendConnection": "اتصال الخادم",
    "settings.api": "واجهة API",
    "settings.health": "الحالة",
    "settings.serverControlled": "تبقى الموارد العلمية وإعدادات سير العمل تحت تحكم الخادم. لا تعرض هذه الصفحة إعدادات آمنة قابلة للتجاوز من العميل.",
    "settings.activeContext": "السياق النشط",
    "settings.browserContext": "سياق سير العمل في المتصفح",
    "settings.caseId": "معرّف الحالة",
    "settings.analysisId": "معرّف التحليل",
    "settings.contextNote": "يؤدي اختيار حالة من سجل الحالات إلى تحديث هذا السياق تلقائياً.",
    "settings.unableToLoad": "تعذر تحميل الإعدادات.",
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
    "dashboard.eyebrow": "DASHBOARD · لوحة المعلومات",
    "dashboard.title": "Laboratory workspace · مساحة عمل المختبر",
    "dashboard.lead": "Start with a case, then use the existing Variant workspace to inspect durable workflow state. · ابدأ بحالة، ثم استخدم مساحة تحليل المتغيرات لمراجعة حالة سير العمل المحفوظة.",
    "dashboard.cases.title": "Cases · الحالات",
    "dashboard.cases.body": "Case-centered intake and longitudinal analysis history. · استقبال متمحور حول الحالة وسجل التحليل الطولي.",
    "dashboard.cases.link": "Open cases → · فتح الحالات ←",
    "dashboard.variant.title": "Variant service · خدمة المتغيرات",
    "dashboard.variant.body": "Existing implementation workspace for analysis, review, reports, and audit. · مساحة العمل الحالية للتحليل والمراجعة والتقارير والتدقيق.",
    "dashboard.variant.link": "Open workspace → · فتح مساحة العمل ←",
    "dashboard.review.title": "Clinical review · المراجعة السريرية",
    "dashboard.review.body": "Prioritized interpretation queue with evidence-linked ACMG review and versioned decisions. · قائمة انتظار لتفسير المتغيرات مرتبة حسب الأولوية مع مراجعة ACMG المرتبطة بالأدلة.",
    "dashboard.review.link": "Open review queue → · فتح قائمة المراجعة ←",
    "settings.eyebrow": "GOVERNANCE · CONFIGURATION · الحوكمة · الإعدادات",
    "settings.title": "Settings · الإعدادات",
    "settings.lead": "Authenticated workspace identity, entitlement, service connection, and active workflow context. · هوية مساحة العمل الموثقة، والاستحقاق، واتصال الخدمة، وسياق سير العمل النشط.",
    "settings.identity": "IDENTITY · الهوية",
    "settings.currentSession": "Current session · الجلسة الحالية",
    "settings.email": "Email · البريد الإلكتروني",
    "settings.role": "Role · الدور",
    "settings.userId": "User ID · معرّف المستخدم",
    "settings.organization": "Organization · المؤسسة",
    "settings.entitlement": "Entitlement · الاستحقاق",
    "settings.loadingSession": "Loading authenticated session · جارٍ تحميل الجلسة الموثقة…",
    "settings.service": "SERVICE · الخدمة",
    "settings.backendConnection": "Backend connection · اتصال الخادم",
    "settings.api": "API · واجهة API",
    "settings.health": "Health · الحالة",
    "settings.serverControlled": "Scientific resources and workflow configuration remain server-controlled. · تبقى الموارد العلمية وإعدادات سير العمل تحت تحكم الخادم.",
    "settings.activeContext": "ACTIVE CONTEXT · السياق النشط",
    "settings.browserContext": "Browser workflow context · سياق سير العمل في المتصفح",
    "settings.caseId": "Case ID · معرّف الحالة",
    "settings.analysisId": "Analysis ID · معرّف التحليل",
    "settings.contextNote": "Selecting a case from the Cases registry updates this context automatically. · يؤدي اختيار حالة من سجل الحالات إلى تحديث هذا السياق تلقائياً.",
    "settings.unableToLoad": "Unable to load settings. · تعذر تحميل الإعدادات.",
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
