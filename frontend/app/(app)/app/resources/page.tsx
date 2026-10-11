"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { firebaseAuth } from "../../../../lib/firebase";
import { useLanguage } from "../../../../lib/i18n";

const API_BASE_RAW = process.env.NEXT_PUBLIC_SIRALOOM_API_BASE ?? "http://localhost:8000/api/v1";
const API_BASE = API_BASE_RAW.endsWith("/") ? API_BASE_RAW.slice(0, -1) : API_BASE_RAW;
const RESOURCE_TYPES = [
  "REFERENCE_PACKAGE", "ANNOTATION_ENGINE", "ANNOTATION_CACHE", "POPULATION",
  "POPULATION_SECONDARY", "CLINICAL_DATABASE", "PHENOTYPE_ONTOLOGY",
  "COMPUTATIONAL_PREDICTOR", "SPLICING_PREDICTOR", "FUNCTIONAL_EVIDENCE",
  "LITERATURE_PROVIDER", "ACMG_RULE_SPECIFICATION", "GENE_DISEASE",
  "INTERNAL_LAB_EVIDENCE", "DISEASE_ONTOLOGY", "GENE_PANEL", "DOSAGE_SENSITIVITY",
];
const PROFILE_ROWS = [
  { id: "WES_GRCh38_STANDARD", scope: "WES", build: "GRCh38", required: "REFERENCE_PACKAGE · ANNOTATION_ENGINE · POPULATION · ACMG_RULE_SPECIFICATION" },
  { id: "WGS_GRCh38_STANDARD", scope: "WGS", build: "GRCh38", required: "REFERENCE_PACKAGE · ANNOTATION_ENGINE · POPULATION · ACMG_RULE_SPECIFICATION" },
  { id: "WES_GRCh37_STANDARD", scope: "WES", build: "GRCh37", required: "REFERENCE_PACKAGE · ANNOTATION_ENGINE · POPULATION · ACMG_RULE_SPECIFICATION" },
];

type Resource = {
  resource_id: string;
  name: string;
  provider: string;
  resource_type: string;
  version: string;
  genome_build?: string | null;
  access_method: string;
  checksum?: string | null;
  location?: string | null;
  status: string;
  organization_id?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at?: string;
};
type Approval = {
  approval_id: string;
  resource_id: string;
  organization_id: string;
  qualification_id: string;
  status: string;
  version: number;
  requested_at?: string;
};

async function apiFetch(path: string, init: RequestInit = {}) {
  const token = await firebaseAuth?.currentUser?.getIdToken();
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.body && !((init.headers as Record<string, string> | undefined)?.["Content-Type"]) ? { "Content-Type": "application/json" } : {}),
    },
  });
  const text = await response.text();
  let body: any = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!response.ok) throw new Error(body?.detail ? String(body.detail) : `HTTP ${response.status}`);
  return body;
}

function pretty(value?: string | null) {
  return String(value ?? "—").replaceAll("_", " ").toLowerCase().split(" ").map(part => part ? part[0].toUpperCase() + part.slice(1) : part).join(" ");
}

function statusClass(status: string) {
  if (["ACTIVE", "APPROVED", "QUALIFIED"].includes(status)) return "success";
  if (["REJECTED", "INTEGRITY_FAILED", "INVALID", "PREFLIGHT_FAILED"].includes(status)) return "danger";
  if (["CANDIDATE", "PENDING", "DISCOVERED", "READY_TO_STAGE", "STAGING"].includes(status)) return "active";
  return "neutral";
}

const METADATA_TEMPLATE = JSON.stringify({
  source_contract: {
    publisher: "REPLACE_WITH_AUTHORITATIVE_PUBLISHER",
    canonical_source_url: "https://publisher.example.org/resource",
    artifact_url: "https://publisher.example.org/exact-release-file",
    release_identity: "REPLACE_WITH_EXACT_RELEASE",
    access_mode: "PUBLIC",
    license_status: "REVIEW_REQUIRED",
    license_url: null,
    terms_url: null,
    checksum_status: "UNKNOWN",
    authority_evidence_url: "https://publisher.example.org/resource-documentation"
  },
  execution: {
    provider_id: "REPLACE_WITH_PROVIDER_ID",
    provider_version: "REPLACE_WITH_EXACT_VERSION",
    access_method: "LOCAL",
    endpoint: null,
    location: "/absolute/path/on/lab-runtime",
    dataset: "REPLACE_WITH_DATASET_OR_CACHE",
    execution_scope: "SNV_INDEL",
    toolchain: {}
  },
  capabilities: []
}, null, 2);

export default function ResourcesPage() {
  const { t } = useLanguage();
  const [resources, setResources] = useState<Resource[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [typeFilter, setTypeFilter] = useState("ALL");
  const [showRegister, setShowRegister] = useState(false);
  const [qualificationVersion, setQualificationVersion] = useState("siraloom-resource-qualification-v1");
  const [decisionReason, setDecisionReason] = useState("");
  const [metadataText, setMetadataText] = useState(METADATA_TEMPLATE);
  const [qualificationResults, setQualificationResults] = useState<Record<string, any>>({});
  const [form, setForm] = useState({
    name: "", provider: "", resource_type: "REFERENCE_PACKAGE", version: "",
    genome_build: "GRCh38", access_method: "LOCAL", location: "", checksum: "",
    license_text: "", population_definition: "",
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [resourceRows, approvalRows] = await Promise.all([
        apiFetch("/resources?status="),
        apiFetch("/resources/approvals/pending"),
      ]);
      setResources(Array.isArray(resourceRows) ? resourceRows : []);
      setApprovals(Array.isArray(approvalRows) ? approvalRows : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("resources.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  const resourcesById = useMemo(() => new Map(resources.map(r => [r.resource_id, r])), [resources]);
  const visibleResources = useMemo(() => resources.filter(r =>
    (statusFilter === "ALL" || r.status === statusFilter) &&
    (typeFilter === "ALL" || r.resource_type === typeFilter)
  ), [resources, statusFilter, typeFilter]);

  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(""); setError("");
    let metadata: Record<string, unknown>;
    try {
      metadata = JSON.parse(metadataText);
      if (!metadata || Array.isArray(metadata) || typeof metadata !== "object") throw new Error("Metadata must be a JSON object.");
    } catch (e) {
      setError(e instanceof Error ? e.message : t("resources.metadataInvalid"));
      return;
    }
    setBusy("register");
    try {
      await apiFetch("/resources", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          genome_build: form.genome_build || null,
          checksum: form.checksum.trim() || null,
          license_text: form.license_text.trim() || null,
          population_definition: form.population_definition.trim() || null,
          metadata,
          status: "CANDIDATE",
        }),
      });
      setMessage(t("resources.registered"));
      setShowRegister(false);
      setForm({ name: "", provider: "", resource_type: "REFERENCE_PACKAGE", version: "", genome_build: "GRCh38", access_method: "LOCAL", location: "", checksum: "", license_text: "", population_definition: "" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("resources.operationFailed"));
    } finally { setBusy(null); }
  }

  async function runQualification(resource: Resource) {
    setBusy(resource.resource_id); setError(""); setMessage("");
    try {
      const result = await apiFetch(`/resources/${resource.resource_id}/qualify`, {
        method: "POST",
        body: JSON.stringify({ qualification_version: qualificationVersion.trim() }),
      });
      setQualificationResults(current => ({ ...current, [resource.resource_id]: result }));
      setMessage(result.passed ? t("resources.qualificationResult") : t("resources.qualificationBlocked"));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("resources.operationFailed"));
      await load();
    } finally { setBusy(null); }
  }

  async function requestApproval(resource: Resource) {
    setBusy(resource.resource_id); setError(""); setMessage("");
    try {
      await apiFetch(`/resources/${resource.resource_id}/approval-request`, {
        method: "POST",
        body: JSON.stringify({ qualification_version: qualificationVersion.trim() }),
      });
      setMessage(t("resources.approvalRequested"));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("resources.operationFailed"));
    } finally { setBusy(null); }
  }

  async function decideApproval(approval: Approval, decision: "APPROVED" | "REJECTED" | "DEFERRED") {
    if (!decisionReason.trim()) { setError(t("resources.reasonRequired")); return; }
    setBusy(approval.approval_id); setError(""); setMessage("");
    try {
      await apiFetch(`/resources/approvals/${approval.approval_id}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, expected_version: approval.version, reason: decisionReason.trim() }),
      });
      setDecisionReason("");
      setMessage(t("resources.approvalDecided"));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("resources.operationFailed"));
      await load();
    } finally { setBusy(null); }
  }

  async function activate(resource: Resource) {
    setBusy(resource.resource_id); setError(""); setMessage("");
    try {
      await apiFetch(`/resources/${resource.resource_id}/activate`, {
        method: "POST",
        body: JSON.stringify({ qualification_version: qualificationVersion.trim() }),
      });
      setMessage(t("resources.activated"));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("resources.operationFailed"));
    } finally { setBusy(null); }
  }

  return (
    <main className="resources-page">
      <header className="page-heading resources-heading">
        <div>
          <p className="eyebrow">{t("resources.eyebrow")}</p>
          <h1>{t("resources.title")}</h1>
          <p className="lead">{t("resources.lead")}</p>
        </div>
        <div className="resources-heading-actions">
          <button type="button" className="secondary" onClick={() => void load()} disabled={loading}>{loading ? t("cases.refreshing") : t("resources.refresh")}</button>
          <button type="button" className="primary" onClick={() => setShowRegister(value => !value)}>{showRegister ? t("cases.back") : t("resources.register")}</button>
        </div>
      </header>

      {message && <div className="notice resources-status-message" role="status">{message}</div>}
      {error && <div className="notice error-notice" role="alert">{error}</div>}

      <section className="panel resources-governance-note">
        <strong>{t("resources.lifecycleNote")}</strong>
        <p>{t("resources.stagingGap")}</p>
      </section>

      {showRegister && <section className="panel resources-register-panel">
        <div className="panel-head">
          <div><p className="eyebrow">{t("resources.candidateOnly")}</p><h2>{t("resources.register")}</h2></div>
        </div>
        <p className="muted">{t("resources.registerHelp")}</p>
        <form onSubmit={register} className="resources-form">
          <div className="resources-form-grid">
            <label>{t("resources.name")}<input required value={form.name} onChange={e => setForm(s => ({ ...s, name: e.target.value }))} /></label>
            <label>{t("resources.provider")}<input required value={form.provider} onChange={e => setForm(s => ({ ...s, provider: e.target.value }))} /></label>
            <label>{t("resources.type")}<select required value={form.resource_type} onChange={e => setForm(s => ({ ...s, resource_type: e.target.value }))}>{RESOURCE_TYPES.map(type => <option key={type} value={type}>{type}</option>)}</select></label>
            <label>{t("resources.version")}<input required value={form.version} onChange={e => setForm(s => ({ ...s, version: e.target.value }))} /></label>
            <label>{t("resources.build")}<select value={form.genome_build} onChange={e => setForm(s => ({ ...s, genome_build: e.target.value }))}><option value="GRCh38">GRCh38</option><option value="GRCh37">GRCh37</option><option value="">Not build-specific</option></select></label>
            <label>{t("resources.accessMethod")}<select value={form.access_method} onChange={e => setForm(s => ({ ...s, access_method: e.target.value }))}>{["LOCAL","FILE","LOCAL_ONLY","HTTPS","HTTP_API","REST","GRAPHQL","TABIX","VCF","SQL","S3","GCS","AUTHENTICATED"].map(v => <option key={v} value={v}>{v}</option>)}</select></label>
            <label className="resources-field-wide">{t("resources.location")}<input required value={form.location} onChange={e => setForm(s => ({ ...s, location: e.target.value }))} placeholder="/lab/resources/reference.fa or approved endpoint" /></label>
            <label>{t("resources.checksum")}<input value={form.checksum} onChange={e => setForm(s => ({ ...s, checksum: e.target.value }))} placeholder="64 hexadecimal characters" /></label>
            <label>{t("resources.license")}<input value={form.license_text} onChange={e => setForm(s => ({ ...s, license_text: e.target.value }))} /></label>
            <label className="resources-field-wide">{t("resources.populationDefinition")}<input value={form.population_definition} onChange={e => setForm(s => ({ ...s, population_definition: e.target.value }))} /></label>
          </div>
          <label className="resources-metadata-label">{t("resources.sourceExecutionMetadata")}<span className="muted">{t("resources.sourceExecutionHelp")}</span><textarea rows={16} spellCheck={false} value={metadataText} onChange={e => setMetadataText(e.target.value)} /></label>
          <div className="actions-row"><button className="primary" type="submit" disabled={busy === "register"}>{busy === "register" ? t("cases.registering") : t("resources.registerCandidate")}</button><button className="secondary" type="button" onClick={() => setMetadataText(METADATA_TEMPLATE)}>Reset metadata template</button></div>
        </form>
      </section>}

      <section className="panel resources-catalog-panel">
        <div className="panel-head resources-catalog-header">
          <div><p className="eyebrow">{t("resources.catalog")}</p><h2>{visibleResources.length} / {resources.length} resources</h2></div>
          <div className="resources-filters">
            <label>{t("resources.status")}<select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}><option value="ALL">All statuses</option>{["CANDIDATE","DISCOVERED","READY_TO_STAGE","STAGING","STAGED","QUALIFIED","ACTIVE","REJECTED","INTEGRITY_FAILED","PREFLIGHT_FAILED","INVALID","REMOVED"].map(s => <option key={s} value={s}>{pretty(s)}</option>)}</select></label>
            <label>{t("resources.type")}<select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}><option value="ALL">All types</option>{RESOURCE_TYPES.map(s => <option key={s} value={s}>{s}</option>)}</select></label>
          </div>
        </div>
        {loading ? <p className="muted">{t("cases.refreshing")}</p> : !visibleResources.length ? <div className="empty"><strong>{t("resources.noResources")}</strong></div> :
          <div className="resources-table-wrap"><table className="resources-table"><thead><tr><th>{t("resources.name")}</th><th>{t("resources.type")}</th><th>{t("resources.version")}</th><th>{t("resources.build")}</th><th>{t("resources.status")}</th><th>{t("resources.actions")}</th></tr></thead>
            <tbody>{visibleResources.map(resource => {
              const result = qualificationResults[resource.resource_id];
              const isBusy = busy === resource.resource_id;
              return <tr key={resource.resource_id}>
                <td><strong>{resource.name}</strong><small>{resource.provider} · {resource.access_method}</small><code>{resource.resource_id}</code>{resource.location && <small className="resources-location">{resource.location}</small>}</td>
                <td>{resource.resource_type}</td><td>{resource.version}<small>{resource.checksum ? `SHA-256 ${resource.checksum.slice(0, 12)}…` : "No checksum recorded"}</small></td><td>{resource.genome_build ?? "—"}</td>
                <td><span className={`badge ${statusClass(resource.status)}`}>{pretty(resource.status)}</span></td>
                <td><div className="resources-row-actions">
                  <button className="secondary small" type="button" disabled={isBusy} onClick={() => void runQualification(resource)}>{isBusy ? "Working…" : t("resources.qualify")}</button>
                  {["QUALIFIED","ACTIVE"].includes(resource.status) && <button className="secondary small" type="button" disabled={isBusy} onClick={() => void requestApproval(resource)}>{t("resources.requestApproval")}</button>}
                  {resource.status !== "ACTIVE" && ["QUALIFIED","APPROVED"].includes(resource.status) && <button className="secondary small" type="button" disabled={isBusy} onClick={() => void activate(resource)}>{t("resources.activate")}</button>}
                </div>
                {result && <details className="resources-qualification-result"><summary>{t("resources.qualificationResult")}: {result.passed ? "PASS" : "BLOCKED"}</summary><pre>{JSON.stringify({ outcome: result.outcome, activation_blockers: result.activation_blockers, checks: result.checks }, null, 2)}</pre></details>}
                </td>
              </tr>;
            })}</tbody></table></div>}
      </section>

      <section className="panel resources-approvals-panel">
        <div className="panel-head"><div><p className="eyebrow">{t("resources.pendingApprovals")}</p><h2>{approvals.length} pending</h2></div></div>
        <label className="resources-reason-field">{t("resources.reason")}<input value={decisionReason} onChange={e => setDecisionReason(e.target.value)} placeholder="Document the lab decision and rationale" /></label>
        {!approvals.length ? <div className="empty"><strong>{t("resources.noApprovals")}</strong></div> :
          <div className="resources-approval-list">{approvals.map(approval => {
            const resource = resourcesById.get(approval.resource_id);
            return <article className="resources-approval-row" key={approval.approval_id}>
              <div><strong>{resource?.name ?? approval.resource_id}</strong><p>{resource ? `${resource.provider} · ${resource.version} · ${resource.resource_type}` : approval.qualification_id}</p><small>Qualification {approval.qualification_id} · version {approval.version}</small></div>
              <div className="resources-row-actions">
                <button className="primary small" disabled={busy === approval.approval_id} onClick={() => void decideApproval(approval, "APPROVED")}>{t("resources.approve")}</button>
                <button className="secondary small" disabled={busy === approval.approval_id} onClick={() => void decideApproval(approval, "DEFERRED")}>{t("resources.defer")}</button>
                <button className="danger-button small" disabled={busy === approval.approval_id} onClick={() => void decideApproval(approval, "REJECTED")}>{t("resources.reject")}</button>
              </div>
            </article>;
          })}</div>}
      </section>

      <section className="panel resources-profiles-panel">
        <div className="panel-head"><div><p className="eyebrow">{t("resources.profiles")}</p><h2>{PROFILE_ROWS.length} supported profiles</h2></div></div>
        <p className="muted">{t("resources.profileHelp")}</p>
        <div className="resources-table-wrap"><table className="resources-table"><thead><tr><th>Profile ID</th><th>Assay</th><th>{t("resources.build")}</th><th>{t("resources.requiredCapabilities")}</th></tr></thead><tbody>{PROFILE_ROWS.map(profile => <tr key={profile.id}><td><strong>{profile.id}</strong></td><td>{profile.scope}</td><td>{profile.build}</td><td>{profile.required.split(" · ").map(capability => <span className="resource-capability" key={capability}>{capability}</span>)}</td></tr>)}</tbody></table></div>
      </section>
    </main>
  );
}
