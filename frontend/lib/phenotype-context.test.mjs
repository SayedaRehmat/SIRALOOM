import test from "node:test";
import assert from "node:assert/strict";
import { phenotypeContextView } from "./phenotype-context.mjs";

test("new phenotype context exposes matched terms without exposing a numeric score", () => {
  const view = phenotypeContextView({
    status: "CONTEXT_ONLY",
    matched_terms: ["HP:0000003"],
    score: 1,
  });

  assert.deepEqual(view, {
    status: "CONTEXT_ONLY",
    matchedTerms: ["HP:0000003"],
    showNoMatchedTerms: false,
    reason: null,
  });
  assert.equal("score" in view, false);
});

test("legacy scored evidence is presented as context only", () => {
  const view = phenotypeContextView({
    status: "SCORED",
    matched_terms: [],
    score: 0,
  });

  assert.equal(view.status, "CONTEXT_ONLY");
  assert.equal(view.showNoMatchedTerms, true);
  assert.equal("score" in view, false);
});

test("missing or malformed phenotype context stays absent", () => {
  assert.equal(phenotypeContextView(null), null);
  assert.equal(phenotypeContextView([]), null);
});
