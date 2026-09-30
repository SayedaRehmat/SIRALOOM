"use client";

import Link from "next/link";
import { SiteShell } from "../../components/site-shell";
import { useLanguage } from "../../lib/i18n";

export default function Home() {
  const { t } = useLanguage();
  const steps = t("public.home.lifecycle.steps").split(" · ");

  return (
    <SiteShell showLanguageSwitcher>
      <main>
        <section className="hero public-hero">
          <div className="hero-copy">
            <p className="eyebrow">{t("public.home.eyebrow")}</p>
            <h1>{t("public.home.title")}</h1>
            <p className="lead">{t("public.home.lead")}</p>
            <div className="actions">
              <Link className="button" href="/signup">{t("public.startTrial")}</Link>
              <Link className="text-link" href="/services">{t("public.services")}</Link>
            </div>
          </div>

          <div className="hero-visual" aria-label={t("public.home.product.title")}>
            <div className="workflow-board">
              <div className="workflow-board-top">
                <span>{t("public.home.product.eyebrow")}</span>
                <span className="workflow-status">{t("public.home.review.title")}</span>
              </div>

              <div className="workflow-case">
                <div className="workflow-case-meta">
                  <span>{steps[0] ?? "CASE"}</span>
                  <span>GRCh38</span>
                </div>
                <strong>{t("public.home.platform.caseTitle")}</strong>
                <small>{t("public.home.platform.caseBody")}</small>
              </div>

              <div className="workflow-track" aria-hidden="true">
                <span /><span /><span /><span />
              </div>

              <div className="workflow-node-grid">
                <div className="workflow-node"><span>{steps[1] ?? "ANALYSIS"}</span><strong>{t("public.home.platform.workflowTitle")}</strong></div>
                <div className="workflow-node"><span>{steps[3] ?? "EVIDENCE"}</span><strong>{t("public.home.platform.governanceTitle")}</strong></div>
                <div className="workflow-node"><span>{steps[5] ?? "REVIEW"}</span><strong>{t("public.home.review.title")}</strong></div>
                <div className="workflow-node"><span>{steps[6] ?? "REPORT"}</span><strong>{t("public.home.product.title")}</strong></div>
              </div>

              <div className="workflow-reanalysis">
                <span>{steps[steps.length - 1] ?? "REANALYSIS"}</span>
                <strong>{t("public.home.lifecycle.title")}</strong>
              </div>
            </div>
          </div>
        </section>

        <section className="home-section home-platform" aria-labelledby="platform-title">
          <div className="section-intro">
            <p className="section-kicker">{t("public.home.platform.eyebrow")}</p>
            <h2 id="platform-title">{t("public.home.platform.title")}</h2>
            <p>{t("public.home.platform.body")}</p>
          </div>
          <div className="platform-principles">
            <article><span>01</span><h3>{t("public.platform.caseTitle")}</h3><p>{t("public.platform.caseBody")}</p></article>
            <article><span>02</span><h3>{t("public.platform.workflowTitle")}</h3><p>{t("public.platform.workflowBody")}</p></article>
            <article><span>03</span><h3>{t("public.platform.governanceTitle")}</h3><p>{t("public.platform.governanceBody")}</p></article>
          </div>
        </section>

        <section className="home-section home-product" aria-labelledby="product-title">
          <div className="product-panel product-panel-large">
            <div>
              <p className="section-kicker">{t("public.home.product.eyebrow")}</p>
              <h2 id="product-title">{t("public.home.product.title")}</h2>
              <p>{t("public.home.product.body")}</p>
            </div>
            <Link className="button secondary" href="/services/variant">{t("public.services.variant.link")}</Link>
          </div>
        </section>

        <section className="home-section home-lifecycle" aria-labelledby="lifecycle-title">
          <div className="section-intro">
            <p className="section-kicker">{t("public.home.lifecycle.eyebrow")}</p>
            <h2 id="lifecycle-title">{t("public.home.lifecycle.title")}</h2>
            <p>{t("public.home.lifecycle.body")}</p>
          </div>
          <div className="workflow-strip" aria-label={t("public.home.lifecycle.steps")}>
            {steps.map((step, index) => (
              <span key={step}><b>{String(index + 1).padStart(2, "0")}</b>{step}</span>
            ))}
          </div>
        </section>

        <section className="feature-grid public-principles">
          <article><span>01</span><b>{t("public.home.traceable.title")}</b><p>{t("public.home.traceable.body")}</p></article>
          <article><span>02</span><b>{t("public.home.review.title")}</b><p>{t("public.home.review.body")}</p></article>
          <article><span>03</span><b>{t("public.home.extend.title")}</b><p>{t("public.home.extend.body")}</p></article>
        </section>
      </main>
    </SiteShell>
  );
}
