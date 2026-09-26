"use client";

import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";
import { useLanguage } from "../../../lib/i18n";

export default function Services() {
  const { t } = useLanguage();
  return <SiteShell><main className="content-page"><p className="eyebrow">{t("public.services.eyebrow")}</p><h1>{t("public.services.title")}</h1><article className="service-card"><p className="eyebrow">{t("public.services.variant.eyebrow")}</p><h2>{t("public.services.variant.title")}</h2><p>{t("public.services.variant.body")}</p><Link className="text-link" href="/services/variant">{t("public.services.variant.link")}</Link></article><p className="quiet">{t("public.services.future")}</p></main></SiteShell>;
}