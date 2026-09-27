import type { Metadata } from "next";
import { cookies } from "next/headers";
import type { ReactNode } from "react";
import "./globals.css";
import { LanguageProvider, type AppLanguage } from "../lib/i18n";

export const metadata: Metadata = {
  title: "SIRALOOM",
  description: "Evidence-connected genomic laboratory workflows",
};

function cookieLanguage(value: string | undefined): AppLanguage {
  return value === "ar" || value === "bilingual" ? value : "en";
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const cookieStore = await cookies();
  const language = cookieLanguage(cookieStore.get("siraloom.language")?.value);
  const direction = language === "ar" ? "rtl" : "ltr";

  return (
    <html lang={language === "ar" ? "ar" : "en"} dir={direction}>
      <body>
        <LanguageProvider initialLanguage={language}>{children}</LanguageProvider>
      </body>
    </html>
  );
}
