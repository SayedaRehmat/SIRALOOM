import test from "node:test";
import assert from "node:assert/strict";
import { canFinalizeClinicalReports, canGenerateOrEvaluateReports } from "./report-permissions.mjs";

test("report generation and evaluation roles match backend case-write roles", () => {
  for (const role of ["platform_admin", "organization_admin", "lab_director", "clinical_geneticist", "bioinformatician", "lab_scientist"]) {
    assert.equal(canGenerateOrEvaluateReports(role), true);
  }
  for (const role of ["reviewer", "read_only", null, undefined]) {
    assert.equal(canGenerateOrEvaluateReports(role), false);
  }
});

test("reportability finalization and clinical sign-out require backend signatory roles", () => {
  for (const role of ["platform_admin", "organization_admin", "lab_director", "clinical_geneticist"]) {
    assert.equal(canFinalizeClinicalReports(role), true);
  }
  for (const role of ["reviewer", "bioinformatician", "lab_scientist", "read_only", null, undefined]) {
    assert.equal(canFinalizeClinicalReports(role), false);
  }
});
