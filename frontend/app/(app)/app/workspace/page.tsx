"use client";

import Link from "next/link";
import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { firebaseAuth } from "../../../../lib/firebase";
import { useLanguage } from "../../../../lib/i18n";
import { isWorkspaceCaseReady } from "../../../../lib/workspace-context.mjs";
import { validatedArtifactId } from "../../../../lib/validated-upload.mjs";
import { canFinalizeClinicalReports, canSubmitReportSignout } from "../../../../lib/report-permissions.mjs";

type Step = {
  step_id: string;
  status: string;
  attempt: number;
  last_heartbeat?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  metadata?: Record<string, unknown>;
};

type Variant = {
  variant_id: string;
  genome_build: string;
  chromosome: string;
  position: number;
  reference: string;
  alternate: string;
};

type ReviewBundle = {
  review_status: string;
  classification?: {
    id?: string;
    result?: string;
    state?: string;
    review_status?: string;
    version?: number;
    review_version?: number;
  } | null;
  criteria: Array<{
    criterion: string;
    automated?: Record<string, unknown> | null;
    reviewed?: Record<string, unknown> | null;
    final?: Record<string, unknown> | null;
    state: string;
  }>;
  history: Array<{
    sequence_number?: number;
    action_type: string;
    reason: string;
    resulting_version?: number;
    created_at?: string;
  }>;
  variant_context?: {
    gene_disease?: Array<Record<string, unknown>>;
    phenotype_evidence?: Array<Record<string, unknown>>;
    literature?: Array<Record<string, unknown>>;
    functional_computational?: Array<Record<string, unknown>>;
    segregation?: Array<Record<string, unknown>>;
  };
};

type CaseWorkspace = {
  case_id: string;
  case_identifier: string;
  status: string;
  language: string;
  clinical_context: Record<string, unknown>;
  specimens: Array<Record<string, unknown> & { metadata?: Record<string, unknown> }>;
  analyses: Array<Record<string, unknown>>;
  assays?: Array<{ assay_id: string; name: string; version: string; assay_type: string; has_qc_rules: boolean }>;
};

type NotificationItem = { notification_id: string; notification_type: string; status: string; title: string; body: string; case_id?: string | null; analysis_id?: string | null; candidate_id?: string | null; metadata?: Record<string, unknown>; created_at?: string; read_at?: string | null; };
type CaseArtifact = { artifact_id: string; filename: string; artifact_type: string; size_bytes: number; sha256: string; genome_build?: string | null; validation_status?: string | null; metadata?: Record<string, unknown>; created_at?: string; specimen_id?: string | null; paired_artifact_id?: string | null; };

type AuditEvent = {
  event_id: string;
  event_type: string;
  analysis_id?: string | null;
  actor_type?: string;
  actor_id?: string;
  subject_type?: string | null;
  subject_id?: string | null;
  operation?: string | null;
  before_state?: Record<string, unknown> | null;
  after_state?: Record<string, unknown> | null;
  reason?: string | null;
  input_artifacts?: Array<Record<string, unknown>>;
  output_artifacts?: Array<Record<string, unknown>>;
  software?: Record<string, unknown>;
  workflow?: Record<string, unknown>;
  resource_versions?: Record<string, unknown>;
  occurred_at?: string;
};

type CompleteVariantRow = Record<string, string | number | null>;

type VariantDetail = {
  variant: Record<string, unknown>;
  annotations: Array<Record<string, unknown>>;
  population: Array<Record<string, unknown>>;
  evidence: Array<Record<string, unknown>>;
  acmg: Array<Record<string, unknown>>;
  classifications: Array<Record<string, unknown>>;
};

const API_BASE = (process.env.NEXT_PUBLIC_SIRALOOM_API_BASE ?? "http://localhost:8000/api/v1").replace(/\/$/, "");

const steps = [
  ["validate_input", "workflow.inputValidation"],
  ["normalize", "workflow.normalization"],
  ["annotate", "workflow.annotation"],
  ["population", "workflow.population"],
  ["build_evidence", "workflow.evidence"],
  ["acmg_assessment", "workflow.acmg"],
  ["review", "workflow.humanReview"],
  ["reportability", "workflow.reportability"],
  ["report", "workflow.report"],
  ["export_provenance", "workflow.caseHistory"],
] as const;

async function apiFetch(path: string, init?: RequestInit) {
  const token = await firebaseAuth?.currentUser?.getIdToken();
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!response.ok) {
    const message = typeof body === "object" && body && "detail" in body ? String((body as { detail: unknown }).detail) : `HTTP ${response.status}`;
    throw new Error(message);
  }
  return body as any;
}

function prettyStatus(status: string) {
  return status.toLowerCase().replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function statusTone(status: string) {
  if (["SUCCEEDED", "FINAL", "APPROVED", "COMPLETED"].includes(status)) return "success";
  if (["FAILED", "BLOCKED", "CANCELLED", "RESOURCE_FAILURE"].includes(status)) return "danger";
  if (["RUNNING", "QUEUED", "RETRYING", "IN_REVIEW", "PENDING"].includes(status)) return "active";
  return "neutral";
}

function formatBytes(value?: number) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "—";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let amount = value / 1024;
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) { amount /= 1024; index += 1; }
  return `${amount.toFixed(amount >= 100 ? 0 : amount >= 10 ? 1 : 2)} ${units[index]}`;
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

function nextActionHref(nextStep?: string | null) {
  if (nextStep === "review" || nextStep === "HUMAN_REVIEW_REQUIRED") return "/app/review";
  if (nextStep === "reportability" || nextStep === "report_finalization" || nextStep === "REPORTABILITY_REQUIRED") return "/app/reports";
  if (
    nextStep === "VALID_VCF_REQUIRED" ||
    nextStep === "SUPPORTED_INPUT_REQUIRED"
  ) return "/app/cases";
  if (
    nextStep === "REFERENCE_REQUIRED" ||
    nextStep === "REFERENCE_PACKAGE_REQUIRED" ||
    nextStep === "REFERENCE_PACKAGE_NOT_FOUND" ||
    nextStep === "ANNOTATION_PROVIDER_REQUIRED" ||
    nextStep === "POPULATION_RESOURCE_REQUIRED" ||
    nextStep === "RESOURCE_REQUIRED"
  ) return "/app/resources";
  return null;
}


export default function Home() {
  const { language, t } = useLanguage();
  const [caseId, setCaseId] = useState("");
  const [caseIdentifier, setCaseIdentifier] = useState("");
  const [caseWorkspace, setCaseWorkspace] = useState<CaseWorkspace | null>(null);
  const [caseLoadError, setCaseLoadError] = useState("");
  const [caseLoadAttempt, setCaseLoadAttempt] = useState(0);
  const caseIdRef = useRef("");
  const [specimenIdentifier, setSpecimenIdentifier] = useState("");
  const [specimenType, setSpecimenType] = useState("Blood");
  const [vcfSampleName, setVcfSampleName] = useState("");
  const [selectedSpecimenId, setSelectedSpecimenId] = useState("");
  const [genomeBuild, setGenomeBuild] = useState("GRCh38");
  const [resourceProfileId, setResourceProfileId] = useState("WES_GRCh38_STANDARD");
  const [assayId, setAssayId] = useState("");
  const [preflightResult, setPreflightResult] = useState<any>(null);
  const [indication, setIndication] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [artifactId, setArtifactId] = useState("");
  const [caseArtifacts, setCaseArtifacts] = useState<CaseArtifact[]>([]);
  const [analysisId, setAnalysisId] = useState("");
  const [analysis, setAnalysis] = useState<any>(null);
  const [variants, setVariants] = useState<Variant[]>([]);
  const [completeVariants, setCompleteVariants] = useState<CompleteVariantRow[]>([]);
  const [completeVariantColumns, setCompleteVariantColumns] = useState<string[]>([]);
  const [selectedVariantId, setSelectedVariantId] = useState("");
  const [variantDetail, setVariantDetail] = useState<VariantDetail | null>(null);
  const [review, setReview] = useState<ReviewBundle | null>(null);
  const [reportId, setReportId] = useState("");
  const [report, setReport] = useState<any>(null);
  const [reportSignoutReason, setReportSignoutReason] = useState("");
  const [sessionRole, setSessionRole] = useState<string | null>(null);
  const [sessionRoleResolved, setSessionRoleResolved] = useState(false);
  const [exportId, setExportId] = useState("");
  const [exportStatus, setExportStatus] = useState("");
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [expandedAuditId, setExpandedAuditId] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
  const [connection, setConnection] = useState<"checking" | "online" | "offline">("checking");
  const [message, setMessage] = useState("");
  const [reviewReason, setReviewReason] = useState("");
  const [gateStepId, setGateStepId] = useState("");
  const [gateDecision, setGateDecision] = useState<"ACCEPT" | "OVERRIDE" | "REQUEST_MORE_EVIDENCE" | "REJECT_AND_RETRY">("ACCEPT");
  const [gateReason, setGateReason] = useState("");
  const [gateInputsChanged, setGateInputsChanged] = useState(false);
  const [pollingEpoch, setPollingEpoch] = useState(0);
  const [criterionReason, setCriterionReason] = useState("");
  const [criterionStrengths, setCriterionStrengths] = useState<Record<string, string>>({});
  const [manualClassificationResult, setManualClassificationResult] = useState("VUS");
  const [manualClassificationReason, setManualClassificationReason] = useState("");
  const [manualClassificationEvidenceId, setManualClassificationEvidenceId] = useState("");
  const [expandedEvidence, setExpandedEvidence] = useState<string | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  caseIdRef.current = caseId;

  const currentStepIndex = useMemo(() => {
    const stepsFromApi: Step[] = analysis?.steps ?? [];
    let last = -1;
    steps.forEach(([id], index) => {
      const current = stepsFromApi.find((step) => step.step_id === id);
      if (current && ["SUCCEEDED", "RUNNING", "REQUIRES_REVIEW", "FAILED", "BLOCKED", "RESOURCE_FAILURE"].includes(current.status)) last = index;
    });
    return last;
  }, [analysis]);

  const waitingGates = useMemo(() => ((analysis?.steps as Step[] | undefined) ?? []).filter(step => step.status === "REQUIRES_REVIEW"), [analysis]);

  const capacityPreflight = preflightResult?.capacity_preflight ?? analysis?.capacity_preflight;

  const resourceStageReadiness = useMemo(() => ((analysis?.steps as Step[] | undefined) ?? []).flatMap(step => {
    const raw = step.metadata?.resource_readiness;
    if (!raw || typeof raw !== "object") return [];
    const readiness = raw as Record<string, any>;
    return [{ step_id: step.step_id, status: String(readiness.status ?? "UNKNOWN"), issues: Array.isArray(readiness.issues) ? readiness.issues : [], selected: Array.isArray(readiness.selected) ? readiness.selected : [] }];
  }), [analysis]);

  const preflightIssues = useMemo(() => {
    const fromStart = preflightResult?.resource_issues;
    if (Array.isArray(fromStart) && fromStart.length) return fromStart;
    const found = new Map<string, any>();
    for (const stage of resourceStageReadiness) for (const issue of stage.issues) found.set(`${issue.capability}:${issue.code}`, issue);
    return Array.from(found.values());
  }, [preflightResult, resourceStageReadiness]);

  const stepStatusSignature = useMemo(() => ((analysis?.steps as Step[] | undefined) ?? []).map(step => `${step.step_id}:${step.status}:${step.attempt}`).join("|"), [analysis]);
  const manualClassificationEvidence = useMemo(() => {
    const context = review?.variant_context;
    const groups = [
      ...(context?.gene_disease ?? []),
      ...(context?.phenotype_evidence ?? []),
      ...(context?.literature ?? []),
      ...(context?.functional_computational ?? []),
      ...(context?.segregation ?? []),
    ];
    const unique = new Map<string, Record<string, unknown>>();
    for (const item of groups) {
      const id = typeof item.id === "string" ? item.id : "";
      if (id) unique.set(id, item);
    }
    return Array.from(unique.values());
  }, [review]);


  const annotationProgress = useMemo(() => {
    const annotation = (analysis?.steps as Step[] | undefined)?.find((step) => step.step_id === "annotate");
    const batches = annotation?.metadata?.batches;
    if (!batches || typeof batches !== "object") return null;
    const values = Object.values(batches as Record<string, unknown>).filter((value): value is Record<string, unknown> => !!value && typeof value === "object");
    const completed = values.filter((value) => value.status === "SUCCEEDED").length;
    return { completed, total: values.length };
  }, [analysis]);

  useEffect(() => {
    const queryCase = new URLSearchParams(window.location.search).get("case") ?? "";
    const storedCase = queryCase || window.localStorage.getItem("siraloom.case_id") || "";
    const storedAnalysis = window.localStorage.getItem("siraloom.analysis_id") ?? "";
    const storedCaseIdentifier = window.localStorage.getItem("siraloom.case_identifier") ?? "";
    if (queryCase) window.localStorage.setItem("siraloom.case_id", queryCase);
    if (storedCase) {
      setCaseId(storedCase);
    } else if (storedAnalysis) {
      // An analysis-only deep link remains supported, but the case is authoritative
      // once a case context exists. The case effect below will reconcile the ID.
      setAnalysisId(storedAnalysis);
    }
    if (storedCaseIdentifier) setCaseIdentifier(storedCaseIdentifier);
    apiFetch("/health")
      .then(() => setConnection("online"))
      .catch(() => setConnection("offline"));
  }, []);

  useEffect(() => {
    let active = true;
    apiFetch("/auth/session")
      .then((session) => {
        if (active) setSessionRole(typeof session?.role === "string" ? session.role : null);
      })
      .catch(() => {
        if (active) setSessionRole(null);
      })
      .finally(() => {
        if (active) setSessionRoleResolved(true);
      });
    return () => { active = false; };
  }, []);

  const refreshCaseArtifacts = useCallback(async () => {
    if (!caseId) return;
    try {
      const rows = await apiFetch(`/cases/${caseId}/artifacts`);
      if (caseIdRef.current === caseId) setCaseArtifacts(Array.isArray(rows) ? rows : []);
    } catch (error) {
      if (caseIdRef.current === caseId) setMessage(error instanceof Error ? error.message : t("workspace.errorLoadCase"));
    }
  }, [caseId, t]);

  useEffect(() => { void refreshCaseArtifacts(); }, [refreshCaseArtifacts, stepStatusSignature]);

  useEffect(() => {
    if (!caseId) return;
    let cancelled = false;
    setCaseLoadError("");
    setCaseWorkspace(null);
    setAnalysisId("");
    setAnalysis(null);
    setVariants([]);
    setCompleteVariants([]);
    setCompleteVariantColumns([]);
    setSelectedVariantId("");
    setVariantDetail(null);
    setReview(null);
    setReportId("");
    setReport(null);
    setExportId("");
    setExportStatus("");
    setAuditEvents([]);
    setCaseArtifacts([]);
    setArtifactId("");
    setSelectedSpecimenId("");
    setPreflightResult(null);
    setMessage("");
    const loadCase = async () => {
      try {
        const data = await apiFetch(`/cases/${caseId}`);
        if (cancelled) return;
        setCaseWorkspace(data);
        setCaseIdentifier(String(data?.case_identifier ?? ""));
        window.localStorage.setItem("siraloom.case_identifier", String(data?.case_identifier ?? ""));
        const specimens = Array.isArray(data?.specimens) ? data.specimens : [];
        const assays = Array.isArray(data?.assays) ? data.assays : [];
        setAssayId(assays.find((assay: any) => assay.has_qc_rules)?.assay_id ?? "");
        // A case deep-link must not retain a specimen or input artifact from the previously open case.
        setSelectedSpecimenId(specimens.length ? String(specimens[0].specimen_id) : "");
        setArtifactId("");
        const indicationValue = data?.clinical_context?.indication;
        if (typeof indicationValue === "string") setIndication(indicationValue);

        // The selected case is authoritative. Preserve an explicitly selected
        // analysis only when it belongs to this case; otherwise fall back to latest.
        const availableAnalyses = Array.isArray(data?.analyses) ? data.analyses : [];
        const requestedAnalysisId = window.localStorage.getItem("siraloom.analysis_id") ?? "";
        const selectedAnalysis = availableAnalyses.find((item: any) => String(item.analysis_id) === requestedAnalysisId)
          ?? availableAnalyses[0]
          ?? null;
        if (selectedAnalysis?.analysis_id) {
          const nextAnalysisId = String(selectedAnalysis.analysis_id);
          setAnalysisId(nextAnalysisId);
          window.localStorage.setItem("siraloom.analysis_id", nextAnalysisId);
        } else {
          setAnalysisId("");
          window.localStorage.removeItem("siraloom.analysis_id");
        }
      } catch (error) {
        if (cancelled) return;
        setCaseLoadError(error instanceof Error ? error.message : t("workspace.errorLoadCase"));
        setMessage(error instanceof Error ? error.message : t("workspace.errorLoadCase"));
      }
    };
    loadCase();
    return () => { cancelled = true; };
  }, [caseId, caseLoadAttempt, t]);

  useEffect(() => {
    if (!analysisId || !["SUCCEEDED", "REQUIRES_REVIEW"].includes(analysis?.status ?? "")) {
      setCompleteVariants([]);
      setCompleteVariantColumns([]);
      return;
    }
    let cancelled = false;
    apiFetch(`/analyses/${analysisId}/complete-variant-report`)
      .then((data) => {
        if (cancelled) return;
        setCompleteVariants(data.variants ?? []);
        setCompleteVariantColumns(data.columns ?? []);
      })
      .catch((error) => { if (!cancelled) setMessage(error instanceof Error ? error.message : t("workspace.errorCompleteReport")); });
    return () => { cancelled = true; };
  }, [analysisId, analysis?.status]);

  useEffect(() => {
    if (!analysisId) return;
    let cancelled = false;
    const loadAudit = async () => {
      try {
        const events = await apiFetch(`/cases/${caseId}/audit`);
        if (!cancelled) setAuditEvents(events);
      } catch {
        // Audit view is observational; analysis state remains authoritative.
      }
    };
    loadAudit();
    const timer = setInterval(loadAudit, 4000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [caseId, analysisId]);

  useEffect(() => {
    if (!analysisId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const next = await apiFetch(`/analyses/${analysisId}`);
        if (cancelled) return;
        setAnalysis(next);
        setConnection("online");
        const terminal = ["SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED", "REQUIRES_REVIEW", "RESOURCE_FAILURE"].includes(next.status);
        if (terminal && pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
        if (["SUCCEEDED", "REQUIRES_REVIEW"].includes(next.status)) {
          try {
            const vs = await apiFetch(`/analyses/${analysisId}/variants`);
            if (cancelled) return;
            setVariants(vs);
            if (!selectedVariantId && vs.length) setSelectedVariantId(vs[0].variant_id);
          } catch {
            // Variant table can be unavailable during an intermediate step; the analysis state remains authoritative.
          }
        }
      } catch (error) {
        if (cancelled) return;
        setConnection("offline");
        setMessage(`${t("workspace.backendReconnectingPrefix")}${error instanceof Error ? error.message : t("workspace.connectionUnavailable")}`);
      }
    };
    poll();
    pollingRef.current = setInterval(poll, 2000);
    return () => {
      cancelled = true;
      if (pollingRef.current) clearInterval(pollingRef.current);
      pollingRef.current = null;
    };
  }, [analysisId, selectedVariantId, pollingEpoch]);

  useEffect(() => {
    if (!exportId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;
    const pollExport = async () => {
      try {
        const result = await apiFetch(`/exports/${exportId}`);
        if (cancelled) return;
        setExportStatus(result.status);
        if (["SUCCEEDED", "FAILED", "CANCELLED"].includes(result.status) && timer) {
          clearInterval(timer);
          timer = null;
        }
      } catch (error) {
        if (cancelled) return;
        setMessage(error instanceof Error ? error.message : t("workspace.errorExportState"));
      }
    };
    pollExport();
    timer = setInterval(pollExport, 2000);
    return () => { cancelled = true; if (timer) clearInterval(timer); };
  }, [exportId]);

  useEffect(() => {
    if (!analysisId || !selectedVariantId) return;
    let cancelled = false;
    const load = async () => {
      try {
        const [detail, reviewBundle] = await Promise.all([
          apiFetch(`/variants/${selectedVariantId}?analysis_id=${analysisId}`),
          apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/review`).catch(() => null),
        ]);
        if (cancelled) return;
        setVariantDetail(detail);
        setReview(reviewBundle);
      } catch (error) {
        if (cancelled) return;
        setMessage(error instanceof Error ? error.message : t("workspace.errorVariantDetails"));
      }
    };
    load();
    return () => { cancelled = true; };
  }, [analysisId, selectedVariantId]);

  const loadNotifications = async () => {
    try {
      const data = await apiFetch("/notifications");
      setNotifications(Array.isArray(data) ? data : []);
    } catch {
      // Notification polling is observational; workflow state remains authoritative.
    }
  };

  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const data = await apiFetch("/notifications");
        if (!cancelled) setNotifications(Array.isArray(data) ? data : []);
      } catch {
        // Notifications are durable advisory state; a temporary read failure
        // must not alter or mask the authoritative analysis workflow state.
      }
    };
    refresh();
    const timer = setInterval(refresh, 15000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const requestReanalysis = async () => {
    if (!analysisId || analysis?.status !== "SUCCEEDED") return;
    setBusy(true);
    setMessage("");
    try {
      const result = await apiFetch(`/analyses/${analysisId}/reanalysis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reason: "Laboratory-requested case-level reanalysis.",
        }),
      });
      setAnalysisId(result.analysis_id);
      window.localStorage.setItem("siraloom.analysis_id", result.analysis_id);
      setMessage(`Reanalysis v${result.analysis_version} queued from the completed parent analysis.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to start reanalysis.");
    } finally {
      setBusy(false);
    }
  };

  const executeCandidateReanalysis = async (item: NotificationItem) => {
    if (!item.candidate_id) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await apiFetch(`/reanalysis/candidates/${item.candidate_id}/execute`, {
        method: "POST",
      });
      setAnalysisId(result.analysis_id);
      window.localStorage.setItem("siraloom.analysis_id", result.analysis_id);
      await markNotificationRead(item.notification_id);
      setMessage(`Reanalysis v${result.analysis_version} queued from the completed parent analysis.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to start change-aware reanalysis.");
    } finally {
      setBusy(false);
    }
  };

  const markNotificationRead = async (notificationId: string) => {
    try {
      await apiFetch(`/notifications/${notificationId}/read`, { method: "POST" });
      setNotifications((current) => current.map((item) => item.notification_id === notificationId ? { ...item, status: "READ" } : item));
    } catch {
      // Keep the notification visible if the read operation fails.
    }
  };

  const createCase = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const result = await apiFetch("/cases", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          case_identifier: caseIdentifier.trim(),
          language,
          clinical_context: { indication: indication.trim() },
        }),
      });
      setCaseId(result.case_id);
      window.localStorage.setItem("siraloom.case_id", result.case_id);
      window.localStorage.setItem("siraloom.case_identifier", result.case_identifier);
      setMessage(result.created ? t("workspace.caseCreated") : t("workspace.caseLoaded"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t("workspace.caseCreationFailed"));
    } finally {
      setBusy(false);
    }
  };

  const registerSpecimen = async () => {
    if (!caseId || !specimenIdentifier.trim() || !vcfSampleName.trim()) {
      setMessage(t("workspace.caseSpecimenRequired"));
      return;
    }
    setBusy(true);
    try {
      const next = await apiFetch(`/cases/${caseId}/specimens`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ specimen_identifier: specimenIdentifier.trim(), specimen_type: specimenType, vcf_sample_name: vcfSampleName.trim() }),
      });
      const refreshed = await apiFetch(`/cases/${caseId}`);
      setCaseWorkspace(refreshed);
      setSelectedSpecimenId(String(next.specimen_id));
      setSpecimenIdentifier("");
      setVcfSampleName("");
      setMessage(t("workspace.specimenRegistered"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t("workspace.specimenRegistrationFailed"));
    } finally {
      setBusy(false);
    }
  };

  const uploadFile = async () => {
    if (!caseId || !file) {
      setMessage(t("workspace.caseAndVcfFirst"));
      return;
    }
    if (!selectedSpecimenId) {
      setMessage(t("workspace.specimenRequired"));
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const form = new FormData();
      form.append("file", file, file.name);
      form.append("specimen_id", selectedSpecimenId);
      form.append("genome_build", genomeBuild);
      const result = await apiFetch(`/cases/${caseId}/artifacts`, { method: "POST", body: form });
      const validatedId = validatedArtifactId(result);
      setArtifactId(validatedId);
      await refreshCaseArtifacts();
      if (!validatedId) {
        const validationErrors = Array.isArray(result.validation?.errors) ? result.validation.errors.join(" ") : "";
        setMessage(`${t("workspace.inputValidationFailedPrefix")}${validationErrors}`);
      } else {
        const warnings = Array.isArray(result.validation?.warnings) ? result.validation.warnings.join(" ") : "";
        setMessage(`${t("workspace.inputRegisteredPrefix")}${result.sha256}${warnings ? ` · ${warnings}` : ""}`);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t("workspace.uploadFailed"));
    } finally {
      setBusy(false);
    }
  };

  const downloadAuthenticated = async (path: string, filename: string) => {
    try {
      const token = await firebaseAuth?.currentUser?.getIdToken();
      const response = await fetch(`${API_BASE}${path}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) {
        const body = await response.text();
        let detail = `HTTP ${response.status}`;
        try { const parsed = body ? JSON.parse(body) : null; if (parsed?.detail) detail = String(parsed.detail); } catch {}
        throw new Error(detail);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      setMessage(error instanceof Error ? `Download failed: ${error.message}` : t("workspace.downloadFailed"));
    }
  };

  const createAndStart = async () => {
    if (!caseId || !artifactId) {
      setMessage(t("workspace.caseVcfRequired"));
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const created = await apiFetch(`/cases/${caseId}/analyses`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          input_artifact_id: artifactId,
          assay_id: assayId || null,
          analysis_type: "VARIANT_INTERPRETATION",
          workflow_id: "variant-v1",
          workflow_version: "2.1",
          reference_build: genomeBuild,
          resource_profile_id: resourceProfileId,
        }),
      });
      setAnalysisId(created.analysis_id);
      window.localStorage.setItem("siraloom.analysis_id", created.analysis_id);
      const started = await apiFetch(`/analyses/${created.analysis_id}/start`, { method: "POST" });
      setPreflightResult(started);
      const current = await apiFetch(`/analyses/${created.analysis_id}`);
      setAnalysis(current);
      setPollingEpoch(epoch => epoch + 1);
      if (started.status === "BLOCKED" || started.resource_plan_status === "BLOCKED") {
        const issueText = (started.resource_issues ?? []).map((issue: any) => `${issue.capability}: ${issue.message}`).join(" · ");
        setMessage(issueText ? `${t("workspace.preflightBlocked")}: ${issueText}` : t("workspace.preflightBlocked"));
      } else {
        setMessage(t("workspace.analysisQueued"));
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t("workspace.analysisStartFailed"));
    } finally {
      setBusy(false);
    }
  };

  const startReview = async () => {
    if (!analysisId || !selectedVariantId) return;
    try {
      await apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/review/start`, { method: "POST" });
      const next = await apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/review`);
      setReview(next);
      setMessage(t("workspace.reviewStarted"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to start review.");
    }
  };

  const proposeManualClassification = async () => {
    if (!analysisId || !selectedVariantId || !manualClassificationReason.trim() || !manualClassificationEvidenceId) {
      setMessage(t("workspace.manualClassificationEvidenceRequired"));
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      await apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/classification/manual`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          result: manualClassificationResult,
          reason: manualClassificationReason.trim(),
          evidence_ids: [manualClassificationEvidenceId],
        }),
      });
      const next = await apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/review`);
      setReview(next);
      setManualClassificationReason("");
      setManualClassificationEvidenceId("");
      setMessage(t("workspace.manualClassificationSaved"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t("workspace.manualClassificationFailed"));
    } finally {
      setBusy(false);
    }
  };

  const reviewCriterion = async (criterion: string, decision: "ACCEPT" | "REJECT") => {
    const current = review?.criteria.find((item) => item.criterion === criterion);
    const expectedVersion = Number((current as any)?.review_version ?? 0);
    const strength = criterionStrengths[criterion] ?? "";
    if (!analysisId || !selectedVariantId || !criterionReason.trim() || (decision === "ACCEPT" && !strength)) {
      setMessage(!criterionReason.trim() ? t("workspace.reviewReasonRequired") : t("review.strengthRequired"));
      return;
    }
    try {
      await apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/acmg/${criterion}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          decision,
          strength: decision === "ACCEPT" ? strength : null,
          reason: criterionReason.trim(),
          evidence_ids: [],
          expected_version: expectedVersion,
        }),
      });
      const next = await apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/review`);
      setReview(next);
      setCriterionReason("");
      if (decision === "ACCEPT") setCriterionStrengths((current) => ({ ...current, [criterion]: "" }));
      setMessage(`${criterion} review saved.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Criterion review failed.");
    }
  };

  const requestMoreEvidence = async () => {
    const version = Number(review?.classification?.review_version ?? 0);
    if (!analysisId || !selectedVariantId || !reviewReason.trim()) {
      setMessage(t("workspace.reasonRequired"));
      return;
    }
    try {
      await apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/review/more-evidence`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version: version, reason: reviewReason.trim() }),
      });
      const next = await apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/review`);
      setReview(next);
      setReviewReason("");
      setMessage(t("workspace.moreEvidenceRequested"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Request for more evidence failed.");
    }
  };

  const approve = async () => {
    const version = Number(review?.classification?.review_version ?? 0);
    if (!analysisId || !selectedVariantId || !reviewReason.trim()) {
      setMessage(t("workspace.approvalReasonRequired"));
      return;
    }
    try {
      await apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/review/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version: version, reason: reviewReason.trim() }),
      });
      const next = await apiFetch(`/analyses/${analysisId}/variants/${selectedVariantId}/review`);
      setReview(next);
      setReviewReason("");
      setMessage(t("workspace.classificationApproved"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Approval failed.");
    }
  };

  const generateReport = async () => {
    if (!analysisId) return;
    setBusy(true);
    try {
      const result = await apiFetch(`/analyses/${analysisId}/reports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ report_type: "CLINICAL_INTERPRETATION", language, include_full_evidence: false }),
      });
      setReportId(result.report_id);
      setReportSignoutReason("");
      const next = await apiFetch(`/reports/${result.report_id}`);
      setReport(next);
      setMessage(`Report draft ${result.version} generated.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Report generation failed.");
    } finally {
      setBusy(false);
    }
  };

  const finalize = async () => {
    if (!reportId || !report) return;
    if (!canSubmitReportSignout(sessionRole, reportSignoutReason)) {
      if (!canFinalizeClinicalReports(sessionRole)) {
        setMessage(t("workspace.reportSignoutRoleHelp"));
        return;
      }
      setMessage(t("workspace.reportSignoutReasonRequired"));
      return;
    }
    setBusy(true);
    try {
      const finalized = await apiFetch(`/reports/${reportId}/finalize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version: report.version, reason: reportSignoutReason.trim() }),
      });
      setReport((current: any) => current ? { ...current, status: finalized.status ?? "FINAL", approved_at: finalized.approved_at ?? current.approved_at } : current);
      try {
        const next = await apiFetch(`/reports/${reportId}`);
        setReport(next);
        setReportSignoutReason(next.signout_reason ?? reportSignoutReason.trim());
        setMessage(t("workspace.reportFinalized"));
      } catch {
        setMessage(t("workspace.reportRefreshFailed"));
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t("workspace.reportFinalizationFailed"));
    } finally {
      setBusy(false);
    }
  };

  const exportHistory = async () => {
    if (!caseId) return;
    try {
      const result = await apiFetch(`/cases/${caseId}/exports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ include_artifacts: true, include_reports: true, include_evidence: true, include_audit: true, include_provenance: true }),
      });
      setExportId(result.export_id);
      setMessage(t("workspace.exportQueued"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t("workspace.exportFailed"));
    }
  };

  const resolveGate = async () => {
    const gate = waitingGates.find(step => step.step_id === gateStepId);
    if (!analysisId || !gate || !gateReason.trim()) {
      setMessage(t("workspace.reasonRequired"));
      return;
    }
    if (gateDecision === "REJECT_AND_RETRY" && !gateInputsChanged) {
      setMessage(t("workspace.gateRetryNeedsChange"));
      return;
    }
    setBusy(true);
    try {
      const result = await apiFetch(`/analyses/${analysisId}/workflow/${encodeURIComponent(gate.step_id)}/human-gate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: gateDecision, reason: gateReason.trim(), expected_attempt: gate.attempt, inputs_changed: gateInputsChanged }),
      });
      setMessage(result.workflow_resume_queued ? t("workspace.gateResolved") : gateDecision === "REQUEST_MORE_EVIDENCE" ? t("workspace.moreEvidenceRequested") : t("workspace.gateResolved"));
      setGateReason("");
      setGateInputsChanged(false);
      setGateStepId("");
      const refreshed = await apiFetch(`/analyses/${analysisId}`);
      setAnalysis(refreshed);
      setPollingEpoch(epoch => epoch + 1);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t("workspace.analysisStartFailed"));
    } finally {
      setBusy(false);
    }
  };

  const handleFile = (event: ChangeEvent<HTMLInputElement>) => {
    setFile(event.target.files?.[0] ?? null);
    setArtifactId("");
  };

  const caseContextReady = isWorkspaceCaseReady(caseId, caseWorkspace?.case_id);
  if (caseId && !caseContextReady) {
    return (
      <main className="shell">
        <header className="topbar">
          <div>
            <div className="eyebrow">{t("workspace.eyebrow")}</div>
            <h1>SIRALOOM <span>{t("workflow.variantFile")}</span></h1>
          </div>
          <div className="connection"><span className={`dot ${connection}`} />{connection === "online" ? t("workspace.backendConnected") : connection === "checking" ? t("workspace.checkingBackend") : t("workspace.reconnecting")}</div>
        </header>
        <section className="panel" role={caseLoadError ? "alert" : "status"} aria-live="polite">
          <p>{caseLoadError || t("workspace.loading")}</p>
          {caseLoadError && <button type="button" className="secondary" onClick={() => { setCaseLoadError(""); setCaseLoadAttempt(attempt => attempt + 1); }}>{t("cases.refresh")}</button>}
        </section>
      </main>
    );
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">{t("workspace.eyebrow")}</div>
          <h1>SIRALOOM <span>{t("workflow.variantFile")}</span></h1>
          <p className="subtitle">{t("workspace.subtitle")}</p>
        </div>
        <div className="connection"><span className={`dot ${connection}`} />{connection === "online" ? t("workspace.backendConnected") : connection === "checking" ? t("workspace.checkingBackend") : t("workspace.reconnecting")}</div>
      </header>

      <section className="hero-grid">
        <div className="hero-card">
          <div className="hero-kicker">{t("workspace.service")}</div>
          <h2>{t("workspace.title")}</h2>
          <p>{t("workspace.lead")}</p>
        </div>
        <div className="metric-card"><span>{t("workspace.pipeline")}</span><strong>{analysis?.status ? prettyStatus(analysis.status) : t("workspace.ready")}</strong></div>
        <div className="metric-card"><span>{t("workflow.case")}</span><strong>{caseIdentifier || t("workspace.notSelected")}</strong></div>
      </section>

      <nav className="workspace-section-nav" aria-label={t("workspace.title")}>
        <a href="#case-intake">{t("workspace.caseSection")}</a>
        <a href="#analysis-workflow">{t("workspace.executionSection")}</a>
        <a href="#artifacts">{t("workspace.files")}</a>
        <a href="#variants">{t("workspace.interpretationSection")}</a>
        <a href="#variant-export">{t("workspace.completeReport")}</a>
        <a href="#evidence">{t("workspace.evidenceSection")}</a>
        <a href="#review">{t("workspace.reviewSection")}</a>
        <a href="#report">{t("workspace.reportSection")}</a>
        <a href="#audit">{t("workspace.auditSection")}</a>
      </nav>

      {message && <div className="notice" role="status">{message}</div>}

      {notifications.length > 0 && (
        <section className="panel">
          <div className="panel-head">
            <div><div className="section-kicker">{t("workspace.reanalysisTitle")}</div><h3>{t("workspace.reanalysisNotification")}</h3></div>
            <span className="badge neutral">{notifications.filter((item) => item.status === "UNREAD").length} unread</span>
          </div>
          <div className="stack">
            {notifications.slice(0, 8).map((item) => {
              const affected = item.metadata?.earliest_affected_step;
              return (
                <div key={item.notification_id} className="keyline">
                  <div>
                    <strong>{item.title}</strong>
                    <div>{item.body}</div>
                    {typeof affected === "string" && <small>{String(t("workspace.reanalysisAffected"))}: {prettyStatus(affected)}</small>}
                    <small>{formatDate(item.created_at)}</small>
                  </div>
                  <div className="actions-row">
                    {item.candidate_id && (
                      <button className="primary" onClick={() => executeCandidateReanalysis(item)} disabled={busy}>
                        {t("workspace.reanalysisRequest")}
                      </button>
                    )}
                    {item.status === "UNREAD" && (
                      <button className="secondary" onClick={() => markNotificationRead(item.notification_id)} disabled={busy}>
                        {t("workspace.markRead")}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {analysis?.status === "SUCCEEDED" && (
        <section className="panel">
          <div className="panel-head">
            <div><div className="section-kicker">{t("workspace.reanalysisTitle")}</div><h3>{t("workspace.reanalysisTitle")}</h3></div>
            <span className="badge success">Analysis v{String(analysis?.analysis_version ?? "1")}</span>
          </div>
          <p>{t("workspace.reanalysisLead")}</p>
          <button className="primary" onClick={requestReanalysis} disabled={busy}>{t("workspace.reanalysisRequest")}</button>
        </section>
      )}

      <section id="case-intake" className="workspace-grid">
        <aside className="panel case-panel">
          <div className="panel-head"><div><div className="section-kicker">{t("workspace.caseSection")}</div><h3>{t("workspace.startCase")}</h3></div><span className={`badge ${statusTone(caseId ? "SUCCEEDED" : "READY")}`}>{caseId ? t("workspace.created") : t("workspace.new")}</span></div>
          <form onSubmit={createCase} className="stack">
            <label>{t("workspace.caseIdentifier")}<input value={caseIdentifier} onChange={(e: ChangeEvent<HTMLInputElement>) => setCaseIdentifier(e.target.value)} placeholder="LVP-2026-000184" required /></label>
            <label>{t("workspace.clinicalIndication")}<input value={indication} onChange={(e: ChangeEvent<HTMLInputElement>) => setIndication(e.target.value)} placeholder="Hereditary cancer evaluation" /></label>
            <button className="primary" disabled={busy || !caseIdentifier.trim()}>{caseId ? "Load case" : "Create case"}</button>
          </form>
          {caseId && <div className="keyline"><span>{t("workspace.caseId")}</span><code>{caseId}</code></div>}
          {caseId && <div className="case-context">
            <div className="section-kicker">{t("workspace.specimenSection")}</div>
            <div className="specimen-form"><input value={specimenIdentifier} onChange={(e) => setSpecimenIdentifier(e.target.value)} placeholder="Specimen ID" /><input value={vcfSampleName} onChange={(e) => setVcfSampleName(e.target.value)} placeholder={t("workspace.vcfSampleName")} /><select value={specimenType} onChange={(e) => setSpecimenType(e.target.value)}><option>{t("workspace.blood")}</option><option>{t("workspace.saliva")}</option><option>{t("workspace.buccal")}</option><option>{t("workspace.other")}</option></select><button className="secondary" onClick={registerSpecimen} disabled={busy || !specimenIdentifier.trim() || !vcfSampleName.trim()}>{t("workspace.registerSpecimen")}</button></div>
            {caseWorkspace?.specimens?.map((specimen, index) => {
              const id = String(specimen.specimen_id ?? "");
              const selected = id && id === selectedSpecimenId;
              return (
                <button
                  type="button"
                  key={id || index}
                  className={`keyline specimen-row ${selected ? "selected-mini" : ""}`}
                  onClick={() => id && setSelectedSpecimenId(id)}
                >
                  <span>{String(specimen.specimen_type ?? "Specimen")}</span>
                  <strong>{String(specimen.specimen_identifier ?? "—")}{selected ? " · selected" : ""}{` · ${t("workspace.vcfSampleName")}: ${String(specimen.metadata?.vcf_sample_name ?? t("workspace.sampleNameUnavailable"))}`}</strong>
                </button>
              );
            })}
          </div>}
        </aside>

        <section className="panel input-panel">
          <div className="panel-head"><div><div className="section-kicker">{t("workspace.inputSection")}</div><h3>{t("workspace.vcfIntake")}</h3></div><span className="badge neutral">{t("workspace.phaseOne")}</span></div>
          <label>Specimen for this VCF
            <select value={selectedSpecimenId} onChange={(e) => setSelectedSpecimenId(e.target.value)}>
              <option value="">{t("workspace.selectSpecimen")}</option>
              {caseWorkspace?.specimens?.map((specimen, index) => (
                <option key={String(specimen.specimen_id ?? index)} value={String(specimen.specimen_id ?? "")}>
                  {String(specimen.specimen_identifier ?? "Specimen")} ({String(specimen.specimen_type ?? "—")}) · {String(specimen.metadata?.vcf_sample_name ?? t("workspace.sampleNameUnavailable"))}
                </option>
              ))}
            </select>
          </label>
          <label>{t("workspace.analysisProfile")}
            <select value={resourceProfileId} onChange={(e) => { const profile = e.target.value; setResourceProfileId(profile); setGenomeBuild(profile === "WES_GRCh37_STANDARD" ? "GRCh37" : "GRCh38"); }}>
              <option value="WES_GRCh38_STANDARD">{t("workspace.profileWes38")}</option>
              <option value="WGS_GRCh38_STANDARD">{t("workspace.profileWgs38")}</option>
              <option value="WES_GRCh37_STANDARD">{t("workspace.profileWes37")}</option>
            </select>
          </label>
          <label>Reference genome
            <select value={genomeBuild} onChange={(e) => { const build = e.target.value; setGenomeBuild(build); setResourceProfileId(build === "GRCh37" ? "WES_GRCh37_STANDARD" : resourceProfileId === "WGS_GRCh38_STANDARD" ? "WGS_GRCh38_STANDARD" : "WES_GRCh38_STANDARD"); }}>
              <option value="GRCh38">GRCh38</option>
              <option value="GRCh37">GRCh37</option>
            </select>
          </label>
          <label>{t("workspace.assayProfile")}
            <select value={assayId} onChange={(event) => setAssayId(event.target.value)}>
              <option value="">{t("workspace.noClinicalAssay")}</option>
              {(caseWorkspace?.assays ?? []).filter((assay) => assay.has_qc_rules).map((assay) => (
                <option key={assay.assay_id} value={assay.assay_id}>
                  {assay.name} · {assay.assay_type} · v{assay.version}
                </option>
              ))}
            </select>
            {!assayId && <small>{t("workspace.assayQcGateNotice")}</small>}
          </label>
          <div className="dropzone">
            <div className="drop-icon">VCF</div>
            <div><strong>{file?.name ?? "Choose a VCF / .vcf.gz / .vcf.bgz"}</strong><p>{t("workspace.inputPersisted")}</p></div>
            <label className="secondary file-button">{t("workspace.choose")}<input type="file" accept=".vcf,.vcf.gz,.vcf.bgz" onChange={handleFile} hidden /></label>
          </div>
          <div className="actions-row">
            <button className="secondary" onClick={uploadFile} disabled={busy || !caseId || !file || !selectedSpecimenId}>{t("workspace.registerInput")}</button>
            <button className="primary" onClick={createAndStart} disabled={busy || !caseId || !artifactId}>{t("workspace.startAnalysis")}</button>
          </div>
          {artifactId && <div className="keyline"><span>{t("workspace.artifactId")}</span><code>{artifactId}</code></div>}
        </section>

        <section id="analysis-workflow" className="panel workflow-panel">
          <div className="panel-head"><div><div className="section-kicker">{t("workspace.executionSection")}</div><h3>{t("workspace.durableWorkflow")}</h3></div>{analysis?.status && <span className={`badge ${statusTone(analysis.status)}`}>{prettyStatus(analysis.status)}</span>}</div>
          <div className="timeline">
            {steps.map(([id, label], index) => {
              const step = (analysis?.steps as Step[] | undefined)?.find((item) => item.step_id === id);
              const status = step?.status ?? (index <= currentStepIndex ? "SUCCEEDED" : "PENDING");
              return <div key={id} className={`timeline-row ${statusTone(status)} ${index === currentStepIndex ? "current" : ""}`}>
                <div className="timeline-mark">{status === "SUCCEEDED" ? "✓" : status === "FAILED" || status === "BLOCKED" ? "!" : index === currentStepIndex ? "•" : "○"}</div>
                <div className="timeline-label"><strong>{t(label)}</strong><span>{prettyStatus(status)}{step?.attempt ? ` · attempt ${step.attempt}` : ""}</span>{step?.error_message && <small>{step.error_message}</small>}</div>
              </div>;
            })}
          </div>
          {waitingGates.length > 0 && <div className="workflow-gate-panel">
            <div className="panel-head"><div><div className="section-kicker">{t("workspace.gateRequired")}</div><h4>{waitingGates.length} {t("workspace.gateRequired")}</h4></div><span className="badge active">Human action required</span></div>
            <div className="workflow-gate-list">{waitingGates.map(gate => <button type="button" key={gate.step_id} className={`workflow-gate-chip ${gateStepId === gate.step_id ? "selected" : ""}`} onClick={() => setGateStepId(gate.step_id)}><strong>{prettyStatus(gate.step_id)}</strong><span>Attempt {gate.attempt}</span></button>)}</div>
            {gateStepId && waitingGates.some(gate => gate.step_id === gateStepId) && <div className="workflow-gate-form">
              <label>{t("workspace.gateDecision")}<select value={gateDecision} onChange={e => setGateDecision(e.target.value as typeof gateDecision)}><option value="ACCEPT">{t("workspace.gateAccept")}</option><option value="OVERRIDE">{t("workspace.gateOverride")}</option><option value="REQUEST_MORE_EVIDENCE">{t("workspace.gateMoreEvidence")}</option><option value="REJECT_AND_RETRY">{t("workspace.gateRetry")}</option></select></label>
              <label>{t("workspace.gateReason")}<textarea rows={3} value={gateReason} onChange={e => setGateReason(e.target.value)} required /></label>
              {gateDecision === "REJECT_AND_RETRY" && <label className="workflow-gate-checkbox"><input type="checkbox" checked={gateInputsChanged} onChange={e => setGateInputsChanged(e.target.checked)} />{t("workspace.gateInputsChanged")}</label>}
              <button type="button" className="primary" disabled={busy || !gateReason.trim()} onClick={() => void resolveGate()}>{busy ? t("workspace.loading") : t("workspace.gateSubmit")}</button>
            </div>}
          </div>}
          {(preflightResult || capacityPreflight || resourceStageReadiness.length > 0) && <div className="preflight-panel">
            <div className="panel-head"><div><div className="section-kicker">{t("workspace.preflightTitle")}</div><h4>{preflightResult?.resource_plan_status ?? preflightResult?.status ?? (resourceStageReadiness.some(stage => stage.status === "BLOCKED") ? "BLOCKED" : "READY")}</h4></div><span className={`badge ${preflightResult?.status === "BLOCKED" || resourceStageReadiness.some(stage => stage.status === "BLOCKED") ? "danger" : "neutral"}`}>{preflightResult?.status === "BLOCKED" || resourceStageReadiness.some(stage => stage.status === "BLOCKED") ? t("workspace.preflightBlocked") : t("workspace.preflightReady")}</span></div>
            {capacityPreflight && <div className="capacity-preflight">
              <div className="capacity-preflight-heading"><strong>{t("workspace.capacityPreflight")}</strong><span className={`badge ${capacityPreflight.status === "BLOCKED" ? "danger" : capacityPreflight.status === "READY" ? "success" : "neutral"}`}>{prettyStatus(capacityPreflight.status)}</span></div>
              <div className="capacity-preflight-summary"><span>Input: <strong>{formatBytes(capacityPreflight.input_size_bytes)}</strong></span><span>{t("workspace.capacityEstimate")}: <strong>{formatBytes(capacityPreflight.estimated_required_bytes)}</strong></span></div>
              {capacityPreflight.status === "NOT_CONFIGURED" && <p className="muted">{t("workspace.capacityNotConfigured")}</p>}
              {(capacityPreflight.roots ?? []).map((root: any) => <div className="capacity-root-row" key={root.label}><strong>{prettyStatus(root.label)}</strong><span>{t("workspace.availableStorage")}: {formatBytes(root.free_bytes)} / {t("workspace.totalStorage")}: {formatBytes(root.total_bytes)}</span><small>Estimated for this step: {formatBytes(root.estimated_required_bytes)}</small>{root.error_message && <small className="preflight-stage-issue">{root.error_message}</small>}</div>)}
              {(capacityPreflight.issues ?? []).map((issue: any, index: number) => <p className="preflight-stage-issue" key={`${issue.code ?? "capacity"}-${index}`}>{issue.code}: {issue.message}</p>)}
              <p className="capacity-reservation-note">{t("workspace.capacityReservationNotProvided")}</p>
            </div>}
            {preflightIssues.length ? <div className="preflight-issues"><strong>{t("workspace.preflightIssues")}</strong>{preflightIssues.map((issue: any, index: number) => <div className="preflight-issue" key={`${issue.capability ?? "resource"}-${issue.code ?? index}`}><b>{issue.capability ?? "Resource"}{issue.required ? " · required" : ""}</b><span>{issue.message ?? issue.code ?? "Resource readiness issue"}</span>{issue.code && <small>{issue.code}</small>}</div>)}</div> : <p className="muted">{t("workspace.preflightNoIssues")}</p>}
            {resourceStageReadiness.length > 0 && <details className="preflight-details"><summary>{t("workspace.preflightDetails")}</summary>{resourceStageReadiness.map(stage => <div className="preflight-stage" key={stage.step_id}><strong>{prettyStatus(stage.step_id)}</strong><span className={`badge ${stage.status === "BLOCKED" ? "danger" : "neutral"}`}>{prettyStatus(stage.status)}</span>{stage.selected.map((resource: any, index: number) => <small key={`${resource.resource_id ?? resource.provider ?? "resource"}-${index}`}>{resource.capability}: {resource.name ?? resource.provider} · {resource.version ?? "unversioned"}</small>)}{stage.issues.map((issue: any, index: number) => <small className="preflight-stage-issue" key={`${issue.code ?? "issue"}-${index}`}>{issue.capability}: {issue.message ?? issue.code}</small>)}</div>)}</details>}
          </div>}
          {annotationProgress && <div className="run-meta"><span>Annotation checkpoints {annotationProgress.completed}/{annotationProgress.total} completed</span><span>{t("workspace.checkpointPersisted")}</span></div>}
          {analysis?.started_at && <div className="run-meta"><span>Started {formatDate(analysis.started_at)}</span><span>Last state update {formatDate(analysis.completed_at ?? analysis.started_at)}</span></div>}
          {analysis?.next_step && ["REQUIRES_REVIEW", "BLOCKED", "FAILED", "RESOURCE_FAILURE"].includes(String(analysis?.status)) && (
            <div className="ready-callout">
              <strong>Next required action</strong>
              <p>The backend workflow reports <strong>{prettyStatus(String(analysis.status))}</strong> at <strong>{prettyStatus(String(analysis.next_step))}</strong>. Follow the stated next action; scientific prerequisites are never bypassed automatically.</p>
              {nextActionHref(String(analysis.next_step)) && (
                <Link className="secondary link-button" href={nextActionHref(String(analysis.next_step)) as string}>
                  Open next step
                </Link>
              )}
            </div>
          )}
        </section>
      </section>

      <section id="artifacts" className="panel artifacts-panel">
        <div className="panel-head"><div><div className="section-kicker">{t("workspace.files")}</div><h3>{caseArtifacts.length} {t("workspace.files")}</h3><p className="muted">{t("workspace.filesLead")}</p></div><button type="button" className="secondary" onClick={() => void refreshCaseArtifacts()}>{t("workspace.refreshFiles")}</button></div>
        {!caseArtifacts.length ? <div className="empty small"><strong>{t("workspace.noFiles")}</strong></div> : <div className="artifacts-list">{caseArtifacts.map(artifact => <article className="artifact-row" key={artifact.artifact_id}>
          <div className="artifact-main"><strong>{artifact.filename}</strong><span>{prettyStatus(artifact.artifact_type)} · {formatBytes(artifact.size_bytes)} · {artifact.genome_build ?? "—"}</span><small>{t("workspace.validationStatus")}: {prettyStatus(artifact.validation_status ?? "UNKNOWN")} · {t("workspace.createdAt")}: {formatDate(artifact.created_at)}</small><details><summary>{t("workspace.sha256")}</summary><code>{artifact.sha256}</code>{artifact.metadata && <pre>{JSON.stringify(artifact.metadata, null, 2)}</pre>}</details></div>
          <div className="artifact-actions"><code>{artifact.artifact_id.slice(0, 12)}…</code><button type="button" className="secondary small" onClick={() => void downloadAuthenticated(`/artifacts/${artifact.artifact_id}/download`, artifact.filename)}>{t("workspace.downloadArtifact")}</button></div>
        </article>)}</div>}
      </section>

      <section id="variants" className="panel variants-panel">
        <div className="panel-head"><div><div className="section-kicker">{t("workspace.interpretationSection")}</div><h3>{t("workspace.analyzedVariants")}</h3></div><span className="badge neutral">{variants.length} {t("workspace.variantsCount")}</span></div>
        {variants.length === 0 ? <div className="empty"><strong>{t("workspace.waitingAnalysis")}</strong><p>{t("workspace.variantsWillPopulate")}</p></div> : <div className="table-wrap"><table><thead><tr><th>{t("workflow.variantFile")}</th><th>{t("workspace.position")}</th><th>{t("workspace.refAlt")}</th><th>{t("workspace.build")}</th><th>{t("workspace.review")}</th></tr></thead><tbody>{variants.map((v) => <tr key={v.variant_id} onClick={() => setSelectedVariantId(v.variant_id)} className={selectedVariantId === v.variant_id ? "selected" : ""}><td><code>{v.variant_id.slice(0, 12)}…</code></td><td>{v.chromosome}:{v.position.toLocaleString()}</td><td><code>{v.reference} → {v.alternate}</code></td><td>{v.genome_build}</td><td>{selectedVariantId === v.variant_id ? <span className="badge active">{t("workspace.selected")}</span> : <span className="badge neutral">{t("workspace.open")}</span>}</td></tr>)}</tbody></table></div>}
      </section>

      <section id="variant-export" className="panel complete-report-panel">
        <div className="panel-head"><div><div className="section-kicker">{t("workspace.completeReport")}</div><h3>{t("workspace.allAnalyzedVariants")}</h3></div><span className="badge neutral">{completeVariants.length} {t("workspace.rowsCount")}</span></div>
        <div className="report-toolbar"><p>{t("workspace.completeReportLead")}</p><div className="actions-row"><button className="secondary" onClick={() => analysisId && downloadAuthenticated(`/analyses/${analysisId}/complete-variant-report.csv`, `siraloom-complete-variant-report-${analysisId}.csv`)} disabled={!analysisId}>{t("workspace.downloadCsv")}</button><button className="secondary" onClick={() => analysisId && downloadAuthenticated(`/analyses/${analysisId}/complete-variant-report.json`, `siraloom-complete-variant-report-${analysisId}.json`)} disabled={!analysisId}>{t("workspace.downloadJson")}</button></div></div>
        {completeVariants.length === 0 ? <div className="empty small"><strong>{t("workspace.noCompleteDataset")}</strong><p>{t("workspace.completeDatasetPending")}</p></div> : <div className="table-wrap"><table><thead><tr>{completeVariantColumns.slice(0, 12).map((column) => <th key={column}>{column.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{completeVariants.slice(0, 100).map((row, index) => <tr key={String(row.variant_id ?? index)} onClick={() => typeof row.variant_id === "string" && setSelectedVariantId(row.variant_id)}>{completeVariantColumns.slice(0, 12).map((column) => <td key={column}><code>{String(row[column] ?? "—")}</code></td>)}</tr>)}</tbody></table>{completeVariants.length > 100 && <p className="table-note">{t("workspace.first100Note")}</p>}</div>}
      </section>

      <section className="detail-grid">
        <section id="evidence" className="panel evidence-panel">
          <div className="panel-head"><div><div className="section-kicker">{t("workspace.evidenceSection")}</div><h3>{t("workspace.variantEvidence")}</h3></div></div>
          {!variantDetail ? <div className="empty"><strong>{t("workspace.noVariantSelected")}</strong><p>{t("workspace.selectVariantAfterAnalysis")}</p></div> : <div className="evidence-stack">
            <div className="identity-card"><div><span>{t("workspace.canonical")}</span><strong>{String(variantDetail.variant.canonical_key ?? "—")}</strong></div><div><span>{t("workspace.normalization")}</span><strong>{String(variantDetail.variant.normalization_status ?? "—")}</strong></div></div>
            <div className="evidence-list">
              {variantDetail.population.map((item, index) => <div className="evidence-item" key={`pop-${index}`}><div><strong>Population · {String(item.label ?? item.population ?? t("workspace.unknown"))}</strong><span>{String(item.availability ?? "—")}</span></div><code>{item.af == null ? t("workspace.noData") : String(item.af)}</code></div>)}
              {variantDetail.evidence.map((item, index) => { const key = `ev-${index}`; const open = expandedEvidence === key; return <div className="evidence-item evidence-click" key={key} onClick={() => setExpandedEvidence(open ? null : key)}><div><strong>{String(item.type ?? t("workspace.evidence"))}</strong><span>{String(item.source ?? t("workspace.unknownSource"))} · {String(item.source_version ?? t("workspace.unversioned"))}</span></div><span>{open ? "−" : "+"}</span>{open && <pre className="evidence-json">{JSON.stringify(item.payload ?? item.statement ?? {}, null, 2)}</pre>}</div>; })}
              {variantDetail.evidence.length === 0 && variantDetail.population.length === 0 && <div className="empty small"><strong>{t("workspace.noEvidence")}</strong></div>}
            </div>
          </div>}
        </section>

        <section id="review" className="panel review-panel">
          <div className="panel-head"><div><div className="section-kicker">{t("workspace.reviewSection")}</div><h3>{t("workspace.humanDecisionWorkspace")}</h3></div>{review?.review_status && <span className={`badge ${statusTone(review.review_status)}`}>{prettyStatus(review.review_status)}</span>}</div>
          {!review ? <div className="empty"><strong>{t("workspace.reviewPending")}</strong><p>{t("workspace.automatedOutputProposed")}</p></div> : <>
            <div className="classification-banner"><span>{t("workspace.proposedCurrent")}</span><strong>{String(review.classification?.result ?? t("workspace.noClassification"))}</strong><small>Review revision {String(review.classification?.review_version ?? 0)}</small></div>
            {!review.classification && review.review_status === "NOT_STARTED" && (analysis?.steps as Step[] | undefined)?.some(step => step.step_id === "acmg_assessment" && step.status === "REQUIRES_REVIEW" && ["NO_AUTOMATABLE_CLINGEN_CONTEXT", "ACMG_VARIANTS_REQUIRE_REVIEW", "CLASSIFICATION_COMBINATION_REQUIRES_REVIEW"].includes(String(step.error_code))) && <div className="manual-classification-form">
              <div className="section-kicker">{t("workspace.manualClassificationTitle")}</div>
              <p>{t("workspace.manualClassificationHelp")}</p>
              <label>{t("workspace.manualClassificationResult")}
                <select value={manualClassificationResult} onChange={event => setManualClassificationResult(event.target.value)}>
                  <option value="PATHOGENIC">{t("workspace.classPathogenic")}</option>
                  <option value="LIKELY_PATHOGENIC">{t("workspace.classLikelyPathogenic")}</option>
                  <option value="VUS">{t("workspace.classVus")}</option>
                  <option value="LIKELY_BENIGN">{t("workspace.classLikelyBenign")}</option>
                  <option value="BENIGN">{t("workspace.classBenign")}</option>
                </select>
              </label>
              <label>{t("workspace.manualClassificationEvidence")}
                <select value={manualClassificationEvidenceId} onChange={event => setManualClassificationEvidenceId(event.target.value)}>
                  <option value="">{t("workspace.selectEvidence")}</option>
                  {manualClassificationEvidence.map(item => <option key={String(item.id)} value={String(item.id)}>{String(item.type ?? "Evidence")} — {String(item.statement ?? item.source ?? item.id)}</option>)}
                </select>
              </label>
              <label>{t("workspace.manualClassificationRationale")}
                <textarea value={manualClassificationReason} onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setManualClassificationReason(event.target.value)} rows={3} />
              </label>
              <button className="primary" type="button" onClick={() => void proposeManualClassification()} disabled={busy || !manualClassificationEvidence.length}>{t("workspace.manualClassificationSubmit")}</button>
            </div>}
            <div className="actions-row"><button className="secondary" onClick={startReview} disabled={!review.classification || review.review_status === "APPROVED"}>{t("workspace.startReview")}</button></div>
            <div className="criteria-grid">{review.criteria.map((item) => <div className="criterion-card" key={item.criterion}><div className="criterion-head"><strong>{item.criterion}</strong><span className={`badge ${statusTone(item.state)}`}>{prettyStatus(item.state)}</span></div><p>{String((item.automated as any)?.reason ?? t("workspace.noAutomatedRationale"))}</p><label>{t("review.selectStrength")}<select value={criterionStrengths[item.criterion] ?? ""} onChange={(e) => setCriterionStrengths((current) => ({ ...current, [item.criterion]: e.target.value }))}><option value="">{t("review.selectStrength")}</option>{item.criterion === "BA1" ? <option>STANDALONE</option> : <><option>SUPPORTING</option><option>MODERATE</option><option>STRONG</option><option>VERY_STRONG</option></>}</select></label><div className="mini-actions"><button onClick={() => reviewCriterion(item.criterion, "ACCEPT")} className="ghost">{t("workspace.accept")}</button><button onClick={() => reviewCriterion(item.criterion, "REJECT")} className="ghost danger-text">{t("workspace.reject")}</button></div></div>)}</div>
            <label>{t("workspace.criterionReviewReason")}<input value={criterionReason} onChange={(e: ChangeEvent<HTMLInputElement>) => setCriterionReason(e.target.value)} placeholder="Why is this criterion accepted/rejected?" /></label>
            <label>{t("workspace.finalApprovalReason")}<textarea value={reviewReason} onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setReviewReason(e.target.value)} placeholder="Explain the basis for the final reviewer decision." rows={3} /></label>
            <div className="actions-row"><button className="primary" onClick={approve} disabled={review.review_status !== "IN_REVIEW"}>{t("workspace.approveClassification")}</button><button className="secondary" onClick={requestMoreEvidence} disabled={review.review_status !== "IN_REVIEW"}>{t("workspace.requestMoreEvidence")}</button><button className="secondary" onClick={generateReport} disabled={!analysisId || review.review_status !== "APPROVED"}>{t("workspace.generateReport")}</button></div>
            <div className="history"><div className="section-kicker">{t("workspace.decisionHistory")}</div>{review.history.length === 0 ? <p>{t("workspace.noReviewActions")}</p> : review.history.map((item, index) => <div className="history-row" key={`${item.action_type}-${index}`}><span>{formatDate(item.created_at)}</span><strong>{item.action_type}</strong><p>{item.reason}</p></div>)}</div>
          </>}
        </section>
      </section>

      <section className="bottom-grid">
        <section id="report" className="panel report-panel"><div className="panel-head"><div><div className="section-kicker">{t("workspace.reportSection")}</div><h3>{t("workspace.finalReport")}</h3></div>{report?.status && <span className={`badge ${statusTone(report.status)}`}>{prettyStatus(report.status)}</span>}</div>{!report ? <div className="empty"><strong>{t("workspace.noReportGenerated")}</strong><p>{t("workspace.reportPending")}</p></div> : <div className="report-preview"><div className="report-title">SIRALOOM Variant Report v{String(report.version)}</div><div className="report-summary">{String(report.content?.summary?.overall_result ?? t("workspace.reportArtifact"))}</div>{report.status !== "FINAL" && <label>{t("workspace.reportSignoutReason")}<textarea value={reportSignoutReason} onChange={(event) => setReportSignoutReason(event.target.value)} rows={3} disabled={!canFinalizeClinicalReports(sessionRole)} placeholder={t("workspace.reportSignoutReasonRequired")} /></label>}{!sessionRoleResolved ? <p className="quiet">{t("workspace.reportSignoutRoleChecking")}</p> : report.status !== "FINAL" && !canFinalizeClinicalReports(sessionRole) ? <p className="quiet">{t("workspace.reportSignoutRoleHelp")}</p> : null}<div className="actions-row"><button className="primary" onClick={finalize} disabled={busy || !sessionRoleResolved || !canSubmitReportSignout(sessionRole, reportSignoutReason) || report.status === "FINAL"}>{t("workspace.finalizeReport")}</button>{report.artifact_id && <button className="secondary" onClick={() => report.artifact_id && downloadAuthenticated(`/artifacts/${report.artifact_id}/download`, `siraloom-report-${report.artifact_id}.pdf`)}>{t("workspace.downloadPdf")}</button>}</div></div>}</section>
        <section id="audit" className="panel audit-panel"><div className="panel-head"><div><div className="section-kicker">{t("workspace.auditSection")}</div><h3>{t("workspace.caseTimeline")}</h3></div><span className="badge neutral">{auditEvents.length} {t("workspace.eventsCount")}</span></div><div className="audit-callout"><strong>{t("workspace.auditReconstructable")}</strong><p>{t("workspace.auditLead")}</p></div><div className="audit-timeline">{auditEvents.length === 0 ? <div className="empty small"><strong>{t("workspace.noAuditEvents")}</strong></div> : auditEvents.slice().reverse().slice(0, 20).map((event) => { const expanded = expandedAuditId === event.event_id; return <div className={`audit-event ${expanded ? "expanded" : ""}`} key={event.event_id} onClick={() => setExpandedAuditId(expanded ? null : event.event_id)}><span>{formatDate(event.occurred_at)}</span><div><strong>{prettyStatus(event.event_type)}</strong><small>{event.actor_type ?? "SYSTEM"} · {event.actor_id ?? "siraloom"}{event.operation ? ` · ${event.operation}` : ""}</small>{event.reason && <p>{event.reason}</p>}{expanded && <pre className="audit-json">{JSON.stringify({ before_state: event.before_state, after_state: event.after_state, input_artifacts: event.input_artifacts, output_artifacts: event.output_artifacts, software: event.software, workflow: event.workflow, resource_versions: event.resource_versions, subject: { type: event.subject_type, id: event.subject_id } }, null, 2)}</pre>}</div><span className="audit-toggle">{expanded ? "−" : "+"}</span></div>; })}</div><button className="secondary full" onClick={exportHistory} disabled={!caseId}>{t("workspace.exportHistory")}</button>{exportId && <><div className="keyline"><span>{t("workspace.export")}</span><code>{exportId}</code></div><div className="keyline"><span>{t("workspace.status")}</span><strong>{exportStatus ? prettyStatus(exportStatus) : t("workspace.queued")}</strong></div>{exportStatus === "SUCCEEDED" && <button className="secondary full" onClick={() => downloadAuthenticated(`/exports/${exportId}/download`, `siraloom-case-history-${exportId}.zip`)}>{t("workspace.downloadHistoryZip")}</button>}</>}</section>
      </section>

      <footer className="footer"><span>SIRALOOM Variant v1</span><span>{t("workspace.footer")}</span></footer>
    </main>
  );
}
