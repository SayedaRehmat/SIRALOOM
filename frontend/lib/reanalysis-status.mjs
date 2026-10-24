const actionableCandidateStatuses = new Set(["PENDING", "STARTED"]);
const retryableChildStatuses = new Set(["CREATED", "FAILED", "RESOURCE_FAILURE"]);

export function reanalysisActionState(candidateStatus, childAnalysisStatus) {
  if (childAnalysisStatus === "QUEUED") return "QUEUED";
  if (childAnalysisStatus === "RUNNING") return "RUNNING";
  if (childAnalysisStatus === "SUCCEEDED") return "COMPLETED";
  if (!actionableCandidateStatuses.has(candidateStatus)) return "CLOSED";
  if (childAnalysisStatus == null || retryableChildStatuses.has(childAnalysisStatus)) {
    return childAnalysisStatus === "FAILED" || childAnalysisStatus === "RESOURCE_FAILURE"
      ? "RETRY"
      : "EXECUTE";
  }
  return "BLOCKED";
}
