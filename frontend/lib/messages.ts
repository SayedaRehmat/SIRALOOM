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
  | "workspace.eyebrow"
  | "workspace.subtitle"
  | "workspace.title"
  | "workspace.lead"
  | "workspace.startCase"
  | "workspace.caseIdentifier"
  | "workspace.clinicalIndication"
  | "workspace.registerSpecimen"
  | "workspace.vcfIntake"
  | "workspace.selectSpecimen"
  | "workspace.inputPersisted"
  | "workspace.registerInput"
  | "workspace.startAnalysis"
  | "workspace.durableWorkflow"
  | "workspace.checkpointPersisted"
  | "workspace.prioritizedVariants"
  | "workspace.waitingAnalysis"
  | "workspace.variantsWillPopulate"
  | "workspace.completeReport"
  | "workspace.allAnalyzedVariants"
  | "workspace.completeReportLead"
  | "workspace.downloadCsv"
  | "workspace.downloadJson"
  | "workspace.noCompleteDataset"
  | "workspace.completeDatasetPending"
  | "workspace.first100Note"
  | "workspace.variantEvidence"
  | "workspace.noVariantSelected"
  | "workspace.selectVariantAfterAnalysis"
  | "workspace.canonical"
  | "workspace.normalization"
  | "workspace.noEvidence"
  | "workspace.humanDecisionWorkspace"
  | "workspace.reviewPending"
  | "workspace.automatedOutputProposed"
  | "workspace.proposedCurrent"
  | "workspace.startReview"
  | "workspace.accept"
  | "workspace.reject"
  | "workspace.criterionReviewReason"
  | "workspace.finalApprovalReason"
  | "workspace.approveClassification"
  | "workspace.requestMoreEvidence"
  | "workspace.generateReport"
  | "workspace.noReviewActions"
  | "workspace.finalReport"
  | "workspace.noReportGenerated"
  | "workspace.reportPending"
  | "workspace.finalizeReport"
  | "workspace.downloadPdf"
  | "workspace.caseTimeline"
  | "workspace.auditReconstructable"
  | "workspace.noAuditEvents"
  | "workspace.exportHistory"
  | "workspace.export"
  | "workspace.status"
  | "workspace.downloadHistoryZip"
  | "workspace.ready"
  | "workspace.notSelected"
  | "workspace.created"
  | "workspace.new"
  | "workspace.loading"
  | "workspace.checkingBackend"
  | "workspace.backendConnected"
  | "workspace.reconnecting"
  | "workspace.reviewRevision"
  | "workspace.noClassification"
  | "workspace.noAutomatedRationale"
  | "workspace.reportArtifact"
  | "workspace.queued"
  | "workspace.caseAndVcfFirst"
  | "workspace.errorLoadCase"
  | "workspace.errorCompleteReport"
  | "workspace.errorExportState"
  | "workspace.errorVariantDetails"
  | "workspace.caseCreated"
  | "workspace.caseLoaded"
  | "workspace.caseCreationFailed"
  | "workspace.caseSpecimenRequired"
  | "workspace.specimenRegistered"
  | "workspace.specimenRegistrationFailed"
  | "workspace.specimenRequired"
  | "workspace.uploadFailed"
  | "workspace.downloadFailed"
  | "workspace.caseVcfRequired"
  | "workspace.analysisQueued"
  | "workspace.analysisStartFailed"
  | "workspace.reviewStarted"
  | "workspace.reviewReasonRequired"
  | "workspace.reasonRequired"
  | "workspace.moreEvidenceRequested"
  | "workspace.approvalReasonRequired"
  | "workspace.classificationApproved"
  | "workspace.finalReportApproved"
  | "workspace.reportFinalized"
  | "workspace.reportFinalizationFailed"
  | "workspace.exportQueued"
  | "workspace.exportFailed"
  | "workspace.backendReconnectingPrefix"
  | "workspace.connectionUnavailable"
  | "workspace.inputRegisteredPrefix"
  | "workspace.downloadFailedPrefix"
  | "workspace.variantsCount"
  | "workspace.rowsCount"
  | "workspace.eventsCount"
  | "workspace.unknown"
  | "workspace.noData"
  | "workspace.evidence"
  | "workspace.unknownSource"
  | "workspace.unversioned"
  | "workspace.service"
  | "workspace.pipeline"
  | "workspace.caseSection"
  | "workspace.caseId"
  | "workspace.specimenSection"
  | "workspace.blood"
  | "workspace.saliva"
  | "workspace.buccal"
  | "workspace.other"
  | "workspace.inputSection"
  | "workspace.phaseOne"
  | "workspace.choose"
  | "workspace.artifactId"
  | "workspace.executionSection"
  | "workspace.interpretationSection"
  | "workspace.position"
  | "workspace.refAlt"
  | "workspace.build"
  | "workspace.review"
  | "workspace.selected"
  | "workspace.open"
  | "workspace.evidenceSection"
  | "workspace.reviewSection"
  | "workspace.decisionHistory"
  | "workspace.reportSection"
  | "workspace.auditSection"
  | "workspace.auditLead"
  | "workspace.footer"
  | "cases.eyebrow"
  | "cases.title"
  | "cases.lead"
  | "cases.back"
  | "cases.registry"
  | "cases.existing"
  | "cases.registryHelp"
  | "cases.none"
  | "cases.createHelp"
  | "cases.actionFailed"
  | "cases.info"
  | "cases.identifier"
  | "cases.indication"
  | "cases.create"
  | "cases.specimen"
  | "cases.specimenIdentifier"
  | "cases.specimenType"
  | "cases.registered"
  | "cases.typeUnspecified"
  | "cases.upload"
  | "cases.reference"
  | "cases.index"
  | "cases.ready"
  | "cases.caseState"
  | "cases.readyAnalysis"
  | "cases.validationDiagnostics"
  | "cases.blood"
  | "cases.saliva"
  | "cases.buccal"
  | "cases.tissue"
  | "cases.other"
  | "cases.case"
  | "cases.specimenLabel"
  | "cases.build"
  | "cases.primaryValidation"
  | "cases.indexLabel"
  | "reports.eyebrow"
  | "reports.title"
  | "reports.lead"
  | "reports.analysisId"
  | "reports.type"
  | "reports.clinical"
  | "reports.analytical"
  | "reports.evaluate"
  | "reports.generate"
  | "reports.section"
  | "reports.none"
  | "reports.help"
  | "reports.human"
  | "reports.noSelected"
  | "reports.selectHelp"
  | "reports.variant"
  | "reports.disposition"
  | "reports.priority"
  | "reports.reviewVersion"
  | "reports.policy"
  | "reports.finalDisposition"
  | "reports.rationale"
  | "reports.finalize"
  | "reports.versions"
  | "reports.lineage"
  | "reports.noReports"
  | "reports.reportHelp"
  | "reports.pdf"
  | "reports.signout"
  | "audit.eyebrow"
  | "audit.title"
  | "audit.lead"
  | "audit.open"
  | "audit.history"
  | "audit.refresh"
  | "audit.none"
  | "audit.help"
  | "audit.openCases"
  | "audit.timeline"
  | "audit.eventsNone"
  | "audit.selectHelp"
  | "review.eyebrow"
  | "review.title"
  | "review.lead"
  | "review.open"
  | "review.analysisId"
  | "review.status"
  | "review.classification"
  | "review.reportability"
  | "review.refresh"
  | "review.queue"
  | "review.none"
  | "review.refreshHelp"
  | "review.select"
  | "review.dossier"
  | "review.clinicalClassification"
  | "review.priority"
  | "review.build"
  | "review.noIndication"
  | "review.hpo"
  | "review.hpoNone"
  | "review.present"
  | "review.phenotype"
  | "review.geneDiseaseNone"
  | "review.inheritance"
  | "review.family"
  | "review.familyHelp"
  | "review.familyNone"
  | "review.parentChild"
  | "review.relationshipNone"
  | "review.addRelationship"
  | "review.segregation"
  | "review.segregationNone"
  | "review.familyMember"
  | "review.zygosity"
  | "review.phase"
  | "review.phenotypeStatus"
  | "review.recordObservation"
  | "review.inheritanceAssessment"
  | "review.inheritanceHelp"
  | "review.assessModels"
  | "review.noModel"
  | "review.context"
  | "review.variant"
  | "review.gene"
  | "review.population"
  | "review.populationNone"
  | "review.qc"
  | "review.qcNone"
  | "review.assay"
  | "review.assayProfile"
  | "review.assayHelp"
  | "review.profile"
  | "review.version"
  | "review.qcGate"
  | "review.qcObsNone"
  | "review.evidence"
  | "review.evidenceNone"
  | "review.acmg"
  | "review.linkEvidence"
  | "review.accept"
  | "review.modify"
  | "review.reject"
  | "review.criteriaNone"
  | "review.relevance"
  | "review.reportabilityNone"
  | "review.confirmation"
  | "review.confirmationHelp"
  | "review.confirmationRequired"
  | "review.saveConfirmation"
  | "review.followup"
  | "review.followupNone"
  | "review.addFollowup"
  | "review.secondary"
  | "review.secondaryHelp"
  | "review.current"
  | "review.saveDecision"
  | "review.signout"
  | "review.signoutHelp"
  | "review.start"
  | "review.approve"
  | "review.more"
  | "review.actionsNone"
  | "cases.identifierPlaceholder"
  | "cases.indicationPlaceholder"
  | "cases.specimenPlaceholder"
  | "cases.refreshing"
  | "cases.creating"
  | "cases.registering"
  | "review.analysisPlaceholder"
  | "review.hpoLabelPlaceholder"
  | "review.memberPlaceholder"
  | "review.genotypePlaceholder"
  | "review.inheritancePlaceholder"
  | "review.rationalePlaceholder"
  | "review.methodPlaceholder"
  | "review.resultPlaceholder"
  | "review.laboratoryPlaceholder"
  | "review.accessionPlaceholder"
  | "review.confirmationNotesPlaceholder"
  | "review.followActionPlaceholder"
  | "review.followNotesPlaceholder"
  | "review.policyNamePlaceholder"
  | "review.policyVersionPlaceholder"
  | "review.policyRationalePlaceholder"
  | "review.signoutPlaceholder"
  | "reports.rationalePlaceholder"
  | "reports.validationDisclaimer";


export const messages: Record<CatalogLanguage, Record<TranslationKey, string>> = {
  en: {
    "cases.eyebrow": "SIRALOOM VARIANT · CASE INTAKE",
    "cases.title": "New genomic case",
    "cases.lead": "Create a traceable case, register its specimen, and validate the variant dataset before scientific analysis begins.",
    "cases.back": "Back to dashboard",
    "cases.registry": "CASE REGISTRY",
    "cases.existing": "Existing cases",
    "cases.registryHelp": "Select a previously created case to continue its persisted workflow.",
    "cases.none": "No cases found",
    "cases.createHelp": "Create a case below. Cases are stored server-side in your organization.",
    "cases.actionFailed": "Action could not be completed",
    "cases.info": "Case information",
    "cases.identifier": "Case identifier",
    "cases.indication": "Clinical indication",
    "cases.create": "Create case",
    "cases.specimen": "Register specimen",
    "cases.specimenIdentifier": "Specimen identifier",
    "cases.specimenType": "Specimen type",
    "cases.registered": "Registered specimens",
    "cases.typeUnspecified": "Type not specified",
    "cases.upload": "Upload variant dataset",
    "cases.reference": "Reference genome",
    "cases.index": "Add a tabix/CSI index",
    "cases.ready": "Review ingestion",
    "cases.caseState": "Case state",
    "cases.readyAnalysis": "Ready for analysis",
    "cases.validationDiagnostics": "Validation diagnostics",
    "cases.blood": "Blood",
    "cases.saliva": "Saliva",
    "cases.buccal": "Buccal",
    "cases.tissue": "Tissue",
    "cases.other": "Other",
    "cases.case": "Case",
    "cases.specimenLabel": "Specimen",
    "cases.build": "Build",
    "cases.primaryValidation": "Primary validation",
    "cases.indexLabel": "Index",
    "reports.eyebrow": "GOVERNED REPORTING",
    "reports.title": "Reports & sign-out",
    "reports.lead": "Separate reportability from pathogenicity classification, preserve every decision version, and release only an authorized immutable report artifact.",
    "reports.analysisId": "Analysis ID",
    "reports.type": "Report type",
    "reports.clinical": "Clinical interpretation",
    "reports.analytical": "Complete analytical",
    "reports.evaluate": "Evaluate reportability",
    "reports.generate": "Generate draft",
    "reports.section": "REPORTABILITY",
    "reports.none": "No reportability decisions",
    "reports.help": "Evaluate the analysis to create versioned policy proposals.",
    "reports.human": "HUMAN REPORTABILITY REVIEW",
    "reports.noSelected": "No decision selected",
    "reports.selectHelp": "Choose a reportability record to review its policy rationale and finalize its disposition.",
    "reports.variant": "Variant",
    "reports.disposition": "Disposition",
    "reports.priority": "Priority",
    "reports.reviewVersion": "Review version",
    "reports.policy": "POLICY RATIONALE",
    "reports.finalDisposition": "Final disposition",
    "reports.rationale": "Reviewer rationale",
    "reports.finalize": "Finalize reportability",
    "reports.versions": "REPORT VERSIONS",
    "reports.lineage": "Immutable report lineage",
    "reports.noReports": "No reports generated",
    "reports.reportHelp": "Generate a clinical or analytical draft after the analysis is available.",
    "reports.pdf": "PDF",
    "reports.signout": "Approve / sign out",
    "audit.eyebrow": "GOVERNANCE · AUDIT",
    "audit.title": "Audit & provenance",
    "audit.lead": "Tenant-scoped case history with persisted workflow, evidence, reviewer, report, and provenance events.",
    "audit.open": "Open workspace",
    "audit.history": "CASE HISTORY",
    "audit.refresh": "Refresh",
    "audit.none": "No cases",
    "audit.help": "Create or load a case from the Cases page.",
    "audit.openCases": "Open cases",
    "audit.timeline": "TIMELINE",
    "audit.eventsNone": "No audit events",
    "audit.selectHelp": "Select a case with persisted activity.",
    "review.eyebrow": "SIRALOOM VARIANT · CLINICAL REVIEW",
    "review.title": "Clinical interpretation workspace",
    "review.lead": "Case-first review: clinical indication, phenotype, inheritance, variant evidence, population context, disease validity, literature, ACMG/ClinGen assessment, reportability and sign-out readiness.",
    "review.open": "Open variant workspace",
    "review.analysisId": "Analysis ID",
    "review.status": "Review status",
    "review.classification": "Classification",
    "review.reportability": "Reportability",
    "review.refresh": "Refresh clinical queue",
    "review.queue": "CLINICAL QUEUE",
    "review.none": "No review candidates",
    "review.refreshHelp": "Run a completed interpretation and refresh.",
    "review.select": "Select a variant",
    "review.dossier": "The clinical review dossier will appear here.",
    "review.clinicalClassification": "Clinical classification",
    "review.priority": "Priority",
    "review.build": "Build",
    "review.noIndication": "No clinical indication recorded.",
    "review.hpo": "Observed HPO phenotype",
    "review.hpoNone": "No HPO observations recorded for this case.",
    "review.present": "Present",
    "review.phenotype": "Phenotype match & gene–disease relationship",
    "review.geneDiseaseNone": "No gene–disease context evidence attached.",
    "review.inheritance": "INHERITANCE, PEDIGREE & SEGREGATION",
    "review.family": "Family structure",
    "review.familyHelp": "Record relatives explicitly rather than burying pedigree data in free-text case context.",
    "review.familyNone": "No pedigree members recorded.",
    "review.parentChild": "Parent–child relationships",
    "review.relationshipNone": "No parent–child relationships recorded.",
    "review.addRelationship": "Add relationship",
    "review.segregation": "Variant segregation observations",
    "review.segregationNone": "No variant-specific family observations recorded.",
    "review.familyMember": "Family member",
    "review.zygosity": "Zygosity",
    "review.phase": "Phase",
    "review.phenotypeStatus": "Phenotype status",
    "review.recordObservation": "Record observation",
    "review.inheritanceAssessment": "Inheritance model assessment",
    "review.inheritanceHelp": "Consistency aid only. It does not assign pathogenicity or an ACMG/ClinGen criterion strength.",
    "review.assessModels": "Assess selected models",
    "review.noModel": "No model assessment has been recorded.",
    "review.context": "VARIANT, POPULATION & TECHNICAL CONTEXT",
    "review.variant": "Variant",
    "review.gene": "Gene",
    "review.population": "Population observations",
    "review.populationNone": "No population observations.",
    "review.qc": "Technical QC",
    "review.qcNone": "No variant-level QC fields were exposed by the annotation provider.",
    "review.assay": "ASSAY & TECHNICAL QUALITY GATE",
    "review.assayProfile": "Assay profile",
    "review.assayHelp": "QC thresholds are laboratory/assay-specific. SIRALOOM records the profile and provenance; it does not invent universal clinical cut-offs.",
    "review.profile": "Profile",
    "review.version": "Version",
    "review.qcGate": "QC gate",
    "review.qcObsNone": "No technical QC observations recorded for this analysis.",
    "review.evidence": "CLINVAR / CLINGEN / LITERATURE / FUNCTIONAL",
    "review.evidenceNone": "No literature or functional/computational context evidence is attached to this variant.",
    "review.acmg": "ACMG / CLINGEN HUMAN ASSESSMENT",
    "review.linkEvidence": "Link supporting/contradictory evidence",
    "review.accept": "Accept",
    "review.modify": "Modify",
    "review.reject": "Reject",
    "review.criteriaNone": "No ACMG criteria persisted.",
    "review.relevance": "CLINICAL RELEVANCE, CONFIRMATION & FOLLOW-UP",
    "review.reportabilityNone": "No reportability decision has been generated.",
    "review.confirmation": "Orthogonal confirmation",
    "review.confirmationHelp": "Confirmation is an explicit laboratory policy decision. SIRALOOM blocks final release only when a record explicitly marks confirmation as required.",
    "review.confirmationRequired": "Confirmation required",
    "review.saveConfirmation": "Save confirmation",
    "review.followup": "Follow-up plan",
    "review.followupNone": "No variant-specific follow-up actions recorded.",
    "review.addFollowup": "Add follow-up",
    "review.secondary": "Secondary finding governance",
    "review.secondaryHelp": "Secondary findings are a separate policy-controlled workflow. SIRALOOM does not silently apply a gene list or treat secondary findings as primary diagnostic reportability.",
    "review.current": "Current",
    "review.saveDecision": "Save decision",
    "review.signout": "SIGN-OUT GATE & AUDIT TRAIL",
    "review.signoutHelp": "Approval remains a human governance action. Report finalization is separately gated by final classifications and final reportability decisions.",
    "review.start": "Start review",
    "review.approve": "Approve classification",
    "review.more": "Request more evidence",
    "review.actionsNone": "No reviewer actions yet.",
    "cases.identifierPlaceholder": "e.g. SRL-2026-0001",
    "cases.indicationPlaceholder": "Clinical question or indication relevant to this analysis",
    "cases.specimenPlaceholder": "e.g. SP-0001",
    "cases.refreshing": "Refreshing…",
    "cases.creating": "Creating…",
    "cases.registering": "Registering…",
    "review.analysisPlaceholder": "Analysis UUID",
    "review.hpoLabelPlaceholder": "Optional phenotype label",
    "review.memberPlaceholder": "Member ID e.g. FATHER",
    "review.genotypePlaceholder": "Genotype e.g. 0/1, 1/1, 0/0",
    "review.inheritancePlaceholder": "Optional reviewer note on inheritance interpretation",
    "review.rationalePlaceholder": "Reviewer rationale",
    "review.methodPlaceholder": "Method e.g. Sanger",
    "review.resultPlaceholder": "Result e.g. CONFIRMED",
    "review.laboratoryPlaceholder": "Laboratory",
    "review.accessionPlaceholder": "Accession / case ID",
    "review.confirmationNotesPlaceholder": "Confirmation notes",
    "review.followActionPlaceholder": "Action e.g. genetic counselling",
    "review.followNotesPlaceholder": "Follow-up notes / outcome",
    "review.policyNamePlaceholder": "Policy name",
    "review.policyVersionPlaceholder": "Policy version",
    "review.policyRationalePlaceholder": "Policy-specific rationale",
    "review.signoutPlaceholder": "Document the classification approval or request-for-evidence rationale.",
    "reports.rationalePlaceholder": "Document the laboratory basis for the final reportability decision.",
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
    "workspace.eyebrow": "GENOMIC INTERPRETATION PLATFORM",
    "workspace.subtitle": "VCF → evidence → review → report",
    "workspace.title": "Explainable variant interpretation, built for long-running laboratory workflows.",
    "workspace.lead": "Analysis state is persisted server-side. Closing the browser does not stop a running job.",
    "workspace.startCase": "Start a case",
    "workspace.caseIdentifier": "Case identifier",
    "workspace.clinicalIndication": "Clinical indication",
    "workspace.registerSpecimen": "Register specimen",
    "workspace.vcfIntake": "VCF intake",
    "workspace.selectSpecimen": "Select a registered specimen…",
    "workspace.inputPersisted": "Input is persisted before analysis begins.",
    "workspace.registerInput": "Register input",
    "workspace.startAnalysis": "Start analysis",
    "workspace.durableWorkflow": "Durable workflow",
    "workspace.checkpointPersisted": "Checkpoint state is persisted server-side",
    "workspace.prioritizedVariants": "Prioritized variants",
    "workspace.waitingAnalysis": "Waiting for a completed analysis",
    "workspace.variantsWillPopulate": "The table will populate from durable server state once annotation has produced variant records.",
    "workspace.completeReport": "COMPLETE VARIANT REPORT",
    "workspace.allAnalyzedVariants": "All analyzed variants",
    "workspace.completeReportLead": "Inspection layer for the laboratory team. This is separate from the concise clinical report.",
    "workspace.downloadCsv": "Download CSV",
    "workspace.downloadJson": "Download JSON",
    "workspace.noCompleteDataset": "No complete variant dataset yet",
    "workspace.completeDatasetPending": "It becomes available after annotation has produced persistent variant records.",
    "workspace.first100Note": "Showing the first 100 rows for interactive inspection. Download the complete CSV/JSON for the full dataset.",
    "workspace.variantEvidence": "Variant evidence",
    "workspace.noVariantSelected": "No variant selected",
    "workspace.selectVariantAfterAnalysis": "Select a variant after analysis completion.",
    "workspace.canonical": "Canonical",
    "workspace.normalization": "Normalization",
    "workspace.noEvidence": "No evidence records yet",
    "workspace.humanDecisionWorkspace": "Human decision workspace",
    "workspace.reviewPending": "Review becomes available after interpretation",
    "workspace.automatedOutputProposed": "Automated output remains proposed until a reviewer acts.",
    "workspace.proposedCurrent": "Proposed / current",
    "workspace.startReview": "Start review",
    "workspace.accept": "Accept",
    "workspace.reject": "Reject",
    "workspace.criterionReviewReason": "Criterion review reason",
    "workspace.finalApprovalReason": "Final approval reason",
    "workspace.approveClassification": "Approve classification",
    "workspace.requestMoreEvidence": "Request more evidence",
    "workspace.generateReport": "Generate report",
    "workspace.noReviewActions": "No review actions yet.",
    "workspace.finalReport": "Final report",
    "workspace.noReportGenerated": "No report generated",
    "workspace.reportPending": "Report generation is downstream of reviewer-approved interpretation.",
    "workspace.finalizeReport": "Finalize report",
    "workspace.downloadPdf": "Download PDF",
    "workspace.caseTimeline": "Case timeline",
    "workspace.auditReconstructable": "Every important action is reconstructable.",
    "workspace.noAuditEvents": "No audit events yet",
    "workspace.exportHistory": "Export complete case history",
    "workspace.export": "Export",
    "workspace.status": "Status",
    "workspace.downloadHistoryZip": "Download case history ZIP",
    "workspace.ready": "Ready",
    "workspace.notSelected": "Not selected",
    "workspace.created": "Created",
    "workspace.new": "New",
    "workspace.loading": "Loading…",
    "workspace.checkingBackend": "Checking backend…",
    "workspace.backendConnected": "Backend connected",
    "workspace.reconnecting": "Reconnecting",
    "workspace.reviewRevision": "Review revision",
    "workspace.noClassification": "No classification",
    "workspace.noAutomatedRationale": "No automated rationale recorded.",
    "workspace.reportArtifact": "Interpretation available in report artifact.",
    "workspace.queued": "Queued",
    "workspace.caseAndVcfFirst": "Create/select a case and choose a VCF first.",
    "workspace.errorLoadCase": "Unable to load case.",
    "workspace.errorCompleteReport": "Unable to load complete variant report.",
    "workspace.errorExportState": "Unable to read export state.",
    "workspace.errorVariantDetails": "Unable to load variant details.",
    "workspace.caseCreated": "Case created.",
    "workspace.caseLoaded": "Existing case loaded.",
    "workspace.caseCreationFailed": "Case creation failed.",
    "workspace.caseSpecimenRequired": "A case and specimen identifier are required.",
    "workspace.specimenRegistered": "Specimen registered to the case.",
    "workspace.specimenRegistrationFailed": "Specimen registration failed.",
    "workspace.specimenRequired": "Register or select a specimen before uploading the VCF.",
    "workspace.uploadFailed": "Upload failed.",
    "workspace.downloadFailed": "Download failed.",
    "workspace.caseVcfRequired": "Case and uploaded VCF are required.",
    "workspace.analysisQueued": "Analysis queued. You can close the browser; execution is server-side.",
    "workspace.analysisStartFailed": "Analysis start failed.",
    "workspace.reviewStarted": "Review started.",
    "workspace.reviewReasonRequired": "A review reason is required.",
    "workspace.reasonRequired": "A reason is required.",
    "workspace.moreEvidenceRequested": "More evidence requested; classification remains pending.",
    "workspace.approvalReasonRequired": "An approval reason is required.",
    "workspace.classificationApproved": "Classification approved.",
    "workspace.finalReportApproved": "Final report approved by reviewer.",
    "workspace.reportFinalized": "Report finalized.",
    "workspace.reportFinalizationFailed": "Report finalization failed.",
    "workspace.exportQueued": "Complete case-history export queued. It is independent of the browser session.",
    "workspace.exportFailed": "Case export failed.",
    "workspace.backendReconnectingPrefix": "Backend reconnecting: ",
    "workspace.connectionUnavailable": "connection unavailable",
    "workspace.inputRegisteredPrefix": "Input registered. SHA-256: ",
    "workspace.downloadFailedPrefix": "Download failed: ",
    "workspace.variantsCount": "variants",
    "workspace.rowsCount": "rows",
    "workspace.eventsCount": "events",
    "workspace.unknown": "Unknown",
    "workspace.noData": "No data",
    "workspace.evidence": "Evidence",
    "workspace.unknownSource": "Unknown source",
    "workspace.unversioned": "unversioned",
    "workspace.service": "SERVICE 01",
    "workspace.pipeline": "Pipeline",
    "workspace.caseSection": "CASE",
    "workspace.caseId": "Case ID",
    "workspace.specimenSection": "SPECIMEN",
    "workspace.blood": "Blood",
    "workspace.saliva": "Saliva",
    "workspace.buccal": "Buccal",
    "workspace.other": "Other",
    "workspace.inputSection": "INPUT",
    "workspace.phaseOne": "Phase 1",
    "workspace.choose": "Choose",
    "workspace.artifactId": "Artifact ID",
    "workspace.executionSection": "EXECUTION",
    "workspace.interpretationSection": "INTERPRETATION",
    "workspace.position": "Position",
    "workspace.refAlt": "Ref / Alt",
    "workspace.build": "Build",
    "workspace.review": "Review",
    "workspace.selected": "Selected",
    "workspace.open": "Open",
    "workspace.evidenceSection": "EVIDENCE",
    "workspace.reviewSection": "REVIEW",
    "workspace.decisionHistory": "DECISION HISTORY",
    "workspace.reportSection": "REPORT",
    "workspace.auditSection": "AUDIT & PROVENANCE",
    "workspace.auditLead": "Computational steps, resources, evidence, reviewer actions and report events are persisted to the case history.",
    "workspace.footer": "Scientific results remain subject to configured resources, review, validation scope, and laboratory governance.",
    "reports.validationDisclaimer": "SIRALOOM software validation is distinct from clinical laboratory validation, accreditation, or regulatory authorization. Release remains subject to the laboratory's qualified signatory, policies, and jurisdictional requirements.",
  },
  ar: {
    "cases.eyebrow": "SIRALOOM VARIANT · إدخال الحالة",
    "cases.title": "حالة جينومية جديدة",
    "cases.lead": "أنشئ حالة قابلة للتتبع، وسجّل عينتها، وتحقق من صحة مجموعة المتغيرات قبل بدء التحليل العلمي.",
    "cases.back": "العودة إلى لوحة المعلومات",
    "cases.registry": "سجل الحالات",
    "cases.existing": "الحالات الحالية",
    "cases.registryHelp": "اختر حالة منشأة مسبقًا لمتابعة سير عملها المحفوظ.",
    "cases.none": "لم يتم العثور على حالات",
    "cases.createHelp": "أنشئ حالة أدناه. تُحفظ الحالات على الخادم ضمن مؤسستك.",
    "cases.actionFailed": "تعذر إكمال الإجراء",
    "cases.info": "معلومات الحالة",
    "cases.identifier": "معرّف الحالة",
    "cases.indication": "الداعي السريري",
    "cases.create": "إنشاء الحالة",
    "cases.specimen": "تسجيل العينة",
    "cases.specimenIdentifier": "معرّف العينة",
    "cases.specimenType": "نوع العينة",
    "cases.registered": "العينات المسجلة",
    "cases.typeUnspecified": "النوع غير محدد",
    "cases.upload": "رفع مجموعة بيانات المتغيرات",
    "cases.reference": "الجينوم المرجعي",
    "cases.index": "إضافة فهرس tabix/CSI",
    "cases.ready": "مراجعة الإدخال",
    "cases.caseState": "حالة الحالة",
    "cases.readyAnalysis": "جاهز للتحليل",
    "cases.validationDiagnostics": "تشخيصات التحقق",
    "cases.blood": "دم",
    "cases.saliva": "لعاب",
    "cases.buccal": "مسحة شدقية",
    "cases.tissue": "نسيج",
    "cases.other": "أخرى",
    "cases.case": "الحالة",
    "cases.specimenLabel": "العينة",
    "cases.build": "البناء",
    "cases.primaryValidation": "التحقق الأساسي",
    "cases.indexLabel": "الفهرس",
    "reports.eyebrow": "إصدار التقارير المحكوم",
    "reports.title": "التقارير والاعتماد النهائي",
    "reports.lead": "افصل قابلية الإبلاغ عن تصنيف الإمراضية، واحفظ كل إصدار من القرارات، ولا تُصدر إلا أثر تقرير ثابتًا ومصرحًا به.",
    "reports.analysisId": "معرّف التحليل",
    "reports.type": "نوع التقرير",
    "reports.clinical": "التفسير السريري",
    "reports.analytical": "تحليل كامل",
    "reports.evaluate": "تقييم قابلية الإبلاغ",
    "reports.generate": "إنشاء مسودة",
    "reports.section": "قابلية الإبلاغ",
    "reports.none": "لا توجد قرارات لقابلية الإبلاغ",
    "reports.help": "قيّم التحليل لإنشاء مقترحات سياسة ذات إصدارات.",
    "reports.human": "المراجعة البشرية لقابلية الإبلاغ",
    "reports.noSelected": "لم يتم تحديد قرار",
    "reports.selectHelp": "اختر سجل قابلية الإبلاغ لمراجعة مبرره واعتماد تصرفه النهائي.",
    "reports.variant": "المتغير",
    "reports.disposition": "التصرف النهائي",
    "reports.priority": "الأولوية",
    "reports.reviewVersion": "إصدار المراجعة",
    "reports.policy": "مبررات السياسة",
    "reports.finalDisposition": "التصرف النهائي",
    "reports.rationale": "مبررات المراجع",
    "reports.finalize": "اعتماد قابلية الإبلاغ نهائيًا",
    "reports.versions": "إصدارات التقرير",
    "reports.lineage": "سلسلة نسب التقرير غير القابلة للتغيير",
    "reports.noReports": "لم يتم إنشاء تقارير",
    "reports.reportHelp": "أنشئ مسودة سريرية أو تحليلية بعد توفر التحليل.",
    "reports.pdf": "PDF",
    "reports.signout": "اعتماد / اعتماد نهائي",
    "audit.eyebrow": "الحوكمة · التدقيق",
    "audit.title": "التدقيق وسلسلة المصدر",
    "audit.lead": "سجل تاريخ الحالات ضمن المؤسسة مع سير العمل المحفوظ، والأدلة، والمراجع، والتقارير، وأحداث سلسلة المصدر.",
    "audit.open": "فتح مساحة العمل",
    "audit.history": "سجل الحالات",
    "audit.refresh": "تحديث",
    "audit.none": "لا توجد حالات",
    "audit.help": "أنشئ حالة أو حمّلها من صفحة الحالات.",
    "audit.openCases": "فتح الحالات",
    "audit.timeline": "الخط الزمني",
    "audit.eventsNone": "لا توجد أحداث تدقيق",
    "audit.selectHelp": "اختر حالة تحتوي على نشاط محفوظ.",
    "review.eyebrow": "SIRALOOM VARIANT · المراجعة السريرية",
    "review.title": "مساحة التفسير السريري",
    "review.lead": "مراجعة تبدأ بالحالة: الداعي السريري، والنمط الظاهري، والوراثة، وأدلة المتغير، والسياق السكاني، وصحة علاقة المرض، والأدبيات، وتقييم ACMG/ClinGen، وقابلية الإبلاغ، والاستعداد للاعتماد النهائي.",
    "review.open": "فتح مساحة المتغيرات",
    "review.analysisId": "معرّف التحليل",
    "review.status": "حالة المراجعة",
    "review.classification": "التصنيف",
    "review.reportability": "قابلية الإبلاغ",
    "review.refresh": "تحديث قائمة المراجعة السريرية",
    "review.queue": "قائمة المراجعة السريرية",
    "review.none": "لا توجد متغيرات مرشحة للمراجعة",
    "review.refreshHelp": "شغّل تفسيرًا مكتملًا ثم حدّث القائمة.",
    "review.select": "اختر متغيرًا",
    "review.dossier": "سيظهر ملف المراجعة السريرية هنا.",
    "review.clinicalClassification": "التصنيف السريري",
    "review.priority": "الأولوية",
    "review.build": "البناء",
    "review.noIndication": "لم يتم تسجيل داعٍ سريري.",
    "review.hpo": "النمط الظاهري المرصود وفق HPO",
    "review.hpoNone": "لم تُسجل ملاحظات HPO لهذه الحالة.",
    "review.present": "موجود",
    "review.phenotype": "تطابق النمط الظاهري وعلاقة الجين بالمرض",
    "review.geneDiseaseNone": "لا توجد أدلة سياقية مرفقة لعلاقة الجين بالمرض.",
    "review.inheritance": "الوراثة، شجرة النسب، والتشارك",
    "review.family": "بنية الأسرة",
    "review.familyHelp": "سجّل الأقارب صراحةً بدل دفن بيانات شجرة النسب داخل نص الحالة الحر.",
    "review.familyNone": "لم يتم تسجيل أفراد في شجرة النسب.",
    "review.parentChild": "علاقات الوالد–الطفل",
    "review.relationshipNone": "لم تُسجل علاقات والد–طفل.",
    "review.addRelationship": "إضافة علاقة",
    "review.segregation": "ملاحظات تشارك المتغير",
    "review.segregationNone": "لم تُسجل ملاحظات أسرية خاصة بالمتغير.",
    "review.familyMember": "فرد الأسرة",
    "review.zygosity": "الزيجوتية",
    "review.phase": "الطور",
    "review.phenotypeStatus": "حالة النمط الظاهري",
    "review.recordObservation": "تسجيل الملاحظة",
    "review.inheritanceAssessment": "تقييم نموذج الوراثة",
    "review.inheritanceHelp": "أداة مساعدة للاتساق فقط. لا تعيّن الإمراضية ولا تحدد قوة معيار ACMG/ClinGen.",
    "review.assessModels": "تقييم النماذج المحددة",
    "review.noModel": "لم يتم تسجيل تقييم للنموذج.",
    "review.context": "سياق المتغير والسكان والجوانب التقنية",
    "review.variant": "المتغير",
    "review.gene": "الجين",
    "review.population": "ملاحظات السكان",
    "review.populationNone": "لا توجد ملاحظات سكانية.",
    "review.qc": "ضبط الجودة التقني",
    "review.qcNone": "لم يوفر مزود التعليق الجينومي حقول ضبط جودة على مستوى المتغير.",
    "review.assay": "بوابة الفحص والجودة التقنية",
    "review.assayProfile": "ملف الفحص",
    "review.assayHelp": "عتبات ضبط الجودة خاصة بالمختبر والفحص. يسجل SIRALOOM الملف وسلسلة المصدر ولا يخترع حدودًا سريرية عامة.",
    "review.profile": "الملف",
    "review.version": "الإصدار",
    "review.qcGate": "بوابة ضبط الجودة",
    "review.qcObsNone": "لم تُسجل ملاحظات ضبط جودة تقنية لهذا التحليل.",
    "review.evidence": "ClinVar / ClinGen / الأدبيات / الوظائف",
    "review.evidenceNone": "لا توجد أدلة سياقية أدبية أو وظيفية/حسابية مرفقة بهذا المتغير.",
    "review.acmg": "التقييم البشري لـ ACMG / ClinGen",
    "review.linkEvidence": "ربط الأدلة الداعمة/المتعارضة",
    "review.accept": "قبول",
    "review.modify": "تعديل",
    "review.reject": "رفض",
    "review.criteriaNone": "لم يتم حفظ معايير ACMG.",
    "review.relevance": "الصلة السريرية، التأكيد، والمتابعة",
    "review.reportabilityNone": "لم يتم إنشاء قرار لقابلية الإبلاغ.",
    "review.confirmation": "التأكيد بوسيلة مستقلة",
    "review.confirmationHelp": "التأكيد قرار صريح وفق سياسة المختبر. يمنع SIRALOOM الإصدار النهائي فقط عندما يحدد سجل صراحةً أن التأكيد مطلوب.",
    "review.confirmationRequired": "التأكيد مطلوب",
    "review.saveConfirmation": "حفظ التأكيد",
    "review.followup": "خطة المتابعة",
    "review.followupNone": "لم تُسجل إجراءات متابعة خاصة بالمتغير.",
    "review.addFollowup": "إضافة متابعة",
    "review.secondary": "حوكمة النتائج الثانوية",
    "review.secondaryHelp": "النتائج الثانوية سير عمل منفصل تحكمه السياسة. لا يطبق SIRALOOM قائمة جينات ضمنيًا ولا يعامل النتائج الثانوية كقابلية إبلاغ تشخيصية أساسية.",
    "review.current": "الحالي",
    "review.saveDecision": "حفظ القرار",
    "review.signout": "بوابة الاعتماد النهائي وسجل التدقيق",
    "review.signoutHelp": "يبقى الاعتماد إجراء حوكمة بشريًا. ويخضع اعتماد التقرير النهائي بشكل منفصل للتصنيفات النهائية وقرارات قابلية الإبلاغ النهائية.",
    "review.start": "بدء المراجعة",
    "review.approve": "اعتماد التصنيف",
    "review.more": "طلب مزيد من الأدلة",
    "review.actionsNone": "لا توجد إجراءات للمراجع بعد.",
    "cases.identifierPlaceholder": "مثال: SRL-2026-0001",
    "cases.indicationPlaceholder": "السؤال السريري أو الداعي ذي الصلة بهذا التحليل",
    "cases.specimenPlaceholder": "مثال: SP-0001",
    "cases.refreshing": "جارٍ التحديث…",
    "cases.creating": "جارٍ الإنشاء…",
    "cases.registering": "جارٍ التسجيل…",
    "review.analysisPlaceholder": "معرّف UUID للتحليل",
    "review.hpoLabelPlaceholder": "تسمية النمط الظاهري اختيارية",
    "review.memberPlaceholder": "معرّف الفرد، مثال: FATHER",
    "review.genotypePlaceholder": "النمط الجيني، مثال: 0/1 أو 1/1 أو 0/0",
    "review.inheritancePlaceholder": "ملاحظة اختيارية للمراجع حول تفسير الوراثة",
    "review.rationalePlaceholder": "مبررات المراجع",
    "review.methodPlaceholder": "الطريقة، مثال: Sanger",
    "review.resultPlaceholder": "النتيجة، مثال: CONFIRMED",
    "review.laboratoryPlaceholder": "المختبر",
    "review.accessionPlaceholder": "رقم الإيداع / معرّف الحالة",
    "review.confirmationNotesPlaceholder": "ملاحظات التأكيد",
    "review.followActionPlaceholder": "الإجراء، مثال: الاستشارة الوراثية",
    "review.followNotesPlaceholder": "ملاحظات المتابعة / النتيجة",
    "review.policyNamePlaceholder": "اسم السياسة",
    "review.policyVersionPlaceholder": "إصدار السياسة",
    "review.policyRationalePlaceholder": "مبررات خاصة بالسياسة",
    "review.signoutPlaceholder": "وثّق مبررات اعتماد التصنيف أو طلب مزيد من الأدلة.",
    "reports.rationalePlaceholder": "وثّق الأساس المختبري لقرار قابلية الإبلاغ النهائي.",
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
    "workspace.eyebrow": "منصة التفسير الجينومي",
    "workspace.subtitle": "VCF ← الأدلة ← المراجعة ← التقرير",
    "workspace.title": "تفسير متغيرات قابل للتفسير، مصمم لسير عمل المختبرات طويل التشغيل.",
    "workspace.lead": "تُحفظ حالة التحليل على الخادم. إغلاق المتصفح لا يوقف المهمة قيد التنفيذ.",
    "workspace.startCase": "بدء حالة",
    "workspace.caseIdentifier": "معرّف الحالة",
    "workspace.clinicalIndication": "الداعي السريري",
    "workspace.registerSpecimen": "تسجيل العينة",
    "workspace.vcfIntake": "إدخال VCF",
    "workspace.selectSpecimen": "اختر عينة مسجلة…",
    "workspace.inputPersisted": "يتم حفظ الإدخال قبل بدء التحليل.",
    "workspace.registerInput": "تسجيل الإدخال",
    "workspace.startAnalysis": "بدء التحليل",
    "workspace.durableWorkflow": "سير عمل مستمر",
    "workspace.checkpointPersisted": "تُحفظ حالة نقاط التحقق على الخادم.",
    "workspace.prioritizedVariants": "المتغيرات ذات الأولوية",
    "workspace.waitingAnalysis": "بانتظار اكتمال التحليل",
    "workspace.variantsWillPopulate": "سيُملأ الجدول من حالة الخادم المستمرة بعد أن ينتج التعليق سجلات المتغيرات.",
    "workspace.completeReport": "تقرير المتغيرات الكامل",
    "workspace.allAnalyzedVariants": "جميع المتغيرات المحللة",
    "workspace.completeReportLead": "طبقة فحص لفريق المختبر. وهي منفصلة عن التقرير السريري المختصر.",
    "workspace.downloadCsv": "تنزيل CSV",
    "workspace.downloadJson": "تنزيل JSON",
    "workspace.noCompleteDataset": "لا توجد مجموعة بيانات كاملة للمتغيرات بعد",
    "workspace.completeDatasetPending": "ستتوفر بعد أن ينتج التعليق سجلات متغيرات مستمرة.",
    "workspace.first100Note": "يتم عرض أول 100 صف للفحص التفاعلي. نزّل CSV/JSON الكامل لمجموعة البيانات بأكملها.",
    "workspace.variantEvidence": "أدلة المتغير",
    "workspace.noVariantSelected": "لم يتم اختيار متغير",
    "workspace.selectVariantAfterAnalysis": "اختر متغيرًا بعد اكتمال التحليل.",
    "workspace.canonical": "قياسي",
    "workspace.normalization": "التطبيع",
    "workspace.noEvidence": "لا توجد سجلات أدلة بعد",
    "workspace.humanDecisionWorkspace": "مساحة قرار المراجع",
    "workspace.reviewPending": "تتوفر المراجعة بعد اكتمال التفسير",
    "workspace.automatedOutputProposed": "يبقى الناتج الآلي مقترحًا حتى يتخذ المراجع إجراءً.",
    "workspace.proposedCurrent": "المقترح / الحالي",
    "workspace.startReview": "بدء المراجعة",
    "workspace.accept": "قبول",
    "workspace.reject": "رفض",
    "workspace.criterionReviewReason": "سبب مراجعة المعيار",
    "workspace.finalApprovalReason": "سبب الموافقة النهائية",
    "workspace.approveClassification": "اعتماد التصنيف",
    "workspace.requestMoreEvidence": "طلب مزيد من الأدلة",
    "workspace.generateReport": "إنشاء التقرير",
    "workspace.noReviewActions": "لا توجد إجراءات مراجعة بعد.",
    "workspace.finalReport": "التقرير النهائي",
    "workspace.noReportGenerated": "لم يتم إنشاء تقرير",
    "workspace.reportPending": "إنشاء التقرير يأتي بعد التفسير المعتمد من المراجع.",
    "workspace.finalizeReport": "اعتماد التقرير",
    "workspace.downloadPdf": "تنزيل PDF",
    "workspace.caseTimeline": "الخط الزمني للحالة",
    "workspace.auditReconstructable": "يمكن إعادة بناء كل إجراء مهم.",
    "workspace.noAuditEvents": "لا توجد أحداث تدقيق بعد",
    "workspace.exportHistory": "تصدير سجل الحالة الكامل",
    "workspace.export": "التصدير",
    "workspace.status": "الحالة",
    "workspace.downloadHistoryZip": "تنزيل ملف ZIP لسجل الحالة",
    "workspace.ready": "جاهز",
    "workspace.notSelected": "غير محدد",
    "workspace.created": "تم الإنشاء",
    "workspace.new": "جديد",
    "workspace.loading": "جارٍ التحميل…",
    "workspace.checkingBackend": "جارٍ فحص الخادم الخلفي…",
    "workspace.backendConnected": "الخادم الخلفي متصل",
    "workspace.reconnecting": "جارٍ إعادة الاتصال",
    "workspace.reviewRevision": "مراجعة الإصدار",
    "workspace.noClassification": "لا يوجد تصنيف",
    "workspace.noAutomatedRationale": "لا يوجد تبرير آلي مسجل.",
    "workspace.reportArtifact": "التفسير متاح في أثر التقرير.",
    "workspace.queued": "في قائمة الانتظار",
    "workspace.caseAndVcfFirst": "أنشئ/اختر حالة واختر VCF أولًا.",
    "workspace.errorLoadCase": "تعذر تحميل الحالة.",
    "workspace.errorCompleteReport": "تعذر تحميل تقرير المتغيرات الكامل.",
    "workspace.errorExportState": "تعذر قراءة حالة التصدير.",
    "workspace.errorVariantDetails": "تعذر تحميل تفاصيل المتغير.",
    "workspace.caseCreated": "تم إنشاء الحالة.",
    "workspace.caseLoaded": "تم تحميل الحالة الموجودة.",
    "workspace.caseCreationFailed": "فشل إنشاء الحالة.",
    "workspace.caseSpecimenRequired": "يلزم إدخال معرّف الحالة ومعرّف العينة.",
    "workspace.specimenRegistered": "تم تسجيل العينة للحالة.",
    "workspace.specimenRegistrationFailed": "فشل تسجيل العينة.",
    "workspace.specimenRequired": "سجّل عينة أو اخترها قبل رفع VCF.",
    "workspace.uploadFailed": "فشل الرفع.",
    "workspace.downloadFailed": "فشل التنزيل.",
    "workspace.caseVcfRequired": "يلزم وجود حالة وملف VCF مرفوع.",
    "workspace.analysisQueued": "تم وضع التحليل في قائمة التنفيذ. يمكنك إغلاق المتصفح؛ التنفيذ يتم على الخادم.",
    "workspace.analysisStartFailed": "فشل بدء التحليل.",
    "workspace.reviewStarted": "بدأت المراجعة.",
    "workspace.reviewReasonRequired": "يلزم إدخال سبب للمراجعة.",
    "workspace.reasonRequired": "يلزم إدخال سبب.",
    "workspace.moreEvidenceRequested": "تم طلب مزيد من الأدلة؛ يظل التصنيف معلقًا.",
    "workspace.approvalReasonRequired": "يلزم إدخال سبب للموافقة.",
    "workspace.classificationApproved": "تم اعتماد التصنيف.",
    "workspace.finalReportApproved": "اعتمد المراجع التقرير النهائي.",
    "workspace.reportFinalized": "تم اعتماد التقرير نهائيًا.",
    "workspace.reportFinalizationFailed": "فشل اعتماد التقرير نهائيًا.",
    "workspace.exportQueued": "تم وضع تصدير سجل الحالة الكامل في قائمة الانتظار. وهو مستقل عن جلسة المتصفح.",
    "workspace.exportFailed": "فشل تصدير الحالة.",
    "workspace.backendReconnectingPrefix": "جارٍ إعادة اتصال الخادم الخلفي: ",
    "workspace.connectionUnavailable": "الاتصال غير متاح",
    "workspace.inputRegisteredPrefix": "تم تسجيل الإدخال. SHA-256: ",
    "workspace.downloadFailedPrefix": "فشل التنزيل: ",
    "workspace.variantsCount": "متغيرات",
    "workspace.rowsCount": "صفوف",
    "workspace.eventsCount": "أحداث",
    "workspace.unknown": "غير معروف",
    "workspace.noData": "لا توجد بيانات",
    "workspace.evidence": "دليل",
    "workspace.unknownSource": "مصدر غير معروف",
    "workspace.unversioned": "بدون إصدار",
    "workspace.service": "الخدمة 01",
    "workspace.pipeline": "خط المعالجة",
    "workspace.caseSection": "الحالة",
    "workspace.caseId": "معرّف الحالة",
    "workspace.specimenSection": "العينة",
    "workspace.blood": "دم",
    "workspace.saliva": "لعاب",
    "workspace.buccal": "مسحة شدقية",
    "workspace.other": "أخرى",
    "workspace.inputSection": "الإدخال",
    "workspace.phaseOne": "المرحلة 1",
    "workspace.choose": "اختيار",
    "workspace.artifactId": "معرّف الأثر",
    "workspace.executionSection": "التنفيذ",
    "workspace.interpretationSection": "التفسير",
    "workspace.position": "الموضع",
    "workspace.refAlt": "المرجع / البديل",
    "workspace.build": "البناء",
    "workspace.review": "المراجعة",
    "workspace.selected": "محدد",
    "workspace.open": "فتح",
    "workspace.evidenceSection": "الأدلة",
    "workspace.reviewSection": "المراجعة",
    "workspace.decisionHistory": "سجل القرارات",
    "workspace.reportSection": "التقرير",
    "workspace.auditSection": "التدقيق وسلسلة المصدر",
    "workspace.auditLead": "تُحفظ الخطوات الحاسوبية والموارد والأدلة وإجراءات المراجعين وأحداث التقارير في سجل الحالة.",
    "workspace.footer": "تظل النتائج العلمية خاضعة للموارد المهيأة والمراجعة ونطاق التحقق وحوكمة المختبر.",
    "reports.validationDisclaimer": "يختلف التحقق من برنامج SIRALOOM عن التحقق السريري للمختبر أو الاعتماد أو الترخيص التنظيمي. ويظل الإصدار خاضعاً للموقّع المؤهل في المختبر وسياساته ومتطلبات الاختصاص القضائي.",
  },
};
