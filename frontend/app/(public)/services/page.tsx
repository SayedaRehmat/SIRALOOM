"use client";

import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";
import { useLanguage } from "../../../lib/i18n";

export default function Services() {
  const { t } = useLanguage();
  return (
    <SiteShell>
      <main className="content-page public-content">
        <p className="eyebrow">{t("public.services.eyebrow")}</p>
        <h1>{t("public.services.title")}</h1>
        <p className="lead">{t("public.platform.lead")}</p>
        <div className="platform-principles">
          <article><span>01</span><h2>{t("public.platform.caseTitle")}</h2><p>{t("public.platform.caseBody")}</p></article>
          <article><span>02</span><h2>{t("public.platform.workflowTitle")}</h2><p>{t("public.platform.workflowBody")}</p></article>
          <article><span>03</span><h2>{t("public.platform.governanceTitle")}</h2><p>{t("public.platform.governanceBody")}</p></article>
        </div>
        <article className="service-card public-product-card">
          <p className="eyebrow">{t("public.services.variant.eyebrow")}</p>
          <h2>{t("public.services.variant.title")}</h2>
          <p>{t("public.services.variant.body")}</p>
          <Link className="button secondary" href="/services/variant">{t("public.services.variant.link")}</Link>
        </article>
        <p className="quiet">{t("public.services.future")}</p>
      </main>
    </SiteShell>
  );
}
