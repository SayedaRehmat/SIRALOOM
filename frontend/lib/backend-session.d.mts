export type BackendSessionState = "ACTIVE" | "RESTRICTED" | "UNAVAILABLE";

export function verifyBackendSession(
  idToken: string,
  options: {
    apiBase: string;
    fetchImpl?: typeof fetch;
    timeoutMs?: number;
  },
): Promise<BackendSessionState>;

export function canShowProtectedContent(state: {
  firebaseConfigured: boolean;
  signedIn: boolean;
  backendSession: BackendSessionState | "CHECKING";
}): boolean;
