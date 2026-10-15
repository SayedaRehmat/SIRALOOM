import assert from "node:assert/strict";
import test from "node:test";
import { safeRedirectPath } from "./safe-redirect.mjs";

test("preserves an internal invitation URL and its token", () => {
  assert.equal(
    safeRedirectPath("/onboarding/invite?token=abc123"),
    "/onboarding/invite?token=abc123",
  );
});

test("rejects absolute, protocol-relative, backslash, and control-character redirects", () => {
  for (const value of [
    "https://attacker.example/",
    "//attacker.example/",
    "/\\attacker.example/",
    "/app\n/evil",
    "javascript:alert(1)",
  ]) {
    assert.equal(safeRedirectPath(value), null, value);
  }
});

test("normalizes dot segments while keeping the destination on this origin", () => {
  assert.equal(safeRedirectPath("/cases/../onboarding/invite?token=x"), "/onboarding/invite?token=x");
});
