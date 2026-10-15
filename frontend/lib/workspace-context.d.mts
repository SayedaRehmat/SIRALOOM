export function syncWorkspaceContext(
  storage: Pick<Storage, "getItem" | "setItem" | "removeItem">,
  userId: string | null,
): void;
