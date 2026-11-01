import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import {
  clearUploadIdempotencyAttempt,
  getOrCreateUploadIdempotencyAttempt,
} from "./upload-idempotency.mjs";

function createStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
    entries: () => Array.from(values.entries()),
  };
}

const digest = async (value) => createHash("sha256").update(value).digest("hex");

function file(name = "sample.vcf", overrides = {}) {
  return {
    name,
    size: 1024,
    lastModified: 1730000000000,
    type: "text/vcf",
    ...overrides,
  };
}

test("reuses the persisted key after a reload and File object recreation", async () => {
  const storage = createStorage();
  const context = {
    file: file(),
    caseId: "case-1",
    specimenId: "specimen-1",
    genomeBuild: "GRCh38",
  };
  const first = await getOrCreateUploadIdempotencyAttempt(
    storage, context, () => "upload-key-0000001", digest,
  );

  // Simulate a browser reload: the in-memory File and component state are gone.
  const reloaded = await getOrCreateUploadIdempotencyAttempt(
    storage,
    { ...context, file: file() },
    () => "upload-key-0000002",
    digest,
  );

  assert.equal(first.key, "upload-key-0000001");
  assert.equal(reloaded.key, first.key);
  assert.equal(reloaded.storageKey, first.storageKey);
});

test("isolates keys by file metadata and clinical upload scope", async () => {
  const storage = createStorage();
  const base = {
    file: file(),
    caseId: "case-1",
    specimenId: "specimen-1",
    genomeBuild: "GRCh38",
  };
  const first = await getOrCreateUploadIdempotencyAttempt(
    storage, base, () => "upload-key-0000001", digest,
  );
  const changed = await getOrCreateUploadIdempotencyAttempt(
    storage,
    { ...base, specimenId: "specimen-2" },
    () => "upload-key-0000002",
    digest,
  );
  assert.notEqual(changed.key, first.key);
  assert.notEqual(changed.storageKey, first.storageKey);
});

test("stores only a metadata digest and opaque key, never raw case or filename", async () => {
  const storage = createStorage();
  await getOrCreateUploadIdempotencyAttempt(
    storage,
    {
      file: file("patient-name-sensitive.vcf"),
      caseId: "case-sensitive-identifier",
      specimenId: "specimen-sensitive-identifier",
      genomeBuild: "GRCh38",
    },
    () => "upload-key-0000001",
    digest,
  );
  const [[storedKey, storedValue]] = storage.entries();
  assert.match(storedKey, /^siraloom\.upload-idempotency\.v1\.[a-f0-9]{64}$/);
  assert.equal(storedValue, "upload-key-0000001");
  assert.equal(storedKey.includes("patient-name-sensitive"), false);
  assert.equal(storedKey.includes("case-sensitive-identifier"), false);
});

test("clears only the completed attempt and preserves a newer replacement", async () => {
  const storage = createStorage();
  const context = {
    file: file(),
    caseId: "case-1",
    specimenId: "specimen-1",
    genomeBuild: "GRCh38",
  };
  const attempt = await getOrCreateUploadIdempotencyAttempt(
    storage, context, () => "upload-key-0000001", digest,
  );
  storage.setItem(attempt.storageKey, "upload-key-0000002");
  clearUploadIdempotencyAttempt(storage, attempt);
  assert.equal(storage.getItem(attempt.storageKey), "upload-key-0000002");
});

test("fails closed when session storage is unavailable or key persistence fails", async () => {
  const context = {
    file: file(),
    caseId: "case-1",
    specimenId: "specimen-1",
    genomeBuild: "GRCh38",
  };
  await assert.rejects(
    getOrCreateUploadIdempotencyAttempt(null, context, () => "upload-key-0000001", digest),
    /Session storage is unavailable/,
  );
  await assert.rejects(
    getOrCreateUploadIdempotencyAttempt(
      { getItem: () => null, setItem: () => {}, },
      context,
      () => "upload-key-0000001",
      digest,
    ),
    /could not be persisted/,
  );
});
