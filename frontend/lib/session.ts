import { sessionDestination } from "./session-destination.mjs";

export const apiBase = (process.env.NEXT_PUBLIC_SIRALOOM_API_BASE ?? "http://localhost:8000/api/v1").replace(/\/$/, "");

/**
 * Asks the backend whether this Firebase identity already has a provisioned SIRALOOM
 * user + active organization membership.
 *
 * The backend, not the browser, is the source of truth for this: `get_current_principal`
 * identifies a brand-new Firebase identity with a stable response header. Other 403
 * responses mean the identity exists but is not currently authorized for a session.
 * Temporary API failures are never treated as successful authentication.
 */
export async function resolveSessionDestination(
  idToken: string,
  fallbackWhenUnprovisioned: string = "/onboarding",
  redirectWhenProvisioned: string | null = null,
): Promise<string> {
  try {
    const res = await fetch(`${apiBase}/auth/session`, { headers: { Authorization: `Bearer ${idToken}` } });
    return sessionDestination({
      ok: res.ok,
      status: res.status,
      sessionState: res.headers.get("X-Siraloom-Session-State"),
      fallbackWhenUnprovisioned,
      redirectWhenProvisioned,
    });
  } catch {
    return "/login?access=unavailable";
  }
}
