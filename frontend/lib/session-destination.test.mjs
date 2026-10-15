import assert from "node:assert/strict";
import test from "node:test";
import { sessionDestination } from "./session-destination.mjs";

test("an active provisioned session may use a safe requested destination", () => {
  assert.equal(
    sessionDestination({ ok: true, status: 200, redirectWhenProvisioned: "/app/cases?case=1" }),
    "/app/cases?case=1",
  );
});

test("only an explicitly unprovisioned identity enters onboarding", () => {
  assert.equal(
    sessionDestination({ ok: false, status: 403, sessionState: "UNPROVISIONED" }),
    "/onboarding",
  );
  assert.equal(
    sessionDestination({ ok: false, status: 403, sessionState: null }),
    "/login?access=restricted",
  );
});

test("unprovisioned identities can continue only to invitation acceptance, not requested protected routes", () => {
  assert.equal(
    sessionDestination({
      ok: false,
      status: 403,
      sessionState: "UNPROVISIONED",
      fallbackWhenUnprovisioned: "/onboarding/invite?token=secret",
    }),
    "/onboarding/invite?token=secret",
  );
  assert.equal(
    sessionDestination({
      ok: false,
      status: 403,
      sessionState: "UNPROVISIONED",
      fallbackWhenUnprovisioned: "/app/dashboard",
    }),
    "/onboarding",
  );
});

test("unexpected HTTP failures do not become authenticated dashboard redirects", () => {
  assert.equal(
    sessionDestination({ ok: false, status: 503 }),
    "/login?access=unavailable",
  );
});
