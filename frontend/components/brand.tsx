"use client";

import Link from "next/link";
import { useLanguage } from "../lib/i18n";

export function Brand() {
  const { t } = useLanguage();
  return (
    <Link href="/" className="brand" aria-label="SIRALOOM home">
      <span className="brand-name">SIRALOOM</span>
      <span className="brand-tagline">{t("public.brand.tagline")}</span>
    </Link>
  );
}
