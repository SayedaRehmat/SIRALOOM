const CONTEXT_KEYS = [
  "siraloom.case_id",
  "siraloom.case_identifier",
  "siraloom.analysis_id",
];
const AUTH_UID_KEY = "siraloom.auth_uid";

/** Do not render case-scoped workspace data until it belongs to the selection. */
export function isWorkspaceCaseReady(requestedCaseId, loadedCaseId) {
  return !requestedCaseId || requestedCaseId === loadedCaseId;
}

/** Keep analysis-derived pages scoped to the analysis that produced their data. */
export function isWorkspaceAnalysisReady(requestedAnalysisId, loadedAnalysisId) {
  return Boolean(requestedAnalysisId) && requestedAnalysisId === loadedAnalysisId;
}

/** Keep selected case context within one Firebase identity on this browser. */
export function syncWorkspaceContext(storage, userId) {
  const nextUserId = typeof userId === "string" && userId.trim() ? userId.trim() : null;

  try {
    const previousUserId = storage.getItem(AUTH_UID_KEY);
    if (!nextUserId || (previousUserId && previousUserId !== nextUserId)) {
      for (const key of CONTEXT_KEYS) storage.removeItem(key);
    }

    if (nextUserId) storage.setItem(AUTH_UID_KEY, nextUserId);
    else storage.removeItem(AUTH_UID_KEY);
  } catch {
    // Workspace state is a convenience; storage restrictions must not block auth.
  }
}
