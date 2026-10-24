import assert from "node:assert/strict";
import test from "node:test";
import { reanalysisActionState } from "./reanalysis-status.mjs";

test("queued and running child analyses cannot be dispatched again from the worklist", () => {
  assert.equal(reanalysisActionState("STARTED", "QUEUED"), "QUEUED");
  assert.equal(reanalysisActionState("STARTED", "RUNNING"), "RUNNING");
});

test("a successful child is shown as complete even if a stale candidate remains open", () => {
  assert.equal(reanalysisActionState("PENDING", "SUCCEEDED"), "COMPLETED");
});

test("missing and created children can be started from an actionable candidate", () => {
  assert.equal(reanalysisActionState("PENDING", null), "EXECUTE");
  assert.equal(reanalysisActionState("STARTED", "CREATED"), "EXECUTE");
});

test("failed children offer retry while non-retryable states remain blocked", () => {
  assert.equal(reanalysisActionState("STARTED", "FAILED"), "RETRY");
  assert.equal(reanalysisActionState("PENDING", "RESOURCE_FAILURE"), "RETRY");
  assert.equal(reanalysisActionState("STARTED", "REQUIRES_REVIEW"), "BLOCKED");
});

test("closed candidates do not offer execution", () => {
  assert.equal(reanalysisActionState("COMPLETED", null), "CLOSED");
  assert.equal(reanalysisActionState("REJECTED", "FAILED"), "CLOSED");
});
