"use client";

import Link from "next/link";
import { SiteShell } from "../../components/site-shell";
import { useLanguage } from "../../lib/i18n";

export default function Home() {
  const { language } = useLanguage();
  const copy = language === "ar" ? {
    eyebrow: "منصة سير عمل جينومي",
    title: "سجل واحد للحالة من الإدخال إلى التقرير وإعادة التحليل.",
    lead: "SIRALOOM يربط الحالات والعينات والملفات والتحليل والأدلة والمراجعة والتقارير ضمن سير عمل مختبري قابل للتتبع.",
    access: "طلب الوصول", product: "استكشاف المنتج", panel: "سير عمل الحالة", status: "حالة نشطة",
    case: "CASE-02418", caseBody: "WES · GRCh38 · مراجعة جارية", analysis: "التحليل", evidence: "الأدلة", review: "المراجعة", report: "التقرير", reanalysis: "إعادة التحليل",
    workflowTitle: "سير العمل المتين", workflowBody: "تظل حالة التحليل ومراحلها ونقاط التوقف والملفات قابلة للاستئناف والتدقيق.",
    reviewTitle: "مراجعة بشرية", reviewBody: "المخرجات الحسابية تدعم القرار؛ يظل التصنيف السريري المصرح به ضمن مسؤولية المراجع المختص.",
    resourcesTitle: "موارد محكومة", resourcesBody: "الإصدارات والمراجع وقواعد البيانات مرتبطة بالتحليل حتى يمكن إعادة بناء النتيجة.",
    sectionTitle: "مصمم للعمل المختبري الفعلي", sectionBody: "إدارة الحالة، التحليل، تفسير المتغيرات، المراجعة، التقرير، وسجل provenance في مساحة عمل واحدة.",
    productTitle: "SIRALOOM Variant", productBody: "من إدخال VCF والتحقق والتطبيع إلى الأدلة والتصنيف والمراجعة والتقرير وإعادة التحليل.",
    deployTitle: "نشر داخل بنية المختبر", deployBody: "يمكن تشغيل مساحة العمل مع تخزين المختبر وموارده وسعة البنية التحتية الخاصة به، مع الاحتفاظ بإصدارات الموارد المستخدمة.",
    lifecycleTitle: "دورة الحالة", lifecycle: ["الحالة", "الإدخال", "التحليل", "التعليق", "السكان", "الأدلة", "ACMG", "المراجعة", "التقرير", "إعادة التحليل"]
  } : {
    eyebrow: "GENOMIC WORKFLOW PLATFORM",
    title: "One case record from intake to report and reanalysis.",
    lead: "SIRALOOM connects cases, specimens, files, analysis, evidence, review and reporting in a controlled laboratory workflow.",
    access: "Request access", product: "Explore product", panel: "Case workflow", status: "Active case",
    case: "CASE-02418", caseBody: "WES · GRCh38 · review in progress", analysis: "Analysis", evidence: "Evidence", review: "Review", report: "Report", reanalysis: "Reanalysis",
    workflowTitle: "Durable workflow", workflowBody: "Analysis state, checkpoints, gates and artifacts remain recoverable and auditable.",
    reviewTitle: "Human review", reviewBody: "Computational results support interpretation; authorized reviewers retain clinical decision authority.",
    resourcesTitle: "Governed resources", resourcesBody: "Reference, annotation, population and clinical-resource versions remain attached to the analysis.",
    sectionTitle: "Designed for laboratory operations", sectionBody: "Case management, analysis, variant interpretation, review, reporting and provenance in one workspace.",
    productTitle: "SIRALOOM Variant", productBody: "From VCF intake, validation and normalization through evidence, classification, review, reporting and reanalysis.",
    deployTitle: "Deploy within the laboratory", deployBody: "Run the workspace with laboratory-owned storage, resources and infrastructure capacity while preserving the resource versions used for each analysis.",
    lifecycleTitle: "Case lifecycle", lifecycle: ["Case", "Intake", "Analysis", "Annotation", "Population", "Evidence", "ACMG", "Review", "Report", "Reanalysis"]
  };

  return (
    <SiteShell showLanguageSwitcher>
      <main className="public-main">
        <section className="public-hero-v2">
          <div className="hero-copy-v2">
            <p className="eyebrow">{copy.eyebrow}</p>
            <h1>{copy.title}</h1>
            <p className="lead">{copy.lead}</p>
            <div className="actions"><Link className="button" href="/signup">{copy.access}</Link><Link className="text-link" href="/services">{copy.product} →</Link></div>
          </div>
          <div className="workflow-console" aria-label={copy.panel}>
            <div className="console-header"><span>{copy.panel}</span><span className="console-status"><i />{copy.status}</span></div>
            <div className="console-case"><div><small>{copy.case}</small><strong>BRCA1 hereditary cancer evaluation</strong><span>{copy.caseBody}</span></div><b>GRCh38</b></div>
            <div className="console-stage"><div className="stage-complete" /><span>{copy.analysis}</span><i>→</i><div className="stage-active" /><span>{copy.evidence}</span><i>→</i><div className="stage-pending" /><span>{copy.review}</span></div>
            <div className="console-grid"><div><small>{copy.analysis}</small><strong>Checkpointed</strong></div><div><small>{copy.evidence}</small><strong>Versioned</strong></div><div><small>{copy.review}</small><strong>Required</strong></div><div><small>{copy.report}</small><strong>Pending sign-out</strong></div></div>
            <div className="console-footer"><span>{copy.reanalysis}</span><strong>Change-aware case history</strong></div>
          </div>
        </section>

        <section className="public-section-v2 intro-section"><p className="section-kicker">SIRALOOM</p><h2>{copy.sectionTitle}</h2><p>{copy.sectionBody}</p></section>

        <section className="public-feature-grid-v2">
          <article><span>01</span><h3>{copy.workflowTitle}</h3><p>{copy.workflowBody}</p></article>
          <article><span>02</span><h3>{copy.reviewTitle}</h3><p>{copy.reviewBody}</p></article>
          <article><span>03</span><h3>{copy.resourcesTitle}</h3><p>{copy.resourcesBody}</p></article>
        </section>

        <section className="public-section-v2 product-section">
          <div><p className="section-kicker">PRODUCT</p><h2>{copy.productTitle}</h2><p>{copy.productBody}</p></div>
          <div className="product-aside"><p className="section-kicker">{copy.deployTitle}</p><p>{copy.deployBody}</p></div>
        </section>

        <section className="public-section-v2 lifecycle-section"><p className="section-kicker">{copy.lifecycleTitle}</p><div className="lifecycle-line">{copy.lifecycle.map((item, index) => <span key={item}><b>{String(index + 1).padStart(2, "0")}</b>{item}</span>)}</div></section>
      </main>
    </SiteShell>
  );
}
