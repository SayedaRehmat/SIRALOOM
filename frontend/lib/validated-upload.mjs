export function validatedArtifactId(result) {
  if (result?.validation_status !== "VALID" || result?.validation?.status !== "VALID") return "";
  return typeof result.artifact_id === "string" ? result.artifact_id : "";
}
