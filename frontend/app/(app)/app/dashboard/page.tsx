import Link from "next/link";
import { useLanguage } from "../../../../lib/i18n";

export default function Dashboard() {
  const { t } = useLanguage();

  return (
    <>
      <p className="eyebrow">{t("dashboard.eyebrow")}</p>
      <h1>{t("dashboard.title")}</h1>
      <p className="lead">{t("dashboard.lead")}</p>
      <div className="feature-grid">
        <article><b>{t("dashboard.cases.title")}</b><p>{t("dashboard.cases.body")}</p><Link href="/app/cases">{t("dashboard.cases.link")}</Link></article>
        <article><b>{t("dashboard.variant.title")}</b><p>{t("dashboard.variant.body")}</p><Link href="/app/workspace">{t("dashboard.variant.link")}</Link></article>
        <article><b>{t("dashboard.review.title")}</b><p>{t("dashboard.review.body")}</p><Link href="/app/review">{t("dashboard.review.link")}</Link></article>
      </div>
    </>
  );
}
