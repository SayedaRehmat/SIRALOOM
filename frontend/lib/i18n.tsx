"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { messages, type TranslationKey } from "./messages";

export type AppLanguage = "en" | "ar" | "bilingual";
export type AppDirection = "ltr" | "rtl";

const storageKey = "siraloom.language";
const cookieKey = "siraloom.language";
const defaultLanguage: AppLanguage = "en";

function isAppLanguage(value: string | null): value is AppLanguage {
  return value === "en" || value === "ar" || value === "bilingual";
}

function directionFor(language: AppLanguage): AppDirection {
  return language === "ar" ? "rtl" : "ltr";
}

function readInitialLanguage(initialLanguage?: AppLanguage): AppLanguage {
  if (initialLanguage) return initialLanguage;
  if (typeof window === "undefined") return defaultLanguage;
  const stored = window.localStorage.getItem(storageKey);
  return isAppLanguage(stored) ? stored : defaultLanguage;
}

function persistLanguage(language: AppLanguage) {
  window.localStorage.setItem(storageKey, language);
  document.cookie = `${cookieKey}=${encodeURIComponent(language)}; Path=/; Max-Age=31536000; SameSite=Lax`;
}

export function getMessage(language: AppLanguage, key: TranslationKey): string {
  const english = messages.en[key] ?? key;
  if (language === "en") return english;
  if (language === "ar") return messages.ar[key] ?? english;
  return `${english} · ${messages.ar[key] ?? english}`;
}

type LanguageContextValue = {
  language: AppLanguage;
  direction: AppDirection;
  setLanguage: (language: AppLanguage) => void;
  t: (key: TranslationKey) => string;
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({
  children,
  initialLanguage,
}: {
  children: ReactNode;
  initialLanguage?: AppLanguage;
}) {
  const [language, setLanguageState] = useState<AppLanguage>(() =>
    readInitialLanguage(initialLanguage),
  );

  useEffect(() => {
    const stored = window.localStorage.getItem(storageKey);
    if (isAppLanguage(stored)) setLanguageState(stored);
  }, []);

  useEffect(() => {
    const direction = directionFor(language);
    document.documentElement.lang = language === "ar" ? "ar" : "en";
    document.documentElement.dir = direction;
    document.documentElement.dataset.language = language;
    document.documentElement.dataset.direction = direction;
    persistLanguage(language);
  }, [language]);

  const value = useMemo<LanguageContextValue>(
    () => ({
      language,
      direction: directionFor(language),
      setLanguage: setLanguageState,
      t: (key) => getMessage(language, key),
    }),
    [language],
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
  const context = useContext(LanguageContext);
  if (!context) throw new Error("useLanguage must be used within LanguageProvider");
  return context;
}
