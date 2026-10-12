"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { messages, type TranslationKey } from "./messages";

export type AppLanguage = "en" | "ar" | "bilingual";
export type AppDirection = "ltr" | "rtl";

const cookieKey = "siraloom.language";
const defaultLanguage: AppLanguage = "en";

function isAppLanguage(value: string | null): value is AppLanguage {
  return value === "en" || value === "ar" || value === "bilingual";
}

function directionFor(language: AppLanguage): AppDirection {
  return language === "ar" ? "rtl" : "ltr";
}

function readInitialLanguage(initialLanguage?: AppLanguage): AppLanguage {
  if (initialLanguage) return initialLanguage;
  return defaultLanguage;
}

function persistLanguage(language: AppLanguage) {
  document.cookie = `${cookieKey}=${encodeURIComponent(language)}; Path=/; Max-Age=31536000; SameSite=Lax`;
}

type CopyPair = readonly [string, string];

/*
 * Clinical-product language is deliberately short and operational. The API
 * and scientific identifiers remain untouched; only interface copy is mapped.
 */
const professionalCopy: Partial<Record<TranslationKey, CopyPair>> = {
  "public.brand.tagline": ["Genomic laboratory workflow", "سير عمل المختبر الجينومي"],
  "public.home.eyebrow": ["GENOMIC WORKFLOW PLATFORM", "منصة سير العمل الجينومي"],
  "public.home.title": ["One case record from intake to report and reanalysis.", "سجل حالة واحد من الإدخال إلى التقرير وإعادة التحليل."],
  "public.home.lead": ["SIRALOOM connects cases, specimens, files, analysis, evidence, review and reporting in a controlled laboratory workflow.", "يربط SIRALOOM الحالات والعينات والملفات والتحليل والأدلة والمراجعة والتقارير ضمن سير عمل مختبري مضبوط."],
  "public.home.platform.eyebrow": ["LABORATORY OPERATIONS", "عمليات المختبر"],
  "public.home.platform.title": ["A clinical workflow, not a collection of screens.", "سير عمل سريري متكامل، وليس مجموعة شاشات منفصلة."],
  "public.home.platform.body": ["The case remains the operational anchor for specimens, analyses, variants, evidence, review decisions, reports and subsequent reanalysis.", "تبقى الحالة المحور التشغيلي للعينات والتحليلات والمتغيرات والأدلة وقرارات المراجعة والتقارير وإعادة التحليل."],
  "public.home.product.eyebrow": ["PRODUCT", "المنتج"],
  "public.home.product.title": ["SIRALOOM Variant", "SIRALOOM Variant"],
  "public.home.product.body": ["VCF intake, validation, normalization, annotation, population context, evidence, ACMG assessment, review, reporting and reanalysis.", "إدخال VCF والتحقق والتطبيع والتعليق والسياق السكاني والأدلة وتقييم ACMG والمراجعة والتقارير وإعادة التحليل."],
  "public.home.lifecycle.eyebrow": ["CASE LIFECYCLE", "دورة الحالة"],
  "public.home.lifecycle.title": ["From intake to controlled reanalysis.", "من الإدخال إلى إعادة التحليل المنضبطة."],
  "public.home.lifecycle.body": ["Each stage retains its state, artifacts, resource versions and decision history so the laboratory can reconstruct the analysis.", "تحتفظ كل مرحلة بحالتها وملفاتها وإصدارات الموارد وسجل القرارات حتى يتمكن المختبر من إعادة بناء التحليل."],
  "public.home.lifecycle.steps": ["CASE · INTAKE · ANALYSIS · ANNOTATION · POPULATION · EVIDENCE · ACMG · REVIEW · REPORT · REANALYSIS", "الحالة · الإدخال · التحليل · التعليق · السكان · الأدلة · ACMG · المراجعة · التقرير · إعادة التحليل"],
  "public.home.traceable.title": ["Traceable by design", "قابل للتتبع من التصميم"],
  "public.home.traceable.body": ["Case context, artifacts, workflow state, evidence, reviewer actions and report versions remain linked.", "تبقى سياقات الحالة والملفات وحالة سير العمل والأدلة وإجراءات المراجع وإصدارات التقارير مترابطة."],
  "public.home.review.title": ["Human review", "المراجعة البشرية"],
  "public.home.review.body": ["Computational output supports interpretation; authorized reviewers retain decision authority and rationale.", "تدعم المخرجات الحسابية التفسير؛ ويحتفظ المراجعون المصرح لهم بسلطة القرار ومبرراته."],
  "public.home.extend.title": ["Governed resources", "موارد محكومة"],
  "public.home.extend.body": ["Reference, annotation, population and clinical-resource versions remain identifiable and reproducible.", "تبقى إصدارات المراجع وموارد التعليق والسكان والموارد السريرية محددة وقابلة لإعادة الإنتاج."],
  "public.services.eyebrow": ["PRODUCT", "المنتج"],
  "public.services.title": ["SIRALOOM for genomic laboratories.", "SIRALOOM للمختبرات الجينومية."],
  "public.services.variant.eyebrow": ["VARIANT WORKFLOW", "سير عمل المتغيرات"],
  "public.services.variant.title": ["A case-centered interpretation workspace.", "مساحة تفسير تتمحور حول الحالة."],
  "public.services.variant.body": ["Manage intake, durable analysis, evidence, review, reports and reanalysis without losing the relationship between them.", "إدارة الإدخال والتحليل المستمر والأدلة والمراجعة والتقارير وإعادة التحليل دون فقدان الترابط بينها."],
  "public.services.future": ["Additional laboratory workflows can be added without changing the platform's case and governance model.", "يمكن إضافة سير عمل مختبرية أخرى دون تغيير نموذج الحالة والحوكمة في المنصة."],
  "public.platform.caseTitle": ["Case-centered", "متمحور حول الحالة"],
  "public.platform.caseBody": ["The case links specimens, inputs, analyses, variants, evidence, review actions, reports and reanalysis.", "تربط الحالة العينات والمدخلات والتحليلات والمتغيرات والأدلة وإجراءات المراجعة والتقارير وإعادة التحليل."],
  "public.platform.workflowTitle": ["Durable workflow", "سير عمل مستمر"],
  "public.platform.workflowBody": ["Stages are persisted with checkpoints and can recover after worker or service interruption.", "تُحفظ المراحل مع نقاط تحقق ويمكن استعادتها بعد انقطاع العامل أو الخدمة."],
  "public.platform.governanceTitle": ["Governed interpretation", "تفسير محكوم"],
  "public.platform.governanceBody": ["Automated evidence remains distinct from authorized human classification and sign-out.", "تبقى الأدلة الآلية منفصلة عن التصنيف والمصادقة النهائية البشرية المصرح بها."],
  "public.about.eyebrow": ["ABOUT", "حول SIRALOOM"],
  "public.about.title": ["Software for controlled genomic laboratory work.", "برمجيات لسير العمل الجينومي المختبري المنضبط."],
  "public.about.lead": ["SIRALOOM is built around the laboratory case: one record connecting data, computation, evidence, review and reporting.", "بُني SIRALOOM حول الحالة المختبرية: سجل واحد يربط البيانات والحوسبة والأدلة والمراجعة والتقارير."],
  "public.about.core.title": ["Operational continuity", "استمرارية التشغيل"],
  "public.about.core.body": ["Analysis state, artifacts and workflow decisions remain persisted so interrupted work can resume without discarding completed work.", "تبقى حالة التحليل والملفات وقرارات سير العمل محفوظة بحيث يمكن استئناف العمل المتوقف دون فقدان العمل المكتمل."],
  "public.about.review.title": ["Clinical governance", "الحوكمة السريرية"],
  "public.about.review.body": ["Computational interpretation is presented as evidence for qualified review; final reporting remains under laboratory governance.", "يُعرض التفسير الحسابي كأدلة للمراجعة المختصة؛ وتبقى التقارير النهائية ضمن حوكمة المختبر."],
  "public.contact.eyebrow": ["LABORATORY DEPLOYMENT", "نشر المختبر"],
  "public.contact.title": ["Deploy SIRALOOM where the laboratory works.", "انشر SIRALOOM داخل بيئة المختبر."],
  "public.contact.lead": ["Discuss a laboratory deployment using its storage, compute, approved resources, access controls and operational policies.", "ناقش نشر SIRALOOM باستخدام تخزين المختبر وحوسبته وموارده المعتمدة وضوابط الوصول وسياساته التشغيلية."],
  "public.contact.note": ["Deployment configuration, resource qualification and clinical validation remain laboratory-controlled activities.", "تبقى إعدادات النشر وتأهيل الموارد والتحقق السريري أنشطة يتحكم بها المختبر."],
  "public.pricing.eyebrow": ["ACCESS", "الوصول"],
  "public.pricing.title": ["Choose the operating model that fits the laboratory.", "اختر نموذج التشغيل المناسب للمختبر."],
  "public.pricing.lead": ["Evaluate the workflow, then move to a laboratory-controlled deployment when required.", "قيّم سير العمل ثم انتقل إلى نشر يتحكم به المختبر عند الحاجة."],
  "public.pricing.trialTitle": ["Evaluation", "تقييم"],
  "public.pricing.trialBody": ["A controlled environment for evaluating the workflow and user experience.", "بيئة مضبوطة لتقييم سير العمل وتجربة المستخدم."],
  "public.pricing.trialCta": ["Request access", "طلب الوصول"],
  "public.pricing.labTitle": ["Laboratory deployment", "نشر المختبر"],
  "public.pricing.labBody": ["Run SIRALOOM with laboratory-owned infrastructure, storage and approved resources.", "شغّل SIRALOOM باستخدام بنية المختبر وتخزينه وموارده المعتمدة."],
  "public.pricing.labCta": ["Discuss deployment", "مناقشة النشر"],
  "public.pricing.enterpriseTitle": ["Institutional deployment", "النشر المؤسسي"],
  "public.pricing.enterpriseBody": ["Coordinate deployment, governance and resource management across a larger laboratory environment.", "نسّق النشر والحوكمة وإدارة الموارد ضمن بيئة مختبرية أكبر."],
  "public.pricing.enterpriseCta": ["Contact SIRALOOM", "تواصل مع SIRALOOM"],
  "public.pricing.note": ["Clinical validation, accreditation and authorized sign-out remain the responsibility of the laboratory and applicable jurisdiction.", "يبقى التحقق السريري والاعتماد والمصادقة النهائية من مسؤولية المختبر والجهة التنظيمية المختصة."],
  "auth.secure": ["SECURE WORKSPACE ACCESS", "دخول آمن إلى مساحة العمل"],
  "auth.login.title": ["Sign in to your laboratory workspace", "سجّل الدخول إلى مساحة عمل مختبرك"],
  "auth.login.body": ["Use your laboratory-approved account to continue a case, review interpretation, or access reports.", "استخدم حساب المختبر المعتمد لمتابعة حالة أو مراجعة التفسير أو الوصول إلى التقارير."],
  "workspace.eyebrow": ["GENOMIC CASE WORKSPACE", "مساحة عمل الحالة الجينومية"],
  "workspace.subtitle": ["Case record", "سجل الحالة"],
  "workspace.title": ["Case analysis", "تحليل الحالة"],
  "workspace.lead": ["Follow the analysis from input validation through interpretation, review, reporting and provenance.", "تابع التحليل من التحقق من الإدخال إلى التفسير والمراجعة والتقرير وسجل المصدر."],
  "workspace.startCase": ["New case", "حالة جديدة"],
  "workspace.caseIdentifier": ["Case identifier", "معرّف الحالة"],
  "workspace.clinicalIndication": ["Clinical indication", "الاستطباب السريري"],
  "workspace.vcfIntake": ["Variant input", "إدخال المتغيرات"],
  "workspace.inputPersisted": ["The input is stored before analysis begins.", "يُحفظ الإدخال قبل بدء التحليل."],
  "workspace.startAnalysis": ["Start analysis", "بدء التحليل"],
  "workspace.durableWorkflow": ["Analysis workflow", "سير عمل التحليل"],
  "workspace.checkpointPersisted": ["State and checkpoints are persisted for recovery.", "تُحفظ الحالة ونقاط التحقق للاستعادة."],
  "workspace.prioritizedVariants": ["Prioritized variants", "المتغيرات ذات الأولوية"],
  "workspace.completeReport": ["Complete variant dataset", "مجموعة المتغيرات الكاملة"],
  "workspace.allAnalyzedVariants": ["All analyzed variants", "جميع المتغيرات المحللة"],
  "workspace.variantEvidence": ["Variant evidence", "أدلة المتغير"],
  "workspace.humanDecisionWorkspace": ["Clinical review", "المراجعة السريرية"],
  "workspace.reviewPending": ["Review required", "المراجعة مطلوبة"],
  "workspace.automatedOutputProposed": ["Automated interpretation", "التفسير الآلي"],
  "workspace.finalReport": ["Final report", "التقرير النهائي"],
  "workspace.noReportGenerated": ["No report yet", "لا يوجد تقرير بعد"],
  "workspace.reportPending": ["Report follows authorized review and sign-out.", "يأتي التقرير بعد المراجعة والمصادقة المصرح بهما."],
  "workspace.caseTimeline": ["Case history", "سجل الحالة"],
  "workspace.auditReconstructable": ["Workflow, evidence, resource and reviewer events are retained in the case record.", "تُحفظ أحداث سير العمل والأدلة والموارد والمراجعين في سجل الحالة."],
  "workspace.exportHistory": ["Export case record", "تصدير سجل الحالة"],
  "workspace.backendConnected": ["Service connected", "الخدمة متصلة"],
  "workspace.connectionUnavailable": ["Service unavailable", "الخدمة غير متاحة"],
  "workspace.analysisQueued": ["Analysis queued", "تم وضع التحليل في قائمة الانتظار"],
  "workspace.analysisStartFailed": ["Analysis could not be started", "تعذر بدء التحليل"],
  "workspace.reportFinalized": ["Report finalized", "تم اعتماد التقرير"],
  "workspace.errorLoadCase": ["Unable to load the case record.", "تعذر تحميل سجل الحالة."],
  "workspace.errorCompleteReport": ["Unable to load the variant dataset.", "تعذر تحميل مجموعة المتغيرات."],
  "resources.eyebrow": ["RESOURCE GOVERNANCE", "حوكمة الموارد"],
  "resources.title": ["Approved scientific resources", "الموارد العلمية المعتمدة"],
  "resources.lead": ["Register, qualify, approve and activate resource versions used by laboratory analyses.", "سجّل وأهّل واعتمد وفعّل إصدارات الموارد المستخدمة في تحليلات المختبر."],
  "resources.register": ["Register resource", "تسجيل مورد"],
  "resources.registerHelp": ["Create a resource record with its version, build, access method, checksum and execution contract.", "أنشئ سجل المورد مع الإصدار والبناء وطريقة الوصول والتحقق وعقد التنفيذ."],
  "resources.catalog": ["Resource catalog", "دليل الموارد"],
  "resources.pendingApprovals": ["Approval queue", "قائمة الاعتماد"],
  "resources.lifecycleNote": ["Register → stage and verify → qualify → approve → activate → bind to an analysis profile.", "تسجيل ← تجهيز والتحقق ← التأهيل ← الاعتماد ← التفعيل ← الربط بملف التحليل."],
  "resources.stagingGap": ["A resource is not executable until its required staging and verification record is complete.", "لا يصبح المورد قابلاً للتنفيذ حتى يكتمل سجل التجهيز والتحقق المطلوب."],
  "resources.candidateOnly": ["Candidate resource", "مورد مرشح"],
  "resources.sourceExecutionMetadata": ["Execution contract", "عقد التنفيذ"],
  "resources.sourceExecutionHelp": ["Defines how SIRALOOM locates, invokes and validates this resource.", "يحدد كيفية وصول SIRALOOM إلى المورد وتشغيله والتحقق من مخرجاته."],
  "workspace.preflightTitle": ["Preflight", "الفحص المسبق"],
  "workspace.preflightReady": ["Ready to run", "جاهز للتشغيل"],
  "workspace.preflightBlocked": ["Blocked before execution", "محظور قبل التنفيذ"],
  "workspace.preflightDetails": ["Checks capacity, required resources and analysis prerequisites before work starts.", "يفحص السعة والموارد المطلوبة ومتطلبات التحليل قبل بدء العمل."],
  "workspace.capacityPreflight": ["Storage preflight", "الفحص المسبق للتخزين"],
  "workspace.capacityEstimate": ["Estimated storage requirement", "متطلبات التخزين المقدرة"],
  "workspace.availableStorage": ["Available storage", "التخزين المتاح"],
  "workspace.totalStorage": ["Total storage", "إجمالي التخزين"],
  "workspace.storageCapacityIssue": ["Insufficient storage capacity", "سعة التخزين غير كافية"],
  "resources.storageCapacity": ["Storage capacity", "سعة التخزين"],
  "resources.totalStorage": ["Total", "الإجمالي"],
  "resources.usedStorage": ["Used", "المستخدم"],
  "resources.freeStorage": ["Free", "المتاح"],
  "resources.storageWritable": ["Writable", "قابل للكتابة"],
};

export function getMessage(language: AppLanguage, key: TranslationKey): string {
  const override = professionalCopy[key];
  const english = override?.[0] ?? messages.en[key] ?? key;
  const arabic = override?.[1] ?? messages.ar[key] ?? english;
  if (language === "en") return english;
  if (language === "ar") return arabic;
  return `${english} · ${arabic}`;
}

type LanguageContextValue = {
  language: AppLanguage;
  direction: AppDirection;
  setLanguage: (language: AppLanguage) => void;
  t: (key: TranslationKey) => string;
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({
  children,
  initialLanguage,
}: {
  children: ReactNode;
  initialLanguage?: AppLanguage;
}) {
  const [language, setLanguageState] = useState<AppLanguage>(() => readInitialLanguage(initialLanguage));

  useEffect(() => {
    const direction = directionFor(language);
    document.documentElement.lang = language === "ar" ? "ar" : "en";
    document.documentElement.dir = direction;
    document.documentElement.dataset.language = language;
    document.documentElement.dataset.direction = direction;
    persistLanguage(language);
  }, [language]);

  const value = useMemo<LanguageContextValue>(
    () => ({
      language,
      direction: directionFor(language),
      setLanguage: setLanguageState,
      t: (key) => getMessage(language, key),
    }),
    [language],
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
  const context = useContext(LanguageContext);
  if (!context) throw new Error("useLanguage must be used within LanguageProvider");
  return context;
}
