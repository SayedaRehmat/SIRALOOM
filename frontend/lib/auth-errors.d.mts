type AuthFlow = "login" | "signup" | "reset" | "google";
type AuthErrorMessageKey =
  | "auth.failed"
  | "auth.googleFailed"
  | "auth.invalidCredentials"
  | "auth.invalidEmail"
  | "auth.resetFailed"
  | "auth.resetSent"
  | "auth.weakPassword";

export function authErrorMessageKey(error: unknown, flow: AuthFlow): AuthErrorMessageKey;
