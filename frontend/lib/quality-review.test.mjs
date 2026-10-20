import test from "node:test";
import assert from "node:assert/strict";
import { latestQualityAssessment, qualityMetricsFromObservations } from "./quality-review.mjs";

test("uses the API's newest-first assessment collection for the gate", () => {
  assert.equal(latestQualityAssessment([{ gate_status: "REVIEW" }, { gate_status: "PASS" }]).gate_status, "REVIEW");
  assert.equal(latestQualityAssessment([]), null);
  assert.equal(latestQualityAssessment(undefined), null);
});

test("builds assay metrics from latest observations and preserves unavailable values", () => {
  assert.deepEqual(qualityMetricsFromObservations([
    { metric_name: "depth", metric_value: 20 },
    { metric_name: "balance", metric_value: null },
    { metric_name: "depth", metric_value: 12 },
    { metric_name: "", metric_value: 7 },
  ]), { depth: 12, balance: null });
});
