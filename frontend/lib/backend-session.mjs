export async function verifyBackendSession(idToken, { apiBase, fetchImpl = fetch, timeoutMs = 10_000 }) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(`${apiBase.replace(/\/$/, "")}/auth/session`, {
      headers: { Authorization: `Bearer ${idToken}` },
      signal: controller.signal,
    });
    if (response.ok) return "ACTIVE";
    if (response.status === 401 || response.status === 403) return "RESTRICTED";
    return "UNAVAILABLE";
  } catch {
    return "UNAVAILABLE";
  } finally {
    clearTimeout(timeout);
  }
}

export function canShowProtectedContent({ firebaseConfigured, signedIn, backendSession }) {
  return !firebaseConfigured || (signedIn && backendSession === "ACTIVE");
}
