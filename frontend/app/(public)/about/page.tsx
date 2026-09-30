"use client";

import { SiteShell } from "../../../components/site-shell";
import { useLanguage } from "../../../lib/i18n";

export default function About() {
  const { t } = useLanguage();
  return (
    <SiteShell>
      <main className="content-page public-content">
        <p className="eyebrow">{t("public.about.eyebrow")}</p>
        <h1>{t("public.about.title")}</h1>
        <p className="lead">{t("public.about.lead")}</p>
        <section className="prose-grid">
          <article><span>01</span><h2>{t("public.about.core.title")}</h2><p>{t("public.about.core.body")}</p></article>
          <article><span>02</span><h2>{t("public.about.review.title")}</h2><p>{t("public.about.review.body")}</p></article>
        </section>
      </main>
    </SiteShell>
  );
}
