"use client";

import Link from "next/link";
import { SiteShell } from "../../../../components/site-shell";
import { useLanguage } from "../../../../lib/i18n";

export default function Variant() {
  const { t } = useLanguage();
  return <SiteShell><main className="content-page"><p className="eyebrow">{t("public.variant.eyebrow")}</p><h1>{t("public.variant.title")}</h1><p className="lead">{t("public.variant.lead")}</p><div className="process"><span>{t("public.variant.case")}</span><span>{t("public.variant.validate")}</span><span>{t("public.variant.normalize")}</span><span>{t("public.variant.evidence")}</span><span>{t("public.variant.review")}</span><span>{t("public.variant.report")}</span></div><p className="quiet">{t("public.variant.note")}</p><Link className="button" href="/signup">{t("public.variant.create")}</Link></main></SiteShell>;
}