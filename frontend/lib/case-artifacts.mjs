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
