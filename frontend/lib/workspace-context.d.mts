export function syncWorkspaceContext(
  storage: Pick<Storage, "getItem" | "setItem" | "removeItem">,
  userId: string | null,
): void;
export function isWorkspaceCaseReady(requestedCaseId: string, loadedCaseId: string | null | undefined): boolean;
