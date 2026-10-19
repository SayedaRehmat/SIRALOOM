import assert from "node:assert/strict";
import test from "node:test";
import { authErrorMessageKey } from "./auth-errors.mjs";

test("email/password login failures do not expose account existence", () => {
  const keys = ["auth/invalid-credential", "auth/wrong-password", "auth/user-not-found"]
    .map((code) => authErrorMessageKey({ code, message: `provider detail for ${code}` }, "login"));

  assert.deepEqual(keys, Array(3).fill("auth.invalidCredentials"));
});

test("password reset uses the same confirmation for an unknown account", () => {
  assert.equal(
    authErrorMessageKey({ code: "auth/user-not-found", message: "email not found" }, "reset"),
    "auth.resetSent",
  );
  assert.equal(
    authErrorMessageKey({ code: "auth/email-not-found" }, "reset"),
    "auth.resetSent",
  );
});

test("password reset exposes only safe generic operational errors", () => {
  assert.equal(authErrorMessageKey(new Error("secret provider response"), "reset"), "auth.resetFailed");
  assert.equal(authErrorMessageKey({ code: "auth/invalid-email" }, "reset"), "auth.invalidEmail");
});

test("signup maps weak passwords and invalid addresses to localized message keys", () => {
  assert.equal(authErrorMessageKey({ code: "auth/weak-password" }, "signup"), "auth.weakPassword");
  assert.equal(authErrorMessageKey({ code: "auth/invalid-email" }, "signup"), "auth.invalidEmail");
  assert.equal(authErrorMessageKey({ code: "auth/email-already-in-use" }, "signup"), "auth.failed");
});

test("unknown provider errors never surface their raw message", () => {
  assert.equal(authErrorMessageKey(new Error("sensitive provider detail"), "login"), "auth.failed");
  assert.equal(authErrorMessageKey(new Error("sensitive provider detail"), "google"), "auth.googleFailed");
});
