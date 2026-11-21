import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import {
  clearLiteratureSearchAttempt,
  getOrCreateLiteratureSearchAttempt,
} from "./literature-search-idempotency.mjs";

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
const context = { analysisId: "analysis-sensitive", variantId: "variant-sensitive", geneSymbol: "PAH" };

test("reuses the opaque search key after a page reload", async () => {
  const storage = createStorage();
  const first = await getOrCreateLiteratureSearchAttempt(storage, context, () => "pubmed-key-00000001", digest);
  const reloaded = await getOrCreateLiteratureSearchAttempt(storage, { ...context }, () => "pubmed-key-00000002", digest);
  assert.equal(reloaded.key, first.key);
  assert.equal(reloaded.storageKey, first.storageKey);
});

test("isolates search keys by analysis, variant, and gene without storing those values", async () => {
  const storage = createStorage();
  const first = await getOrCreateLiteratureSearchAttempt(storage, context, () => "pubmed-key-00000001", digest);
  const second = await getOrCreateLiteratureSearchAttempt(
    storage,
    { ...context, geneSymbol: "CFTR" },
    () => "pubmed-key-00000002",
    digest,
  );
  assert.notEqual(first.storageKey, second.storageKey);
  const serialized = JSON.stringify(storage.entries());
  assert.equal(serialized.includes("analysis-sensitive"), false);
  assert.equal(serialized.includes("variant-sensitive"), false);
  assert.equal(serialized.includes("PAH"), false);
});

test("clears only the completed search attempt", async () => {
  const storage = createStorage();
  const attempt = await getOrCreateLiteratureSearchAttempt(storage, context, () => "pubmed-key-00000001", digest);
  clearLiteratureSearchAttempt(storage, attempt);
  assert.equal(storage.getItem(attempt.storageKey), null);
});

test("fails closed when secure identity storage cannot be used", async () => {
  await assert.rejects(
    () => getOrCreateLiteratureSearchAttempt(null, context, () => "pubmed-key-00000001", digest),
    /Session storage is unavailable/,
  );
});
