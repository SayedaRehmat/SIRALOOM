export function syncWorkspaceContext(
  storage: Pick<Storage, "getItem" | "setItem" | "removeItem">,
  userId: string | null,
): void;
export function isWorkspaceCaseReady(requestedCaseId: string, loadedCaseId: string | null | undefined): boolean;
export function isWorkspaceAnalysisReady(requestedAnalysisId: string, loadedAnalysisId: string | null | undefined): boolean;
export function workspaceIdentityKey(userId: string | null | undefined): string;
