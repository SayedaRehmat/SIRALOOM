"use client";

import Link from "next/link";
import { SiteShell } from "../../../../components/site-shell";
import { useLanguage } from "../../../../lib/i18n";

export default function Variant() {
  const { t } = useLanguage();
  const steps = [
    ["01", "public.variant.case"],
    ["02", "public.variant.validate"],
    ["03", "public.variant.normalize"],
    ["04", "public.variant.evidence"],
    ["05", "public.variant.review"],
    ["06", "public.variant.report"],
  ] as const;
  return (
    <SiteShell>
      <main className="content-page public-content">
        <p className="eyebrow">{t("public.variant.eyebrow")}</p>
        <h1>{t("public.variant.title")}</h1>
        <p className="lead">{t("public.variant.lead")}</p>
        <div className="process">
          {steps.map(([number, key]) => <div key={key}><span>{number}</span><strong>{t(key)}</strong></div>)}
        </div>
        <p className="quiet">{t("public.variant.note")}</p>
        <Link className="button" href="/signup">{t("public.variant.create")}</Link>
      </main>
    </SiteShell>
  );
}
