const INVALID_LOGIN_CODES = new Set([
  "auth/invalid-credential",
  "auth/wrong-password",
  "auth/user-not-found",
]);

const MISSING_ACCOUNT_CODES = new Set([
  "auth/user-not-found",
  "auth/email-not-found",
]);

function firebaseErrorCode(error) {
  if (!error || typeof error !== "object" || !("code" in error)) return "";
  return typeof error.code === "string" ? error.code : "";
}

export function authErrorMessageKey(error, flow) {
  const code = firebaseErrorCode(error);

  if (flow === "reset") {
    if (code === "auth/invalid-email") return "auth.invalidEmail";
    // Keep reset responses indistinguishable when email-enumeration protection
    // is disabled and Firebase reports an unknown address.
    if (MISSING_ACCOUNT_CODES.has(code)) return "auth.resetSent";
    return "auth.resetFailed";
  }

  if (code === "auth/invalid-email") return "auth.invalidEmail";
  if (flow === "login" && INVALID_LOGIN_CODES.has(code)) return "auth.invalidCredentials";
  if (flow === "signup" && code === "auth/weak-password") return "auth.weakPassword";

  if (flow === "google") return "auth.googleFailed";
  return "auth.failed";
}
