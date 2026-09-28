"use client";

import Link from "next/link";
import { SiteShell } from "../../components/site-shell";
import { useLanguage } from "../../lib/i18n";

export default function Home() {
  const { t } = useLanguage();

  return (
    <SiteShell showLanguageSwitcher>
      <main>
        <section className="hero">
          <div>
            <p className="eyebrow">{t("public.home.eyebrow")}</p>
            <h1>{t("public.home.title")}</h1>
            <p className="lead">{t("public.home.lead")}</p>
            <div className="actions">
              <Link className="button" href="/signup">{t("public.startTrial")}</Link>
              <Link className="text-link" href="/services">{t("public.services")}</Link>
            </div>
          </div>

        </section>

        <section className="home-section home-lifecycle" aria-labelledby="lifecycle-title">
          <p className="section-kicker">{t("public.home.lifecycle.eyebrow")}</p>
          <h2 id="lifecycle-title">{t("public.home.lifecycle.title")}</h2>
          <p>{t("public.home.lifecycle.body")}</p>
          <div className="workflow-strip" aria-label={t("public.home.lifecycle.steps")}>
            {t("public.home.lifecycle.steps").split(" · ").map((step) => (
              <span key={step}>{step}</span>
            ))}
          </div>
        </section>

        <section className="home-section home-platform" aria-labelledby="platform-title">
          <div>
            <p className="section-kicker">{t("public.home.platform.eyebrow")}</p>
            <h2 id="platform-title">{t("public.home.platform.title")}</h2>
            <p>{t("public.home.platform.body")}</p>
          </div>
          <div className="product-panel">
            <p className="section-kicker">{t("public.home.product.eyebrow")}</p>
            <h3>{t("public.home.product.title")}</h3>
            <p>{t("public.home.product.body")}</p>
            <Link className="text-link" href="/services/variant">{t("public.services.variant.link")}</Link>
          </div>
        </section>

        <section className="feature-grid">
          <article>
            <b>{t("public.home.traceable.title")}</b>
            <p>{t("public.home.traceable.body")}</p>
          </article>
          <article>
            <b>{t("public.home.review.title")}</b>
            <p>{t("public.home.review.body")}</p>
          </article>
          <article>
            <b>{t("public.home.extend.title")}</b>
            <p>{t("public.home.extend.body")}</p>
          </article>
        </section>
      </main>
    </SiteShell>
  );
}
