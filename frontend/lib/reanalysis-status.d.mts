export function reanalysisActionState(
  candidateStatus: string,
  childAnalysisStatus?: string | null,
): "QUEUED" | "RUNNING" | "COMPLETED" | "CLOSED" | "EXECUTE" | "RETRY" | "BLOCKED";
