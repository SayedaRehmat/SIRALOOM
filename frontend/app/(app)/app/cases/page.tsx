"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { firebaseAuth } from "../../../../lib/firebase";

type CaseSummary = {
  case_id: string;
  case_identifier: string;
  status: string;
  language: string;
  clinical_context: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
  analyses?: Array<{
    analysis_id: string;
    status: string;
    analysis_type?: string;
    workflow_id?: string;
    workflow_version?: string;
    reference_build?: string;
    created_at?: string;
  }>;
  specimens: Array<{
    specimen_id: string;
    specimen_identifier: string;
    specimen_type?: string | null;
  }>;
};

type Artifact = {
  artifact_id: string;
  filename: string;
  artifact_type: string;
  size_bytes: number;
  sha256: string;
  genome_build?: string | null;
  specimen_id?: string | null;
  paired_artifact_id?: string | null;
  validation_status: string;
  metadata?: Record<string, unknown>;
};

const API_BASE = (
  process.env.NEXT_PUBLIC_SIRALOOM_API_BASE ??
  "http://localhost:8000/api/v1"
).replace(/\/$/, "");

const steps = ["Case", "Specimen", "Variant file", "Index", "Review"];

async function apiFetch(path: string, init?: RequestInit) {
  const user = firebaseAuth?.currentUser;
  const token = user ? await user.getIdToken() : null;

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });

  const text = await response.text();

  let body: any = null;

  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }

  if (!response.ok) {
    throw new Error(
      typeof body === "object" && body?.detail
        ? String(body.detail)
        : `Request failed (${response.status})`,
    );
  }

  return body;
}

function pretty(value: string) {
  return value
    .toLowerCase()
    .replaceAll("_", " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;

  if (bytes < 1024 ** 2) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }

  if (bytes < 1024 ** 3) {
    return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  }

  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export default function Cases() {
  const [step, setStep] = useState(0);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [loadingCases, setLoadingCases] = useState(false);
  const [caseIdentifier, setCaseIdentifier] = useState("");
  const [indication, setIndication] = useState("");
  const [language, setLanguage] = useState("en");
  const [caseId, setCaseId] = useState("");
  const [caseData, setCaseData] = useState<CaseSummary | null>(null);
  const [specimenIdentifier, setSpecimenIdentifier] = useState("");
  const [specimenType, setSpecimenType] = useState("Blood");
  const [specimenId, setSpecimenId] = useState("");
  const [build, setBuild] = useState("GRCh38");
  const [variantFile, setVariantFile] = useState<File | null>(null);
  const [primaryArtifact, setPrimaryArtifact] = useState<Artifact | null>(null);
  const [indexFile, setIndexFile] = useState<File | null>(null);
  const [indexArtifact, setIndexArtifact] = useState<Artifact | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const validPrimary = primaryArtifact?.validation_status === "VALID";

  const canContinue = useMemo(() => {
    if (step === 0) return Boolean(caseId);
    if (step === 1) return Boolean(specimenId);
    if (step === 2) return Boolean(primaryArtifact);

    return true;
  }, [step, caseId, specimenId, primaryArtifact]);

  const loadCases = async () => {
    setLoadingCases(true);
    try {
      const rows = await apiFetch("/cases");
      setCases(Array.isArray(rows) ? rows : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load existing cases.");
    } finally {
      setLoadingCases(false);
    }
  };

  const loadExistingCase = async (id: string) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const [data, files] = await Promise.all([
        apiFetch(`/cases/${id}`),
        apiFetch(`/cases/${id}/artifacts`),
      ]);
      const specimens = Array.isArray(data.specimens) ? data.specimens : [];
      const artifactRows = Array.isArray(files) ? files : [];
      const primary = artifactRows.find(
        (a: Artifact) =>
          a.artifact_type === "VCF" &&
          a.validation_status === "VALID",
      ) ?? null;
      const index = artifactRows.find(
        (a: Artifact) =>
          ["VCF_INDEX_TBI", "VCF_INDEX_CSI"].includes(a.artifact_type),
      ) ?? null;
      const latestAnalysis = Array.isArray(data.analyses) && data.analyses.length
        ? data.analyses[0]
        : null;

      setCaseId(data.case_id);
      setCaseIdentifier(data.case_identifier ?? "");
      setIndication(String(data.clinical_context?.indication ?? ""));
      setLanguage(data.language ?? "en");
      setCaseData(data);
      setArtifacts(artifactRows);
      setSpecimenId(specimens[0]?.specimen_id ?? "");
      setPrimaryArtifact(primary);
      setIndexArtifact(index);
      setBuild(primary?.genome_build ?? "GRCh38");
      setVariantFile(null);
      setIndexFile(null);

      window.localStorage.setItem("siraloom.case_id", data.case_id);
      window.localStorage.setItem("siraloom.case_identifier", data.case_identifier);
      if (latestAnalysis?.analysis_id) {
        window.localStorage.setItem("siraloom.analysis_id", latestAnalysis.analysis_id);
      }

      if (!specimens.length) setStep(1);
      else if (!primary) setStep(2);
      else setStep(4);

      setMessage(`Loaded case ${data.case_identifier}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load case.");
    } finally {
      setBusy(false);
    }
  };

  const refreshCase = async (id = caseId) =>
    if (!id) return;

    const [data, files] = await Promise.all([
      apiFetch(`/cases/${id}`),
      apiFetch(`/cases/${id}/artifacts`),
    ]);

    setCaseData(data);
    setArtifacts(files);

    const specimen = data.specimens?.[0];

    if (specimen && !specimenId) {
      setSpecimenId(specimen.specimen_id);
    }
  };

  useEffect(() => {
    loadCases();
  }, []);

  useEffect(() => {
    if (caseId) {
      refreshCase().catch((e) =>
        setError(e instanceof Error ? e.message : "Unable to load case."),
      );
    }
  }, [caseId]);

  const createCase = async (event: FormEvent) => {
    event.preventDefault();

    setBusy(true);
    setError("");
    setMessage("");

    try {
      const result = await apiFetch("/cases", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          case_identifier: caseIdentifier.trim(),
          language,
          clinical_context: {
            indication: indication.trim(),
          },
        }),
      });

      setCaseId(result.case_id);
      window.localStorage.setItem("siraloom.case_id", result.case_id);
      window.localStorage.setItem("siraloom.case_identifier", result.case_identifier);
      window.localStorage.removeItem("siraloom.analysis_id");

      setMessage(
        result.created
          ? "Case created securely in your organization."
          : "Existing case loaded.",
      );

      await loadCases();
      setStep(1);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Case creation failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const createSpecimen = async () => {
    if (!caseId || !specimenIdentifier.trim()) {
      setError("Enter a specimen identifier before continuing.");
      return;
    }

    setBusy(true);
    setError("");

    try {
      const result = await apiFetch(`/cases/${caseId}/specimens`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          specimen_identifier: specimenIdentifier.trim(),
          specimen_type: specimenType,
        }),
      });

      const createdSpecimenId = result.specimen_id;

      setSpecimenId(createdSpecimenId);
      setSpecimenIdentifier("");
      setMessage("Specimen registered.");

      await refreshCase();

      setStep(2);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Specimen registration failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const upload = async (
    selected: File,
    isIndex = false,
    selectedSpecimenId = specimenId,
  ) => {
    if (!caseId) return;

    if (!isIndex && !selectedSpecimenId) {
      setError("Select or register a specimen before uploading the VCF.");
      return;
    }

    setBusy(true);
    setError("");

    setMessage(
      isIndex
        ? "Uploading index and validating its pairing…"
        : "Uploading and validating the variant file…",
    );

    try {
      const form = new FormData();

      form.append("file", selected, selected.name);

      if (isIndex) {
        form.append(
          "paired_artifact_id",
          primaryArtifact!.artifact_id,
        );
      } else {
        form.append("specimen_id", selectedSpecimenId);
        form.append("genome_build", build);
      }

      const result = await apiFetch(`/cases/${caseId}/artifacts`, {
        method: "POST",
        body: form,
      });

      const artifact: Artifact = {
        ...result,
        filename: selected.name,
        artifact_type: result.artifact_type,
        metadata: {
          validation: result.validation,
        },
      };

      if (isIndex) {
        setIndexArtifact(artifact);
      } else {
        setPrimaryArtifact(artifact);
      }

      setMessage(
        result.validation_status === "VALID"
          ? `${isIndex ? "Index" : "Variant file"} validated successfully.`
          : `${isIndex ? "Index" : "Variant file"} was stored but failed validation.`,
      );

      await refreshCase();

      if (!isIndex && result.validation_status === "VALID") {
        setStep(3);
      }

      if (isIndex) {
        setStep(4);
      }
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Upload failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const chooseVariant = (file: File | null) => {
    setVariantFile(file);

    if (file) {
      upload(file, false, specimenId);
    }
  };

  const chooseIndex = (file: File | null) => {
    setIndexFile(file);

    if (file && primaryArtifact) {
      upload(file, true);
    }
  };

  return (
    <div className="case-wizard-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">SIRALOOM VARIANT · CASE INTAKE</p>
          <h1>New genomic case</h1>
          <p className="lead">
            Create a traceable case, register its specimen, and validate the
            variant dataset before scientific analysis begins.
          </p>
        </div>

        <Link className="link-button" href="/app/dashboard">
          Back to dashboard
        </Link>
      </div>

      <section className="panel existing-cases-panel">
        <div className="panel-head">
          <div>
            <p className="eyebrow">CASE REGISTRY</p>
            <h2>Existing cases</h2>
            <p className="muted">Select a previously created case to continue its persisted workflow.</p>
          </div>
          <button className="secondary" onClick={loadCases} disabled={loadingCases}>
            {loadingCases ? "Refreshing…" : "Refresh cases"}
          </button>
        </div>
        {!cases.length ? (
          <div className="empty">
            <strong>No cases found</strong>
            <p>Create a case below. Cases are stored server-side in your organization.</p>
          </div>
        ) : (
          <div className="case-registry-list">
            {cases.map((item) => {
              const latestAnalysis = item.analyses?.[0];
              return (
                <button
                  key={item.case_id}
                  className={caseId === item.case_id ? "case-registry-item selected" : "case-registry-item"}
                  onClick={() => loadExistingCase(item.case_id)}
                  disabled={busy}
                >
                  <span>
                    <strong>{item.case_identifier}</strong>
                    <small>{pretty(item.status)} · {item.specimens?.length ?? 0} specimen(s)</small>
                  </span>
                  <span>
                    <small>{latestAnalysis ? `Analysis · ${pretty(latestAnalysis.status)}` : "No analysis yet"}</small>
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </section>

      <div className="wizard-steps">
        {steps.map((label, i) => (
          <div
            className={`wizard-step ${
              i === step ? "current" : ""
            } ${i < step ? "done" : ""}`}
            key={label}
          >
            <span>{i + 1}</span>
            <strong>{label}</strong>
          </div>
        ))}
      </div>

      {message && (
        <div className="notice success-notice">
          {message}
        </div>
      )}

      {error && (
        <div className="notice error-notice">
          <strong>Action could not be completed</strong>
          <span>{error}</span>
        </div>
      )}

      <section className="panel wizard-card">
        {step === 0 && (
          <form onSubmit={createCase}>
            <p className="eyebrow">STEP 01</p>

            <h2>Case information</h2>

            <p className="muted">
              The case is created inside your authenticated organization.
              Organization ownership is determined by the server.
            </p>

            <div className="form-grid">
              <label>
                Case identifier
                <input
                  value={caseIdentifier}
                  onChange={(e) => setCaseIdentifier(e.target.value)}
                  placeholder="e.g. SRL-2026-0001"
                  required
                />
              </label>

              <label>
                Language
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                >
                  <option value="en">English</option>
                  <option value="ar">Arabic</option>
                  <option value="bilingual">Bilingual</option>
                </select>
              </label>

              <label className="span-2">
                Clinical indication
                <textarea
                  value={indication}
                  onChange={(e) => setIndication(e.target.value)}
                  rows={4}
                  placeholder="Clinical question or indication relevant to this analysis"
                />
              </label>
            </div>

            <div className="actions-row">
              <button className="primary" disabled={busy}>
                {busy ? "Creating…" : "Create case"}
              </button>
            </div>
          </form>
        )}

        {step === 1 && (
          <div>
            <p className="eyebrow">STEP 02</p>

            <h2>Register specimen</h2>

            <p className="muted">
              A variant file must be associated with a specimen before it can
              enter the Phase 1 workflow.
            </p>

            <div className="form-grid">
              <label>
                Specimen identifier
                <input
                  value={specimenIdentifier}
                  onChange={(e) =>
                    setSpecimenIdentifier(e.target.value)
                  }
                  placeholder="e.g. SP-0001"
                />
              </label>

              <label>
                Specimen type
                <select
                  value={specimenType}
                  onChange={(e) => setSpecimenType(e.target.value)}
                >
                  <option>Blood</option>
                  <option>Saliva</option>
                  <option>Buccal</option>
                  <option>Tissue</option>
                  <option>Other</option>
                </select>
              </label>
            </div>

            <div className="actions-row">
              <button
                className="primary"
                onClick={createSpecimen}
                disabled={busy}
              >
                {busy ? "Registering…" : "Register specimen"}
              </button>
            </div>

            {caseData?.specimens?.length ? (
              <div className="mini-list">
                <strong>Registered specimens</strong>

                {caseData.specimens.map((s) => (
                  <button
                    key={s.specimen_id}
                    className={
                      specimenId === s.specimen_id
                        ? "selected-mini"
                        : "mini-row"
                    }
                    onClick={() => {
                      setSpecimenId(s.specimen_id);
                      setStep(2);
                    }}
                  >
                    <span>{s.specimen_identifier}</span>
                    <small>
                      {s.specimen_type || "Type not specified"}
                    </small>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        )}

        {step === 2 && (
          <div>
            <p className="eyebrow">STEP 03</p>

            <h2>Upload variant dataset</h2>

            <p className="muted">
              Supported: <strong>.vcf</strong>,{" "}
              <strong>.vcf.gz</strong>, and{" "}
              <strong>.vcf.bgz</strong>. The original artifact is preserved
              and SHA-256 is calculated from the uploaded content.
            </p>

            <div className="form-grid">
              <label>
                Reference genome
                <select
                  value={build}
                  onChange={(e) => setBuild(e.target.value)}
                >
                  <option value="GRCh38">GRCh38</option>
                  <option value="GRCh37">GRCh37</option>
                </select>
              </label>

              <label>
                Specimen
                <select
                  value={specimenId}
                  onChange={(e) => setSpecimenId(e.target.value)}
                >
                  {caseData?.specimens.map((s) => (
                    <option
                      key={s.specimen_id}
                      value={s.specimen_id}
                    >
                      {s.specimen_identifier}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <label className="dropzone file-picker">
              <span className="drop-icon">VCF</span>

              <div>
                <strong>
                  {variantFile?.name ??
                    "Choose a VCF / VCF.GZ / VCF.BGZ file"}
                </strong>

                <p>
                  Validation runs against the actual uploaded content. No
                  mock variant data is generated.
                </p>
              </div>

              <input
                type="file"
                accept=".vcf,.gz,.bgz"
                onChange={(e) =>
                  chooseVariant(e.target.files?.[0] ?? null)
                }
              />
            </label>

            {primaryArtifact && (
              <ArtifactCard artifact={primaryArtifact} />
            )}
          </div>
        )}

        {step === 3 && (
          <div>
            <p className="eyebrow">STEP 04 · OPTIONAL INDEX</p>

            <h2>Add a tabix/CSI index</h2>

            <p className="muted">
              Indexes are associated with the validated primary VCF. An index
              file alone is never treated as a variant dataset.
            </p>

            <label className="dropzone file-picker">
              <span className="drop-icon">IDX</span>

              <div>
                <strong>
                  {indexFile?.name ?? "Choose .tbi or .csi"}
                </strong>

                <p>
                  Expected pairing: {primaryArtifact?.filename}.tbi or{" "}
                  {primaryArtifact?.filename}.csi
                </p>
              </div>

              <input
                type="file"
                accept=".tbi,.csi"
                onChange={(e) =>
                  chooseIndex(e.target.files?.[0] ?? null)
                }
              />
            </label>

            {indexArtifact && (
              <ArtifactCard artifact={indexArtifact} />
            )}
          </div>
        )}

        {step === 4 && (
          <div>
            <p className="eyebrow">STEP 05 · READY CHECK</p>

            <h2>Review ingestion</h2>

            <p className="muted">
              Confirm the case is internally consistent before starting
              scientific analysis.
            </p>

            <div className="review-grid">
              <div>
                <span>Case</span>
                <strong>
                  {caseData?.case_identifier ?? caseIdentifier}
                </strong>
              </div>

              <div>
                <span>Specimen</span>
                <strong>
                  {caseData?.specimens.find(
                    (s) => s.specimen_id === specimenId,
                  )?.specimen_identifier ?? "—"}
                </strong>
              </div>

              <div>
                <span>Build</span>
                <strong>
                  {primaryArtifact?.genome_build ?? build}
                </strong>
              </div>

              <div>
                <span>Primary validation</span>
                <strong>
                  {pretty(
                    primaryArtifact?.validation_status ?? "PENDING",
                  )}
                </strong>
              </div>

              <div>
                <span>Index</span>
                <strong>
                  {indexArtifact
                    ? `${indexArtifact.filename} · ${pretty(
                        indexArtifact.validation_status,
                      )}`
                    : "Not supplied"}
                </strong>
              </div>

              <div>
                <span>Case state</span>
                <strong>{caseData?.status ?? "—"}</strong>
              </div>
            </div>

            {validPrimary ? (
              <div className="ready-callout">
                <strong>Ready for analysis</strong>

                <p>
                  The primary VCF passed structural validation and has an
                  explicit genome build. You can proceed to the existing
                  Variant workflow.
                </p>

                <Link
                  className="primary link-button"
                  href="/app/workspace"
                  onClick={() => {
                    if (caseId) {
                      window.localStorage.setItem("siraloom.case_id", caseId);
                      window.localStorage.setItem("siraloom.case_identifier", caseData?.case_identifier ?? caseIdentifier);
                      const latestAnalysis = caseData?.analyses?.[0];
                      if (latestAnalysis?.analysis_id) {
                        window.localStorage.setItem("siraloom.analysis_id", latestAnalysis.analysis_id);
                      }
                    }
                  }}
                >
                  Open Variant workspace
                </Link>
              </div>
            ) : (
              <div className="notice error-notice">
                The primary variant artifact is not valid. Resolve the
                validation failure before starting analysis.
              </div>
            )}

            <div className="artifact-list">
              {artifacts.map((a) => (
                <ArtifactCard
                  key={a.artifact_id}
                  artifact={a}
                />
              ))}
            </div>
          </div>
        )}

        {step > 0 && (
          <div className="wizard-footer">
            <button
              className="secondary"
              onClick={() =>
                setStep(Math.max(0, step - 1))
              }
            >
              Back
            </button>

            {step < 2 && canContinue && (
              <button
                className="primary"
                onClick={() => setStep(step + 1)}
              >
                Continue
              </button>
            )}

            {step === 2 &&
              primaryArtifact?.validation_status === "VALID" && (
                <button
                  className="primary"
                  onClick={() => setStep(3)}
                >
                  Continue to index
                </button>
              )}

            {step === 3 && (
              <button
                className="primary"
                onClick={() => setStep(4)}
              >
                Skip index & review
              </button>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function ArtifactCard({ artifact }: { artifact: Artifact }) {
  const valid = artifact.validation_status === "VALID";
  const validation = artifact.metadata?.validation;

  return (
    <div className="artifact-card">
      <div>
        <strong>{artifact.filename}</strong>

        <span>
          {artifact.artifact_type} ·{" "}
          {formatBytes(artifact.size_bytes)}
        </span>
      </div>

      <span
        className={`badge ${
          valid
            ? "success"
            : artifact.validation_status === "INVALID"
              ? "danger"
              : "neutral"
        }`}
      >
        {pretty(artifact.validation_status)}
      </span>

      <code>{artifact.sha256}</code>

      {validation !== undefined && (
        <details>
          <summary>Validation diagnostics</summary>

          <pre>
            {JSON.stringify(validation, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
