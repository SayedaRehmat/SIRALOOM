"use client";

import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";
import { useLanguage } from "../../../lib/i18n";

export default function Pricing() {
  const { t } = useLanguage();

  return (
    <SiteShell>
      <main className="content-page public-content pricing-page">
        <p className="eyebrow">{t("public.pricing.eyebrow")}</p>
        <h1>{t("public.pricing.title")}</h1>
        <p className="lead">{t("public.pricing.lead")}</p>
        <div className="pricing-grid">
          <article className="pricing-card featured">
            <span>01</span>
            <h2>{t("public.pricing.trialTitle")}</h2>
            <p>{t("public.pricing.trialBody")}</p>
            <Link className="button" href="/signup">
              {t("public.pricing.trialCta")}
            </Link>
          </article>
          <article className="pricing-card">
            <span>02</span>
            <h2>{t("public.pricing.labTitle")}</h2>
            <p>{t("public.pricing.labBody")}</p>
            <Link className="button secondary" href="/contact">
              {t("public.pricing.labCta")}
            </Link>
          </article>
          <article className="pricing-card">
            <span>03</span>
            <h2>{t("public.pricing.enterpriseTitle")}</h2>
            <p>{t("public.pricing.enterpriseBody")}</p>
            <Link className="button secondary" href="/contact">
              {t("public.pricing.enterpriseCta")}
            </Link>
          </article>
        </div>
        <p className="quiet">{t("public.pricing.note")}</p>
      </main>
    </SiteShell>
  );
}
