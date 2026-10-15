import assert from "node:assert/strict";
import test from "node:test";
import { isWorkspaceCaseReady, syncWorkspaceContext } from "./workspace-context.mjs";

test("case workspace is hidden until the selected case has loaded", () => {
  assert.equal(isWorkspaceCaseReady("case-b", "case-a"), false);
  assert.equal(isWorkspaceCaseReady("case-b", null), false);
  assert.equal(isWorkspaceCaseReady("case-b", "case-b"), true);
  assert.equal(isWorkspaceCaseReady("", null), true);
});

function createStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    snapshot: () => Object.fromEntries(values),
  };
}

test("preserves selected case context for the same identity", () => {
  const storage = createStorage({
    "siraloom.auth_uid": "user-a",
    "siraloom.case_id": "case-a",
    "siraloom.case_identifier": "LAB-1",
    "siraloom.analysis_id": "analysis-a",
  });

  syncWorkspaceContext(storage, "user-a");

  assert.equal(storage.getItem("siraloom.case_id"), "case-a");
  assert.equal(storage.getItem("siraloom.analysis_id"), "analysis-a");
});

test("clears selected case context when the Firebase identity changes", () => {
  const storage = createStorage({
    "siraloom.auth_uid": "user-a",
    "siraloom.case_id": "case-a",
    "siraloom.case_identifier": "LAB-1",
    "siraloom.analysis_id": "analysis-a",
  });

  syncWorkspaceContext(storage, "user-b");

  assert.equal(storage.getItem("siraloom.case_id"), null);
  assert.equal(storage.getItem("siraloom.case_identifier"), null);
  assert.equal(storage.getItem("siraloom.analysis_id"), null);
  assert.equal(storage.getItem("siraloom.auth_uid"), "user-b");
});

test("clears selected case context on signout", () => {
  const storage = createStorage({
    "siraloom.auth_uid": "user-a",
    "siraloom.case_id": "case-a",
    "siraloom.analysis_id": "analysis-a",
  });

  syncWorkspaceContext(storage, null);

  assert.equal(storage.getItem("siraloom.case_id"), null);
  assert.equal(storage.getItem("siraloom.analysis_id"), null);
  assert.equal(storage.getItem("siraloom.auth_uid"), null);
});

test("storage errors do not escape into the authentication callback", () => {
  const storage = {
    getItem() { throw new Error("storage unavailable"); },
    setItem() { throw new Error("storage unavailable"); },
    removeItem() { throw new Error("storage unavailable"); },
  };

  assert.doesNotThrow(() => syncWorkspaceContext(storage, "user-a"));
});
