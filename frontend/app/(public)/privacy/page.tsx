"use client";

import { SiteShell } from "../../../components/site-shell";
import { useLanguage } from "../../../lib/i18n";

export default function Privacy() {
  const { t } = useLanguage();
  return <SiteShell><main className="content-page public-content legal"><p className="eyebrow">{t("public.privacy.eyebrow")}</p><h1>{t("public.privacy.title")}</h1><p className="lead">{t("public.privacy.body")}</p></main></SiteShell>;
}
