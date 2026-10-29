/**
 * Select the latest validated primary VCF and only its explicitly paired index.
 * @param {Array<Record<string, any>>} artifacts
 * @param {Array<Record<string, any>>} specimens
 */
export function selectCaseInputArtifacts(artifacts, specimens) {
  const primary = artifacts.find(
    (artifact) => artifact.artifact_type === "VCF" && artifact.validation_status === "VALID",
  ) ?? null;
  const index = primary
    ? artifacts.find(
      (artifact) =>
        ["VCF_INDEX_TBI", "VCF_INDEX_CSI"].includes(artifact.artifact_type) &&
        artifact.paired_artifact_id === primary.artifact_id,
    ) ?? null
    : null;

  return {
    primary,
    index,
    specimenId: primary?.specimen_id ?? specimens[0]?.specimen_id ?? "",
  };
}

/** Keep a valid selected input when a replacement upload is rejected. */
export function selectPrimaryAfterUpload(currentPrimary, uploadedPrimary) {
  if (uploadedPrimary?.validation_status === "VALID") return uploadedPrimary;
  if (currentPrimary?.validation_status === "VALID") return currentPrimary;
  return uploadedPrimary ?? null;
}

/** Keep server-reported validation warnings visible in the accession upload flow. */
export function uploadValidationMessage({
  status,
  label,
  successText,
  warningLabel,
  failureText,
  warnings = [],
  errors = [],
}) {
  if (status === "VALID") {
    const visibleWarnings = (Array.isArray(warnings) ? warnings : [])
      .filter((value) => typeof value === "string" && value.trim());
    return `${label} ${successText}${visibleWarnings.length ? ` ${warningLabel}: ${visibleWarnings.join(" ")}` : ""}`;
  }
  const visibleErrors = (Array.isArray(errors) ? errors : [])
    .filter((value) => typeof value === "string" && value.trim());
  return `${label} ${failureText}${visibleErrors.length ? ` ${visibleErrors.join(" ")}` : ""}`;
}
