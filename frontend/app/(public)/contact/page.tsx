"use client";

import { SiteShell } from "../../../components/site-shell";
import { useLanguage } from "../../../lib/i18n";

export default function Contact() {
  const { t } = useLanguage();
  return (
    <SiteShell>
      <main className="content-page public-content">
        <p className="eyebrow">{t("public.contact.eyebrow")}</p>
        <h1>{t("public.contact.title")}</h1>
        <p className="lead">{t("public.contact.lead")}</p>
        <div className="contact-grid">
          <article><span>01</span><h2>{t("public.pricing.labTitle")}</h2><p>{t("public.pricing.labBody")}</p></article>
          <article><span>02</span><h2>{t("public.pricing.enterpriseTitle")}</h2><p>{t("public.pricing.enterpriseBody")}</p></article>
          <article><span>03</span><h2>{t("public.home.review.title")}</h2><p>{t("public.home.review.body")}</p></article>
        </div>
        <p className="quiet">{t("public.contact.note")}</p>
      </main>
    </SiteShell>
  );
}
