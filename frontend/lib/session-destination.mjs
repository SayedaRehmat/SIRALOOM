import { safeRedirectPath } from "./safe-redirect.mjs";

export function sessionDestination({
  ok,
  status,
  sessionState,
  fallbackWhenUnprovisioned = "/onboarding",
  redirectWhenProvisioned = null,
}) {
  if (ok) return safeRedirectPath(redirectWhenProvisioned) ?? "/app/dashboard";
  if (status === 403 && sessionState === "UNPROVISIONED") {
    const fallback = safeRedirectPath(fallbackWhenUnprovisioned);
    const isInvitationRoute = fallback
      && new URL(fallback, "https://siraloom.invalid").pathname === "/onboarding/invite";
    return isInvitationRoute ? fallback : "/onboarding";
  }
  if (status === 403) return "/login?access=restricted";
  return "/login?access=unavailable";
}
