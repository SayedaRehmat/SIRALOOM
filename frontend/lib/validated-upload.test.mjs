import assert from "node:assert/strict";
import test from "node:test";
import { validatedArtifactId } from "./validated-upload.mjs";

test("only a persisted artifact with successful VCF validation can start analysis", () => {
  assert.equal(validatedArtifactId({
    artifact_id: "valid-id",
    validation_status: "VALID",
    validation: { status: "VALID" },
  }), "valid-id");
  assert.equal(validatedArtifactId({
    artifact_id: "invalid-id",
    validation_status: "INVALID",
    validation: { status: "INVALID", errors: ["bad header"] },
  }), "");
  assert.equal(validatedArtifactId({
    artifact_id: "inconsistent-id",
    validation_status: "VALID",
    validation: { status: "INVALID" },
  }), "");
  assert.equal(validatedArtifactId({ validation_status: "VALID", validation: { status: "VALID" } }), "");
});
