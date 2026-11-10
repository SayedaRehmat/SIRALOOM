"use client";

import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";
import { useLanguage } from "../../../lib/i18n";

export default function Pricing() {
  const { t, language } = useLanguage();
  const isArabic = language === "ar";
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
            <Link className="button" href="/signup">{t("public.pricing.trialCta")}</Link>
          </article>
          <article className="pricing-card">
            <span>02</span>
            <h2>{t("public.pricing.labTitle")}</h2>
            <p>{t("public.pricing.labBody")}</p>
            <p><strong>{isArabic ? "عرض سعر مخصص" : "Custom quotation"}</strong></p>
            <Link className="button secondary" href="/contact">{t("public.pricing.labCta")}</Link>
          </article>
          <article className="pricing-card">
            <span>03</span>
            <h2>{t("public.pricing.enterpriseTitle")}</h2>
            <p>{t("public.pricing.enterpriseBody")}</p>
            <p><strong>{isArabic ? "عرض سعر مخصص" : "Custom quotation"}</strong></p>
            <Link className="button secondary" href="/contact">{t("public.pricing.enterpriseCta")}</Link>
          </article>
        </div>
        <section className="legal">
          <h2>{isArabic ? "كيف يتم تحديد السعر؟" : "How pricing is determined"}</h2>
          <p>{isArabic
            ? "تُقدَّم عروض الأسعار قبل الشراء، بناءً على نموذج النشر (سحابي أو محلي)، وعدد المختبرات والمستخدمين، وحجم التحليل والتخزين والحوسبة، والتكاملات ومستوى الدعم المطلوب."
            : "We provide a written quotation before purchase. Pricing is based on deployment model (hosted or on-premises), number of laboratories and users, analysis volume, storage and compute requirements, integrations, and support level."}</p>
          <p>{isArabic
            ? "للحصول على عرض سعر أو مناقشة نطاق النشر، تواصل معنا عبر البريد الإلكتروني أو صفحة التواصل."
            : "Request a quotation or discuss deployment scope through our contact page or email."} <a href="mailto:siralooms@gmail.com">siralooms@gmail.com</a></p>
        </section>
        <p className="quiet">{t("public.pricing.note")}</p>
      </main>
    </SiteShell>
  );
}
