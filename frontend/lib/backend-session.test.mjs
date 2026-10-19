import assert from "node:assert/strict";
import test from "node:test";
import { canShowProtectedContent, verifyBackendSession } from "./backend-session.mjs";

test("protected content requires a verified backend session in configured deployments", () => {
  assert.equal(canShowProtectedContent({ firebaseConfigured: true, signedIn: true, backendSession: "ACTIVE" }), true);
  for (const backendSession of ["CHECKING", "RESTRICTED", "UNAVAILABLE"]) {
    assert.equal(canShowProtectedContent({ firebaseConfigured: true, signedIn: true, backendSession }), false);
  }
  assert.equal(canShowProtectedContent({ firebaseConfigured: true, signedIn: false, backendSession: "ACTIVE" }), false);
  assert.equal(canShowProtectedContent({ firebaseConfigured: false, signedIn: false, backendSession: "UNAVAILABLE" }), true);
});

test("verifies the current backend session with the Firebase bearer token", async () => {
  let request;
  const state = await verifyBackendSession("firebase-token", {
    apiBase: "https://api.example.test/api/v1/",
    fetchImpl: async (url, init) => {
      request = { url, init };
      return new Response(null, { status: 200 });
    },
  });

  assert.equal(state, "ACTIVE");
  assert.equal(request.url, "https://api.example.test/api/v1/auth/session");
  assert.equal(request.init.headers.Authorization, "Bearer firebase-token");
  assert.ok(request.init.signal instanceof AbortSignal);
});

test("treats revoked or unauthorized backend identities as restricted", async () => {
  for (const status of [401, 403]) {
    assert.equal(
      await verifyBackendSession("token", {
        apiBase: "https://api.example.test",
        fetchImpl: async () => new Response(null, { status }),
      }),
      "RESTRICTED",
    );
  }
});

test("fails closed on service errors and request timeouts without declaring the identity revoked", async () => {
  assert.equal(
    await verifyBackendSession("token", {
      apiBase: "https://api.example.test",
      fetchImpl: async () => new Response(null, { status: 503 }),
    }),
    "UNAVAILABLE",
  );
  assert.equal(
    await verifyBackendSession("token", {
      apiBase: "https://api.example.test",
      fetchImpl: async () => { throw new Error("network failure"); },
    }),
    "UNAVAILABLE",
  );
  assert.equal(
    await verifyBackendSession("token", {
      apiBase: "https://api.example.test",
      timeoutMs: 5,
      fetchImpl: async (_url, { signal }) => new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
      }),
    }),
    "UNAVAILABLE",
  );
});
