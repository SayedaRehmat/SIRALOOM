import assert from "node:assert/strict";
import test from "node:test";
import { getOrCreateUploadIdempotencyAttempt } from "./upload-idempotency.mjs";

test("reuses the same key when retrying the same logical upload", () => {
  const file = { name: "sample.vcf" };
  const context = { file, caseId: "case-1", specimenId: "specimen-1", genomeBuild: "GRCh38" };
  const first = getOrCreateUploadIdempotencyAttempt(null, context, () => "key-1");
  const retry = getOrCreateUploadIdempotencyAttempt(first, context, () => "key-2");
  assert.equal(first.key, "key-1");
  assert.equal(retry.key, "key-1");
  assert.equal(retry, first);
});

test("generates a new key when file or upload scope changes", () => {
  const file = { name: "sample.vcf" };
  const first = getOrCreateUploadIdempotencyAttempt(null, {
    file, caseId: "case-1", specimenId: "specimen-1", genomeBuild: "GRCh38",
  }, () => "key-1");
  const changed = getOrCreateUploadIdempotencyAttempt(first, {
    file, caseId: "case-1", specimenId: "specimen-2", genomeBuild: "GRCh38",
  }, () => "key-2");
  assert.equal(changed.key, "key-2");
  assert.notEqual(changed, first);
});
