export const apiBase = (process.env.NEXT_PUBLIC_SIRALOOM_API_BASE ?? "http://localhost:8000/api/v1").replace(/\/$/, "");

/**
 * Asks the backend whether this Firebase identity already has a provisioned SIRALOOM
 * user + active organization membership.
 *
 * The backend, not the browser, is the source of truth for this: `get_current_principal`
 * returns 403 "No SIRALOOM user is provisioned for this identity" for a brand-new
 * identity (whether they arrived via email/password or Google), and 200 with a session
 * for anyone already onboarded. This lets one Google button serve both the login and
 * signup pages without the frontend having to guess which case it's in.
 */
export async function resolveSessionDestination(
  idToken: string,
  fallbackOnError: "/app/dashboard" | "/onboarding" = "/onboarding",
): Promise<"/app/dashboard" | "/onboarding"> {
  try {
    const res = await fetch(`${apiBase}/auth/session`, { headers: { Authorization: `Bearer ${idToken}` } });
    if (res.ok) return "/app/dashboard";
    if (res.status === 403) return "/onboarding";
    return fallbackOnError;
  } catch {
    // Network/backend hiccup: fall back to the caller's best guess rather than stranding the user.
    return fallbackOnError;
  }
}
