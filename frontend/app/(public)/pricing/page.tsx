"use client";

import Link from "next/link";
import { SiteShell } from "../../../components/site-shell";
import { useLanguage } from "../../../lib/i18n";

export default function Pricing() {
  const { t, language } = useLanguage();
  const isArabic = language === "ar";

  const plans = isArabic
    ? [
        {
          number: "01",
          name: "أساسي",
          monthly: "$249",
          annual: "$2,490",
          audience: "للمختبرات التشخيصية الصغيرة",
          limits: ["مختبر واحد", "حتى 5 مستخدمين", "50 عينة تحليل شهرياً"],
          features: [
            "إدارة المؤسسة والمستخدمين والصلاحيات",
            "إنشاء الحالات وإدارة ملفات VCF",
            "سير عمل تفسير SNV وindel",
            "مراجعة الأدلة والمراجعة البشرية واعتماد التقارير",
            "طلبات إعادة التحليل وتتبع دورة حياتها",
            "سجلات التدقيق وتتبع المصدر",
            "دعم قياسي عبر البريد الإلكتروني",
          ],
        },
        {
          number: "02",
          name: "احترافي",
          monthly: "$599",
          annual: "$5,990",
          audience: "للمختبرات التشخيصية النامية",
          limits: ["مختبر واحد", "حتى 15 مستخدماً", "200 عينة تحليل شهرياً"],
          features: [
            "جميع مزايا الخطة الأساسية",
            "سير عمل قابل للتهيئة للمراجعة والاعتماد",
            "إدارة موسعة للأدلة وتتبع المصدر",
            "إدارة متقدمة لإعادة التحليل",
            "التقارير وسجلات التدقيق",
            "دعم ذو أولوية",
          ],
          featured: true,
        },
        {
          number: "03",
          name: "متقدم",
          monthly: "$1,199",
          annual: "$11,990",
          audience: "للمختبرات ذات أحجام العمل الكبيرة",
          limits: ["مختبر واحد", "حتى 30 مستخدماً", "600 عينة تحليل شهرياً"],
          features: [
            "جميع مزايا الخطة الاحترافية",
            "إعدادات متقدمة لسير العمل",
            "قوالب تقارير مخصصة",
            "إمكانية التكامل وواجهات API عند توفرها",
            "دعم فني موسع",
          ],
        },
      ]
    : [
        {
          number: "01",
          name: "Essential",
          monthly: "$249",
          annual: "$2,490",
          audience: "For small diagnostic laboratories",
          limits: ["1 laboratory", "Up to 5 users", "50 analysis samples/month"],
          features: [
            "Organization, user and access management",
            "Case creation and VCF case management",
            "SNV and indel interpretation workflow",
            "Evidence review, human review and controlled report sign-out",
            "Reanalysis request and lifecycle tracking",
            "Audit history and provenance",
            "Standard email support",
          ],
        },
        {
          number: "02",
          name: "Professional",
          monthly: "$599",
          annual: "$5,990",
          audience: "For growing diagnostic laboratories",
          limits: ["1 laboratory", "Up to 15 users", "200 analysis samples/month"],
          features: [
            "Everything in Essential",
            "Configurable review and approval workflows",
            "Enhanced evidence management and provenance",
            "Advanced reanalysis administration",
            "Reporting and audit history",
            "Priority support",
          ],
          featured: true,
        },
        {
          number: "03",
          name: "Advanced",
          monthly: "$1,199",
          annual: "$11,990",
          audience: "For higher-throughput laboratories",
          limits: ["1 laboratory", "Up to 30 users", "600 analysis samples/month"],
          features: [
            "Everything in Professional",
            "Advanced workflow configuration",
            "Custom report templates",
            "Integration and API access where available",
            "Extended technical support",
          ],
        },
      ];

  const copy = isArabic
    ? {
        eyebrow: "الأسعار",
        title: "ترخيص برمجيات المختبر، دون تكلفة البنية التحتية",
        lead: "توفر SIRALOOM منصة لإدارة سير العمل المخبري وتفسير المتغيرات الجينية، من إدارة المؤسسة والحالات إلى مراجعة الأدلة والتقارير والاعتماد وإعادة التحليل.",
        monthly: "شهرياً",
        annual: "سنوياً",
        annualNote: "السعر السنوي يعادل دفع 10 أشهر",
        limits: "حدود الخطة",
        enterprise: "المؤسسات وشبكات المختبرات",
        enterpriseBody: "ترخيص سنوي مخصص للمؤسسات متعددة المواقع، مع نطاق مستخدمين وحالات مخصص، ونشر محلي أو سحابة خاصة، وتكاملات ودعم وفق اتفاقية.",
        quote: "اطلب عرض سعر",
        contact: "تواصل مع المبيعات",
        deployment: "بنيتك التحتية. بياناتك. سير عملك.",
        customer: "يوفر المختبر ويدير",
        customerItems: ["الخوادم والمعالج والذاكرة وموارد الحوسبة", "التخزين والنسخ الاحتياطي", "نظام التشغيل وبيئة الحاويات والشبكة", "المراجع الجينومية وقواعد البيانات والتراخيص الخارجية المطلوبة"],
        vendor: "توفر SIRALOOM",
        vendorItems: ["ترخيص البرنامج ومكونات سير العمل المدعومة", "إدارة المؤسسات والمستخدمين والصلاحيات والحالات", "استقبال VCF وتفسير المتغيرات وإدارة الأدلة", "المراجعة البشرية والتقارير والاعتماد وسجلات التدقيق", "إدارة إعادة التحليل والتحديثات والدعم حسب الخطة"],
        usage: "ما المقصود بعينة التحليل؟",
        usageBody: "تُحتسب عينة تحليل واحدة لكل فرد يتم تحليل ملف VCF الخاص به. لذلك قد تستهلك حالة الثلاثي العائلي ثلاثة أرصدة عينات. إعادة تقييم الأدلة لحالة موجودة لا تُعد تلقائياً تحليلاً جديداً؛ أما إعادة تشغيل تحليل VCF من البداية فتستهلك رصيداً وفق سياسة الاستخدام.",
        addOn: "العينات الإضافية",
        addOnBody: "Essential: $3.50 للعينة · Professional: $2.50 للعينة · Advanced: $1.75 للعينة. تُحدد شروط شراء الأرصدة وصلاحيتها في اتفاقية الاشتراك.",
        implementation: "خدمات التنفيذ الاختيارية",
        implementationBody: "مساعدة التثبيت القياسي تبدأ من $750. التثبيت المتقدم والتهيئة يبدأان من $1,500. تنفيذ المؤسسات ومتعددة المواقع حسب عرض سعر.",
        exclusions: "غير مشمول في الاشتراك",
        exclusionsBody: "لا تشمل الأسعار الحوسبة أو التخزين أو النسخ الاحتياطي أو الاستضافة أو تسلسل FASTQ واستدعاء المتغيرات من القراءات الخام أو تراخيص قواعد البيانات الخارجية. كما لا تشمل تفسيراً طبياً بشرياً أو اعتماداً تنظيمياً أو تحققاً سريرياً لم تحصل عليه المنصة.",
        note: "الأسعار بالدولار الأمريكي. الضرائب، شروط الفوترة، حدود الملفات والأحجام المدعومة، والميزات المتاحة تخضع لاتفاقية الخطة وإصدار البرنامج المؤهل. لا تُعرض ميزة للبيع قبل إتاحتها واجتياز بوابة الإصدار ذات الصلة.",
        contactLine: "للاستفسارات وعروض المؤسسات: ",
      }
    : {
        eyebrow: "Pricing",
        title: "Laboratory software licensing. Infrastructure not included.",
        lead: "SIRALOOM is a laboratory genomic workflow and variant interpretation platform covering organization and access management, case processing, evidence review, reporting, sign-out, auditability and reanalysis.",
        monthly: "Monthly",
        annual: "Annual",
        annualNote: "Annual billing is equivalent to 10 monthly payments",
        limits: "Plan limits",
        enterprise: "Enterprise and laboratory networks",
        enterpriseBody: "Custom annual licensing for multi-site organizations, with negotiated user and case allowances, on-premises or customer-managed private-cloud deployment, integrations and support agreements.",
        quote: "Request a quotation",
        contact: "Contact sales",
        deployment: "Your infrastructure. Your data. Your genomic workflow.",
        customer: "The laboratory provides and manages",
        customerItems: ["Servers, CPU, memory and compute capacity", "Storage and backups", "Operating system, container runtime and network", "Reference genomes, databases and required third-party licences"],
        vendor: "SIRALOOM provides",
        vendorItems: ["Software licence and supported workflow components", "Organization, user, access and case management", "VCF intake, variant interpretation and evidence management", "Human review, reports, sign-out and audit history", "Reanalysis lifecycle, software updates and plan-based support"],
        usage: "What counts as an analysis sample?",
        usageBody: "One analysis sample is one individual whose VCF is processed. A trio therefore uses three sample credits. Evidence reassessment on an existing case is not automatically a new analysis; rerunning a VCF analysis from the beginning consumes a credit under the usage policy.",
        addOn: "Additional analysis samples",
        addOnBody: "Essential: $3.50/sample · Professional: $2.50/sample · Advanced: $1.75/sample. Credit purchase and expiry terms are defined in the subscription agreement.",
        implementation: "Optional implementation services",
        implementationBody: "Standard installation assistance from $750. Advanced installation and configuration from $1,500. Enterprise and multi-site implementation by quotation.",
        exclusions: "Not included in the subscription",
        exclusionsBody: "Compute, storage, backups, hosting, FASTQ sequencing or variant calling from raw reads, and third-party database licences are not included. Human medical interpretation, regulatory certification and clinical validation not achieved by the platform are also excluded.",
        note: "Prices are in USD. Taxes, billing terms, supported file-size and workload limits, and available features are governed by the plan agreement and qualified software release. Features are not offered for sale until available and through their applicable release gate.",
        contactLine: "For questions and enterprise quotations: ",
      };

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
          {plans.map((plan) => (
            <article className={plan.featured ? "pricing-card featured" : "pricing-card"} key={plan.number}>
              <span>{plan.number}</span>
              <h2>{plan.name}</h2>
              <p>{plan.audience}</p>
              <p><strong>{plan.monthly} / {copy.monthly}</strong></p>
              <p>{plan.annual} / {copy.annual}</p>
              <p className="quiet">{copy.annualNote}</p>
              <h3>{copy.limits}</h3>
              <ul>
                {plan.limits.map((item) => <li key={item}>{item}</li>)}
              </ul>
              <ul>
                {plan.features.map((item) => <li key={item}>{item}</li>)}
              </ul>
              <Link className={plan.featured ? "button" : "button secondary"} href="/contact">{copy.contact}</Link>
            </article>
          ))}
        </div>

        <section className="legal">
          <h2>{copy.enterprise}</h2>
          <p>{copy.enterpriseBody}</p>
          <Link className="button secondary" href="/contact">{copy.quote}</Link>
        </section>

        <section className="legal">
          <h2>{copy.deployment}</h2>
          <h3>{copy.customer}</h3>
          <ul>{copy.customerItems.map((item) => <li key={item}>{item}</li>)}</ul>
          <h3>{copy.vendor}</h3>
          <ul>{copy.vendorItems.map((item) => <li key={item}>{item}</li>)}</ul>
        </section>

        <section className="legal">
          <h2>{copy.usage}</h2>
          <p>{copy.usageBody}</p>
          <h3>{copy.addOn}</h3>
          <p>{copy.addOnBody}</p>
          <h3>{copy.implementation}</h3>
          <p>{copy.implementationBody}</p>
        </section>

        <section className="legal">
          <h2>{copy.exclusions}</h2>
          <p>{copy.exclusionsBody}</p>
        </section>

        <p className="quiet">{copy.note}</p>
        <p>{copy.contactLine}<a href="mailto:siralooms@gmail.com">siralooms@gmail.com</a></p>
      </main>
    </SiteShell>
  );
}
