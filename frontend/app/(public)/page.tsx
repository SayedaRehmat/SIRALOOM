"use client";

import Link from "next/link";
import { SiteShell } from "../../components/site-shell";
import { useLanguage } from "../../lib/i18n";

export default function Home() {
  const { t } = useLanguage();
  return <SiteShell><main><section className="hero"><div><p className="eyebrow">{t("public.home.eyebrow")}</p><h1>{t("public.home.title")}</h1><p className="lead">{t("public.home.lead")}</p><div className="actions"><Link className="button" href="/signup">{t("public.startTrial")}</Link><Link className="text-link" href="/services/variant">{t("public.services.variant.link")}</Link></div></div><div className="molecule" aria-hidden="true"><span /><span /><span /><span /><span /></div></section><section className="feature-grid"><article><b>{t("public.home.traceable.title")}</b><p>{t("public.home.traceable.body")}</p></article><article><b>{t("public.home.review.title")}</b><p>{t("public.home.review.body")}</p></article><article><b>{t("public.home.extend.title")}</b><p>{t("public.home.extend.body")}</p></article></section></main></SiteShell>;
}