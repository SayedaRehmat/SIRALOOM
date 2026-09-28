export type CatalogLanguage = "en" | "ar";


/**
 * SIRALOOM application message catalog.
 *
 * Message IDs are stable semantic identifiers. Scientific data, identifiers,
 * API payloads, evidence text, and user-entered clinical content are never
 * passed through this catalog automatically.
 */
export type TranslationKey =
  | "app.workspace"
  | "app.governance"
  | "nav.dashboard"
  | "nav.cases"
  | "nav.variantWorkspace"
  | "nav.reviewQueue"
  | "nav.reports"
  | "nav.audit"
  | "nav.settings"
  | "nav.signOut"
  | "language.label"
  | "language.english"
  | "language.arabic"
  | "language.bilingual"
  | "session.checking"
  | "development.notice"
  | "dashboard.eyebrow"
  | "dashboard.title"
  | "dashboard.lead"
  | "dashboard.cases.title"
  | "dashboard.cases.body"
  | "dashboard.cases.link"
  | "dashboard.variant.title"
  | "dashboard.variant.body"
  | "dashboard.variant.link"
  | "dashboard.review.title"
  | "dashboard.review.body"
  | "dashboard.review.link"
  | "settings.eyebrow"
  | "settings.title"
  | "settings.lead"
  | "settings.identity"
  | "settings.currentSession"
  | "settings.email"
  | "settings.role"
  | "settings.userId"
  | "settings.organization"
  | "settings.entitlement"
  | "settings.loadingSession"
  | "settings.service"
  | "settings.backendConnection"
  | "settings.api"
  | "settings.health"
  | "settings.serverControlled"
  | "settings.activeContext"
  | "settings.browserContext"
  | "settings.caseId"
  | "settings.analysisId"
  | "settings.contextNote"
  | "settings.unableToLoad"
  | "public.about"
  | "public.services"
  | "public.contact"
  | "public.signIn"
  | "public.startTrial"
  | "public.privacy"
  | "public.terms"
  | "public.home.eyebrow"
  | "public.home.title"
  | "public.home.lead"
  | "public.home.traceable.title"
  | "public.home.traceable.body"
  | "public.home.review.title"
  | "public.home.review.body"
  | "public.home.extend.title"
  | "public.home.extend.body"
  | "public.about.eyebrow"
  | "public.about.title"
  | "public.about.lead"
  | "public.about.core.title"
  | "public.about.core.body"
  | "public.about.review.title"
  | "public.about.review.body"
  | "public.services.eyebrow"
  | "public.services.title"
  | "public.services.variant.eyebrow"
  | "public.services.variant.title"
  | "public.services.variant.body"
  | "public.services.variant.link"
  | "public.services.future"
  | "public.variant.eyebrow"
  | "public.variant.title"
  | "public.variant.lead"
  | "public.variant.case"
  | "public.variant.validate"
  | "public.variant.normalize"
  | "public.variant.evidence"
  | "public.variant.review"
  | "public.variant.report"
  | "public.variant.note"
  | "public.variant.create"
  | "public.contact.eyebrow"
  | "public.contact.title"
  | "public.contact.lead"
  | "public.contact.note"
  | "public.privacy.eyebrow"
  | "public.privacy.title"
  | "public.privacy.body"
  | "public.terms.eyebrow"
  | "public.terms.title"
  | "public.terms.body"
  | "auth.secure"
  | "auth.login.title"
  | "auth.signup.trialTitle"
  | "auth.signup.orgTitle"
  | "auth.login.body"
  | "auth.signup.trialBody"
  | "auth.signup.orgBody"
  | "auth.google"
  | "auth.or"
  | "auth.email"
  | "auth.password"
  | "auth.working"
  | "auth.signIn"
  | "auth.startTrial"
  | "auth.createAccount"
  | "auth.resetPassword"
  | "auth.newUser"
  | "auth.startFreeTrial"
  | "auth.haveAccount"
  | "auth.firebaseMissing"
  | "auth.failed"
  | "auth.enterEmail"
  | "auth.resetSent"
  | "auth.resetFailed"
  | "auth.googleFailed"
  | "auth.orgSwitch"
  | "onboarding.secure"
  | "onboarding.trialEyebrow"
  | "onboarding.orgEyebrow"
  | "onboarding.trialTitle"
  | "onboarding.orgTitle"
  | "onboarding.trialBody"
  | "onboarding.orgBody"
  | "onboarding.labName"
  | "onboarding.optional"
  | "onboarding.verifyBody"
  | "onboarding.checking"
  | "onboarding.verified"
  | "onboarding.resend"
  | "onboarding.create"
  | "onboarding.createOrg"
  | "onboarding.creating"
  | "onboarding.signOut"
  | "onboarding.returnSignIn"
  | "onboarding.accessRequired"
  | "onboarding.signInFirst"
  | "onboarding.firebaseMissing"
  | "onboarding.verifySent"
  | "onboarding.notVerified"
  | "onboarding.createFailed"
  | "workflow.case"
  | "workflow.specimen"
  | "workflow.variantFile"
  | "workflow.index"
  | "workflow.review"
  | "workflow.inputValidation"
  | "workflow.normalization"
  | "workflow.annotation"
  | "workflow.population"
  | "workflow.evidence"
  | "workflow.acmg"
  | "workflow.humanReview"
  | "workflow.report"
  | "workflow.caseHistory"
  | "reports.validationDisclaimer";


export const messages: Record<CatalogLanguage, Record<TranslationKey, string>> = {
  en: {
    "app.workspace": "WORKSPACE",
    "app.governance": "GOVERNANCE",
    "nav.dashboard": "Dashboard",
    "nav.cases": "Cases",
    "nav.variantWorkspace": "Variant workspace",
    "nav.reviewQueue": "Review queue",
    "nav.reports": "Reports",
    "nav.audit": "Audit",
    "nav.settings": "Settings",
    "nav.signOut": "Sign out",
    "language.label": "Language",
    "language.english": "English",
    "language.arabic": "Arabic",
    "language.bilingual": "Bilingual",
    "session.checking": "Checking secure session…",
    "development.notice": "Development mode: Firebase client configuration is absent. Production requires Firebase authentication and server-side membership provisioning.",
    "dashboard.eyebrow": "DASHBOARD",
    "dashboard.title": "Laboratory workspace",
    "dashboard.lead": "Start with a case, then use the existing Variant workspace to inspect durable workflow state.",
    "dashboard.cases.title": "Cases",
    "dashboard.cases.body": "Case-centered intake and longitudinal analysis history.",
    "dashboard.cases.link": "Open cases →",
    "dashboard.variant.title": "Variant service",
    "dashboard.variant.body": "Existing implementation workspace for analysis, review, reports, and audit.",
    "dashboard.variant.link": "Open workspace →",
    "dashboard.review.title": "Clinical review",
    "dashboard.review.body": "Prioritized interpretation queue with evidence-linked ACMG review and versioned decisions.",
    "dashboard.review.link": "Open review queue →",
    "settings.eyebrow": "GOVERNANCE · CONFIGURATION",
    "settings.title": "Settings",
    "settings.lead": "Authenticated workspace identity, entitlement, service connection, and active workflow context.",
    "settings.identity": "IDENTITY",
    "settings.currentSession": "Current session",
    "settings.email": "Email",
    "settings.role": "Role",
    "settings.userId": "User ID",
    "settings.organization": "Organization",
    "settings.entitlement": "Entitlement",
    "settings.loadingSession": "Loading authenticated session…",
    "settings.service": "SERVICE",
    "settings.backendConnection": "Backend connection",
    "settings.api": "API",
    "settings.health": "Health",
    "settings.serverControlled": "Scientific resources and workflow configuration remain server-controlled. This page does not expose unsafe client-side overrides.",
    "settings.activeContext": "ACTIVE CONTEXT",
    "settings.browserContext": "Browser workflow context",
    "settings.caseId": "Case ID",
    "settings.analysisId": "Analysis ID",
    "settings.contextNote": "Selecting a case from the Cases registry updates this context automatically.",
    "settings.unableToLoad": "Unable to load settings.",
    "public.about": "About",
    "public.services": "Services",
    "public.contact": "Contact",
    "public.signIn": "Sign in",
    "public.startTrial": "Start Free Trial",
    "public.privacy": "Privacy",
    "public.terms": "Terms",
    "public.home.eyebrow": "GENOMIC INTELLIGENCE PLATFORM",
    "public.home.title": "Evidence-connected workflows for genomic laboratories.",
    "public.home.lead": "SIRALOOM is building extensible infrastructure that connects case intake, genomic evidence, human review, reporting, and transparent computational history.",
    "public.home.traceable.title": "Traceable by design",
    "public.home.traceable.body": "Artifacts, evidence, decisions, resources, and reports preserve their history.",
    "public.home.review.title": "Built for review",
    "public.home.review.body": "Computational observations remain distinct from clinical interpretation.",
    "public.home.extend.title": "Designed to extend",
    "public.home.extend.body": "Variant is the first service on a stable platform core—not an isolated tool.",
    "public.about.eyebrow": "ABOUT SIRALOOM",
    "public.about.title": "Infrastructure for thoughtful genomic interpretation.",
    "public.about.lead": "We are creating an extensible platform for laboratories that need scientific traceability, connected evidence, and durable workflows from case intake through reporting.",
    "public.about.core.title": "Platform core first",
    "public.about.core.body": "Identity, cases, artifacts, workflow state, evidence, review, reporting, and audit are shared foundations for current and future scientific services.",
    "public.about.review.title": "Human review remains central",
    "public.about.review.body": "SIRALOOM supports experts with transparent computational context. It does not replace clinical judgment or make claims of clinical certification.",
    "public.services.eyebrow": "SERVICES",
    "public.services.title": "Scientific services on a shared laboratory platform.",
    "public.services.variant.eyebrow": "SERVICE 01",
    "public.services.variant.title": "SIRALOOM Variant",
    "public.services.variant.body": "VCF interpretation workflows with validation, normalization, evidence integration, ACMG-aware assessment, review, reporting, and provenance.",
    "public.services.variant.link": "View service →",
    "public.services.future": "Future services may cover CNV, SV, RNA, somatic analysis, pharmacogenomics, phenotype, and reanalysis through the same trusted platform core.",
    "public.variant.eyebrow": "SIRALOOM VARIANT",
    "public.variant.title": "From VCF intake to reviewable, auditable interpretation.",
    "public.variant.lead": "A case-centered service designed to preserve original inputs, workflow context, resource provenance, reviewer decisions, and report history.",
    "public.variant.case": "Case",
    "public.variant.validate": "Validate",
    "public.variant.normalize": "Normalize",
    "public.variant.evidence": "Evidence",
    "public.variant.review": "Review",
    "public.variant.report": "Report",
    "public.variant.note": "External resources and scientific outputs remain configuration-dependent and require laboratory validation for intended use.",
    "public.variant.create": "Create account",
    "public.contact.eyebrow": "CONTACT",
    "public.contact.title": "Talk with the SIRALOOM team.",
    "public.contact.lead": "For platform, laboratory workflow, and implementation enquiries, contact your SIRALOOM representative.",
    "public.contact.note": "A contact-delivery service is not configured in this environment; no form submissions are collected here.",
    "public.privacy.eyebrow": "PRIVACY",
    "public.privacy.title": "Privacy principles",
    "public.privacy.body": "SIRALOOM is designed so laboratory data access is tenant-scoped and subject to authenticated authorization. Deploying organizations remain responsible for configuring access, retention, and regulatory obligations appropriate to their use.",
    "public.terms.eyebrow": "TERMS",
    "public.terms.title": "Use of SIRALOOM",
    "public.terms.body": "SIRALOOM is a genomic workflow and decision-support platform. It is not represented by this software as clinically validated, certified, or a replacement for qualified professional review.",
    "auth.secure": "SECURE ACCESS",
    "auth.login.title": "Sign in to your workspace",
    "auth.signup.trialTitle": "Start your SIRALOOM trial",
    "auth.signup.orgTitle": "Create your SIRALOOM account",
    "auth.login.body": "Use your laboratory-approved account.",
    "auth.signup.trialBody": "No payment method required. Your workspace is created automatically once you verify your identity.",
    "auth.signup.orgBody": "Your organization workspace is created automatically once you verify your identity.",
    "auth.google": "Continue with Google",
    "auth.or": "or",
    "auth.email": "Email",
    "auth.password": "Password",
    "auth.working": "Working…",
    "auth.signIn": "Sign in",
    "auth.startTrial": "Start Free Trial",
    "auth.createAccount": "Create account",
    "auth.resetPassword": "Reset password",
    "auth.newUser": "New to SIRALOOM?",
    "auth.startFreeTrial": "Start a free trial",
    "auth.haveAccount": "Already have an account?",
    "auth.firebaseMissing": "Firebase is not configured for this deployment.",
    "auth.failed": "Authentication could not be completed.",
    "auth.enterEmail": "Enter your email address first.",
    "auth.resetSent": "Password-reset email sent.",
    "auth.resetFailed": "Unable to send reset email.",
    "auth.googleFailed": "Google sign-in could not be completed.",
    "auth.orgSwitch": "Setting up a production laboratory account instead?",
    "onboarding.secure": "SECURE ACCESS REQUIRED",
    "onboarding.trialEyebrow": "SIRALOOM FREE TRIAL",
    "onboarding.orgEyebrow": "ORGANIZATION ONBOARDING",
    "onboarding.trialTitle": "Your trial workspace is ready to be created",
    "onboarding.orgTitle": "Set up your laboratory workspace",
    "onboarding.trialBody": "SIRALOOM will automatically create your private trial workspace. No payment method is required.",
    "onboarding.orgBody": "SIRALOOM will create the organization and assign you the initial administrator role server-side.",
    "onboarding.labName": "Laboratory name",
    "onboarding.optional": "optional",
    "onboarding.verifyBody": "We need your verified email before creating the workspace. Check your inbox for the Firebase verification email.",
    "onboarding.checking": "Checking…",
    "onboarding.verified": "I’ve verified my email",
    "onboarding.resend": "Resend verification email",
    "onboarding.create": "Start Free Trial",
    "onboarding.createOrg": "Create organization",
    "onboarding.creating": "Creating workspace…",
    "onboarding.signOut": "Sign out",
    "onboarding.returnSignIn": "Return to sign in",
    "onboarding.accessRequired": "Secure access required",
    "onboarding.signInFirst": "Please sign in before starting your SIRALOOM workspace.",
    "onboarding.firebaseMissing": "Firebase is not configured for this deployment.",
    "onboarding.verifySent": "Verification email sent.",
    "onboarding.notVerified": "Your email is not verified yet. Open the Firebase verification email and try again.",
    "onboarding.createFailed": "Unable to create your SIRALOOM workspace.",
    "workflow.case": "Case",
    "workflow.specimen": "Specimen",
    "workflow.variantFile": "Variant file",
    "workflow.index": "Index",
    "workflow.review": "Review",
    "workflow.inputValidation": "Input validation",
    "workflow.normalization": "Normalization",
    "workflow.annotation": "Annotation",
    "workflow.population": "Population context",
    "workflow.evidence": "Evidence",
    "workflow.acmg": "ACMG assessment",
    "workflow.humanReview": "Human review",
    "workflow.report": "Report",
    "workflow.caseHistory": "Case history",
    "reports.validationDisclaimer": "SIRALOOM software validation is distinct from clinical laboratory validation, accreditation, or regulatory authorization. Release remains subject to the laboratory's qualified signatory, policies, and jurisdictional requirements.",
  },
  ar: {
    "app.workspace": "مساحة العمل",
    "app.governance": "الحوكمة",
    "nav.dashboard": "لوحة المعلومات",
    "nav.cases": "الحالات",
    "nav.variantWorkspace": "مساحة تحليل المتغيرات",
    "nav.reviewQueue": "قائمة المراجعة",
    "nav.reports": "التقارير",
    "nav.audit": "التدقيق والسجل",
    "nav.settings": "الإعدادات",
    "nav.signOut": "تسجيل الخروج",
    "language.label": "اللغة",
    "language.english": "الإنجليزية",
    "language.arabic": "العربية",
    "language.bilingual": "ثنائي اللغة",
    "session.checking": "جارٍ التحقق من الجلسة الآمنة…",
    "development.notice": "وضع التطوير: إعدادات Firebase للعميل غير موجودة. يتطلب الإنتاج مصادقة Firebase وتوفير العضوية على الخادم.",
    "dashboard.eyebrow": "لوحة المعلومات",
    "dashboard.title": "مساحة عمل المختبر",
    "dashboard.lead": "ابدأ بحالة، ثم استخدم مساحة تحليل المتغيرات لمراجعة حالة سير العمل المحفوظة بشكل مستمر.",
    "dashboard.cases.title": "الحالات",
    "dashboard.cases.body": "استقبال متمحور حول الحالة وسجل التحليل الطولي.",
    "dashboard.cases.link": "فتح الحالات ←",
    "dashboard.variant.title": "خدمة المتغيرات",
    "dashboard.variant.body": "مساحة العمل الحالية للتحليل والمراجعة والتقارير والتدقيق.",
    "dashboard.variant.link": "فتح مساحة العمل ←",
    "dashboard.review.title": "المراجعة السريرية",
    "dashboard.review.body": "قائمة انتظار لتفسير المتغيرات مرتبة حسب الأولوية مع مراجعة ACMG المرتبطة بالأدلة وقرارات ذات إصدارات.",
    "dashboard.review.link": "فتح قائمة المراجعة ←",
    "settings.eyebrow": "الحوكمة · الإعدادات",
    "settings.title": "الإعدادات",
    "settings.lead": "هوية مساحة العمل الموثقة، والاستحقاق، واتصال الخدمة، وسياق سير العمل النشط.",
    "settings.identity": "الهوية",
    "settings.currentSession": "الجلسة الحالية",
    "settings.email": "البريد الإلكتروني",
    "settings.role": "الدور",
    "settings.userId": "معرّف المستخدم",
    "settings.organization": "المؤسسة",
    "settings.entitlement": "الاستحقاق",
    "settings.loadingSession": "جارٍ تحميل الجلسة الموثقة…",
    "settings.service": "الخدمة",
    "settings.backendConnection": "اتصال الخادم",
    "settings.api": "واجهة API",
    "settings.health": "الحالة",
    "settings.serverControlled": "تبقى الموارد العلمية وإعدادات سير العمل تحت تحكم الخادم. لا تعرض هذه الصفحة إعدادات آمنة قابلة للتجاوز من العميل.",
    "settings.activeContext": "السياق النشط",
    "settings.browserContext": "سياق سير العمل في المتصفح",
    "settings.caseId": "معرّف الحالة",
    "settings.analysisId": "معرّف التحليل",
    "settings.contextNote": "يؤدي اختيار حالة من سجل الحالات إلى تحديث هذا السياق تلقائياً.",
    "settings.unableToLoad": "تعذر تحميل الإعدادات.",
    "public.about": "عن SIRALOOM",
    "public.services": "الخدمات",
    "public.contact": "اتصل بنا",
    "public.signIn": "تسجيل الدخول",
    "public.startTrial": "ابدأ التجربة المجانية",
    "public.privacy": "الخصوصية",
    "public.terms": "الشروط",
    "public.home.eyebrow": "منصة الذكاء الجينومي",
    "public.home.title": "سير عمل متصل بالأدلة للمختبرات الجينومية.",
    "public.home.lead": "تبني SIRALOOM بنية قابلة للتوسع تربط استقبال الحالات والأدلة الجينومية والمراجعة البشرية وإعداد التقارير والسجل الحسابي الشفاف.",
    "public.home.traceable.title": "قابل للتتبع منذ التصميم",
    "public.home.traceable.body": "تحافظ القطع والأدلة والقرارات والموارد والتقارير على سجلها التاريخي.",
    "public.home.review.title": "مصمم للمراجعة",
    "public.home.review.body": "تبقى الملاحظات الحاسوبية منفصلة عن التفسير السريري.",
    "public.home.extend.title": "مصمم للتوسع",
    "public.home.extend.body": "Variant هي أول خدمة على نواة منصة مستقرة وليست أداة معزولة.",
    "public.about.eyebrow": "عن SIRALOOM",
    "public.about.title": "بنية تحتية لتفسير جينومي مدروس.",
    "public.about.lead": "ننشئ منصة قابلة للتوسع للمختبرات التي تحتاج إلى التتبع العلمي والأدلة المترابطة وسير العمل المستمر من استقبال الحالة حتى إعداد التقرير.",
    "public.about.core.title": "نواة المنصة أولاً",
    "public.about.core.body": "الهوية والحالات والقطع وحالة سير العمل والأدلة والمراجعة والتقارير والتدقيق هي أسس مشتركة للخدمات العلمية الحالية والمستقبلية.",
    "public.about.review.title": "تبقى المراجعة البشرية محورية",
    "public.about.review.body": "تدعم SIRALOOM الخبراء بسياق حاسوبي شفاف. ولا تحل محل الحكم السريري ولا تدعي الاعتماد السريري.",
    "public.services.eyebrow": "الخدمات",
    "public.services.title": "خدمات علمية على منصة مختبرية مشتركة.",
    "public.services.variant.eyebrow": "الخدمة 01",
    "public.services.variant.title": "SIRALOOM Variant",
    "public.services.variant.body": "سير عمل لتفسير VCF يشمل التحقق والتطبيع ودمج الأدلة والتقييم المتوافق مع ACMG والمراجعة والتقارير والتتبع.",
    "public.services.variant.link": "عرض الخدمة ←",
    "public.services.future": "قد تشمل الخدمات المستقبلية CNV وSV وRNA والتحليل الجسدي وعلم الصيدلة الجيني والنمط الظاهري وإعادة التحليل عبر نواة المنصة نفسها.",
    "public.variant.eyebrow": "SIRALOOM VARIANT",
    "public.variant.title": "من استقبال VCF إلى تفسير قابل للمراجعة والتدقيق.",
    "public.variant.lead": "خدمة متمحورة حول الحالة مصممة للحفاظ على المدخلات الأصلية وسياق سير العمل ومصدر الموارد وقرارات المراجعين وسجل التقارير.",
    "public.variant.case": "الحالة",
    "public.variant.validate": "التحقق",
    "public.variant.normalize": "التطبيع",
    "public.variant.evidence": "الأدلة",
    "public.variant.review": "المراجعة",
    "public.variant.report": "التقرير",
    "public.variant.note": "تبقى الموارد الخارجية والمخرجات العلمية معتمدة على الإعداد وتتطلب تحقق المختبر للاستخدام المقصود.",
    "public.variant.create": "إنشاء حساب",
    "public.contact.eyebrow": "اتصل بنا",
    "public.contact.title": "تحدث مع فريق SIRALOOM.",
    "public.contact.lead": "لاستفسارات المنصة وسير عمل المختبر والتنفيذ، تواصل مع ممثل SIRALOOM.",
    "public.contact.note": "خدمة استقبال الاتصالات غير مهيأة في هذه البيئة؛ ولا يتم جمع أي إرساليات من النماذج هنا.",
    "public.privacy.eyebrow": "الخصوصية",
    "public.privacy.title": "مبادئ الخصوصية",
    "public.privacy.body": "صُممت SIRALOOM بحيث يكون الوصول إلى بيانات المختبر محصوراً بالمستأجر وخاضعاً للتفويض الموثق. وتتحمل المؤسسات الناشرة مسؤولية إعداد الوصول والاحتفاظ والالتزامات التنظيمية المناسبة لاستخدامها.",
    "public.terms.eyebrow": "الشروط",
    "public.terms.title": "استخدام SIRALOOM",
    "public.terms.body": "SIRALOOM منصة لسير العمل الجينومي ودعم القرار. ولا يمثل هذا البرنامج نفسه على أنه مُتحقق سريرياً أو معتمد أو بديلاً عن المراجعة المهنية المؤهلة.",
    "auth.secure": "الوصول الآمن",
    "auth.login.title": "تسجيل الدخول إلى مساحة العمل",
    "auth.signup.trialTitle": "ابدأ تجربة SIRALOOM",
    "auth.signup.orgTitle": "أنشئ حساب SIRALOOM",
    "auth.login.body": "استخدم حساب المختبر المعتمد لك.",
    "auth.signup.trialBody": "لا يلزم إدخال وسيلة دفع. سيتم إنشاء مساحة العمل تلقائياً بعد التحقق من هويتك.",
    "auth.signup.orgBody": "سيتم إنشاء مساحة مؤسستك تلقائياً بعد التحقق من هويتك.",
    "auth.google": "المتابعة باستخدام Google",
    "auth.or": "أو",
    "auth.email": "البريد الإلكتروني",
    "auth.password": "كلمة المرور",
    "auth.working": "جارٍ التنفيذ…",
    "auth.signIn": "تسجيل الدخول",
    "auth.startTrial": "ابدأ التجربة المجانية",
    "auth.createAccount": "إنشاء حساب",
    "auth.resetPassword": "إعادة تعيين كلمة المرور",
    "auth.newUser": "جديد على SIRALOOM؟",
    "auth.startFreeTrial": "ابدأ تجربة مجانية",
    "auth.haveAccount": "لديك حساب بالفعل؟",
    "auth.firebaseMissing": "لم يتم إعداد Firebase لهذا النشر.",
    "auth.failed": "تعذر إكمال المصادقة.",
    "auth.enterEmail": "أدخل عنوان بريدك الإلكتروني أولاً.",
    "auth.resetSent": "تم إرسال رسالة إعادة تعيين كلمة المرور.",
    "auth.resetFailed": "تعذر إرسال إعادة التعيين.",
    "auth.googleFailed": "تعذر إكمال تسجيل الدخول باستخدام Google.",
    "auth.orgSwitch": "هل تريد إعداد حساب مختبر إنتاجي بدلاً من ذلك؟",
    "onboarding.secure": "الوصول الآمن مطلوب",
    "onboarding.trialEyebrow": "التجربة المجانية لـ SIRALOOM",
    "onboarding.orgEyebrow": "إعداد المؤسسة",
    "onboarding.trialTitle": "مساحة تجربتك جاهزة للإنشاء",
    "onboarding.orgTitle": "إعداد مساحة عمل المختبر",
    "onboarding.trialBody": "ستنشئ SIRALOOM مساحة تجربتك الخاصة تلقائياً. لا يلزم إدخال وسيلة دفع.",
    "onboarding.orgBody": "ستنشيء SIRALOOM المؤسسة وتعيّنك دور المسؤول الأول من جهة الخادم.",
    "onboarding.labName": "اسم المختبر",
    "onboarding.optional": "اختياري",
    "onboarding.verifyBody": "نحتاج إلى بريد إلكتروني موثق قبل إنشاء مساحة العمل. تحقق من بريدك الوارد لرسالة التحقق من Firebase.",
    "onboarding.checking": "جارٍ التحقق…",
    "onboarding.verified": "لقد تحققت من بريدي الإلكتروني",
    "onboarding.resend": "إعادة إرسال رسالة التحقق",
    "onboarding.create": "ابدأ التجربة المجانية",
    "onboarding.createOrg": "إنشاء المؤسسة",
    "onboarding.creating": "جارٍ إنشاء مساحة العمل…",
    "onboarding.signOut": "تسجيل الخروج",
    "onboarding.returnSignIn": "العودة إلى تسجيل الدخول",
    "onboarding.accessRequired": "الوصول الآمن مطلوب",
    "onboarding.signInFirst": "يرجى تسجيل الدخول قبل بدء مساحة عمل SIRALOOM.",
    "onboarding.firebaseMissing": "لم يتم إعداد Firebase لهذا النشر.",
    "onboarding.verifySent": "تم إرسال رسالة التحقق.",
    "onboarding.notVerified": "لم يتم توثيق بريدك الإلكتروني بعد. افتح رسالة التحقق من Firebase وحاول مرة أخرى.",
    "onboarding.createFailed": "تعذر إنشاء مساحة عمل SIRALOOM.",
    "workflow.case": "الحالة",
    "workflow.specimen": "العينة",
    "workflow.variantFile": "ملف المتغيرات",
    "workflow.index": "الفهرس",
    "workflow.review": "المراجعة",
    "workflow.inputValidation": "التحقق من الإدخال",
    "workflow.normalization": "التطبيع",
    "workflow.annotation": "التعليق الجينومي",
    "workflow.population": "السياق السكاني",
    "workflow.evidence": "الأدلة",
    "workflow.acmg": "تقييم ACMG",
    "workflow.humanReview": "المراجعة البشرية",
    "workflow.report": "التقرير",
    "workflow.caseHistory": "سجل الحالة",
    "reports.validationDisclaimer": "يختلف التحقق من برنامج SIRALOOM عن التحقق السريري للمختبر أو الاعتماد أو الترخيص التنظيمي. ويظل الإصدار خاضعاً للموقّع المؤهل في المختبر وسياساته ومتطلبات الاختصاص القضائي.",
  },
};
