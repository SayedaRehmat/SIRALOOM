"use client";

import Link from "next/link";
import { SiteShell } from "../../components/site-shell";
import { useLanguage } from "../../lib/i18n";

export default function Home() {
  const { language } = useLanguage();
  const label = (en: string, ar: string) => language === "ar" ? ar : language === "bilingual" ? `${en} · ${ar}` : en;
  const lifecycle = [
    ["Case intake", "استقبال الحالة"],
    ["VCF validation", "التحقق من VCF"],
    ["Normalization", "التطبيع"],
    ["Annotation", "التعليق"],
    ["Population", "بيانات السكان"],
    ["Evidence", "الأدلة"],
    ["ACMG assessment", "تقييم ACMG"],
    ["Human review", "المراجعة البشرية"],
    ["Reportability", "قابلية الإبلاغ"],
    ["Sign-out", "اعتماد التقرير"],
    ["Provenance & reanalysis", "سلسلة المصدر وإعادة التحليل"],
  ];

  return (
    <SiteShell showLanguageSwitcher>
      <main className="public-main">
        <section className="public-hero-v2">
          <div className="hero-copy-v2">
            <p className="eyebrow">{label("GENOMIC WORKFLOW SOFTWARE FOR LABORATORIES", "برمجيات سير العمل الجينومي للمختبرات")}</p>
            <h1>{label("One governed case record from VCF intake to reviewed report.", "سجل حالة محكوم واحد من إدخال VCF إلى التقرير المراجع.")}</h1>
            <p className="lead">{label(
              "Manage cases, specimens, files, analysis checkpoints, evidence, human review, reporting and reanalysis in one traceable workspace.",
              "أدر الحالات والعينات والملفات ونقاط حفظ التحليل والأدلة والمراجعة البشرية والتقارير وإعادة التحليل في مساحة عمل قابلة للتتبع."
            )}</p>
            <div className="actions">
              <Link className="button" href="/signup">{label("Request trial access", "طلب الوصول التجريبي")}</Link>
              <Link className="text-link" href="/services">{label("Explore the workflow", "استكشف سير العمل")} →</Link>
            </div>
            <p className="public-qualification-note">{label(
              "Software capability is not clinical validation. Each laboratory must qualify its deployment, resources and workflow before clinical use.",
              "قدرات البرمجيات لا تعني التحقق السريري. يجب على كل مختبر تأهيل النشر والموارد وسير العمل قبل الاستخدام السريري."
            )}</p>
          </div>

          <div className="workflow-console" aria-label={label("Illustrative workflow, synthetic data only", "سير عمل توضيحي ببيانات اصطناعية فقط")}>
            <div className="console-header">
              <span>{label("ILLUSTRATIVE CASE WORKFLOW", "سير عمل حالة توضيحي")}</span>
              <span className="console-status"><i />{label("Example only", "مثال فقط")}</span>
            </div>
            <div className="console-case">
              <div>
                <small>DEMO-CASE-001 · {label("Synthetic example", "مثال اصطناعي")}</small>
                <strong>{label("Germline variant analysis", "تحليل متغيرات وراثية")}</strong>
                <span>WES · GRCh38 · {label("No patient data", "لا توجد بيانات مرضى")}</span>
              </div>
              <b>VCF</b>
            </div>
            <div className="console-stage">
              <div className="stage-complete" /><span>{label("Validated", "تم التحقق")}</span><i>→</i>
              <div className="stage-active" /><span>{label("Analysis", "التحليل")}</span><i>→</i>
              <div className="stage-pending" /><span>{label("Review", "المراجعة")}</span>
            </div>
            <div className="console-grid">
              <div><small>{label("Workflow state", "حالة سير العمل")}</small><strong>{label("Checkpointed", "نقاط حفظ")}</strong></div>
              <div><small>{label("Evidence", "الأدلة")}</small><strong>{label("Source-linked", "مرتبطة بالمصدر")}</strong></div>
              <div><small>{label("Classification", "التصنيف")}</small><strong>{label("Reviewer required", "تتطلب مراجعاً")}</strong></div>
              <div><small>{label("Report", "التقرير")}</small><strong>{label("Pending sign-out", "بانتظار الاعتماد")}</strong></div>
            </div>
            <div className="console-footer"><span>{label("Resource versions", "إصدارات الموارد")}</span><strong>{label("Recorded per analysis", "مسجلة لكل تحليل")}</strong></div>
            <p className="console-disclaimer">{label("Illustrative interface, not a live patient case or a clinical result.", "واجهة توضيحية وليست حالة مريض حقيقية أو نتيجة سريرية.")}</p>
          </div>
        </section>

        <section className="public-section-v2 intro-section">
          <p className="section-kicker">{label("BUILT AROUND THE LABORATORY WORKFLOW", "مصمم حول سير عمل المختبر")}</p>
          <h2>{label("Make the case, the evidence and the decision traceable together.", "اربط الحالة والأدلة والقرار ضمن سجل قابل للتتبع.")}</h2>
          <p>{label(
            "Keep computational output separate from authorized human decisions, and preserve the context needed to review previous work.",
            "افصل المخرجات الحسابية عن القرارات البشرية المصرح بها، واحتفظ بالسياق اللازم لمراجعة العمل السابق."
          )}</p>
        </section>

        <section className="public-feature-grid-v2">
          <article><span>01</span><h3>{label("Workflow state", "حالة سير العمل")}</h3><p>{label("Persisted steps, artifacts and checkpoints are designed to support controlled retry and recovery. Validate failure handling in the target deployment.", "صُممت الخطوات والملفات ونقاط الحفظ المستمرة لدعم إعادة المحاولة والاستعادة المنضبطة. تحقّق من معالجة الأعطال في بيئة النشر المستهدفة.")}</p></article>
          <article><span>02</span><h3>{label("Human review", "المراجعة البشرية")}</h3><p>{label("Review evidence, document criterion decisions, retain classification history and keep reportability separate from pathogenicity.", "راجع الأدلة ووثّق قرارات المعايير واحتفظ بتاريخ التصنيف وافصل قابلية الإبلاغ عن إمراضية المتغير.")}</p></article>
          <article><span>03</span><h3>{label("Governed resources", "الموارد المحكومة")}</h3><p>{label("Record resource identity and versions, and require compatibility and laboratory approval rather than treating registry entries as automatically executable.", "سجّل هوية الموارد وإصداراتها، واشترط التوافق واعتماد المختبر بدلاً من اعتبار كل سجل مورداً قابلاً للتنفيذ تلقائياً.")}</p></article>
        </section>

        <section className="public-section-v2 product-section">
          <div><p className="section-kicker">{label("WORKSPACE", "مساحة العمل")}</p><h2>{label("A case-first operational view.", "واجهة تشغيل تتمحور حول الحالة.")}</h2><p>{label("Move from the case list to specimen and input files, then into analysis status, variant evidence, review decisions, reports and audit history.", "انتقل من قائمة الحالات إلى العينات والملفات، ثم إلى حالة التحليل وأدلة المتغيرات وقرارات المراجعة والتقارير وسجل التدقيق.")}</p></div>
          <div className="product-aside"><p className="section-kicker">{label("LABORATORY DEPLOYMENT", "نشر المختبر")}</p><p>{label("SIRALOOM can be installed with laboratory-controlled persistent storage, references, databases and worker infrastructure. Capacity limits, security, backup/restore and large-file performance must be measured and qualified on the lab's own systems.", "يمكن تثبيت SIRALOOM مع التخزين المستمر والمراجع وقواعد البيانات وبنية العاملين التي يتحكم بها المختبر. يجب قياس حدود السعة والأمان والنسخ الاحتياطي/الاستعادة وأداء الملفات الكبيرة وتأهيلها على أنظمة المختبر نفسه.")}</p><Link className="text-link" href="/services">{label("Deployment details", "تفاصيل النشر")} →</Link></div>
        </section>

        <section className="public-section-v2 lifecycle-section">
          <p className="section-kicker">{label("CASE LIFECYCLE", "دورة حياة الحالة")}</p>
          <div className="lifecycle-line">{lifecycle.map(([en, ar], index) => <span key={en}><b>{String(index + 1).padStart(2, "0")}</b>{label(en, ar)}</span>)}</div>
        </section>
      </main>
    </SiteShell>
  );
}
