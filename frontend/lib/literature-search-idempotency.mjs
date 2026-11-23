const STORAGE_PREFIX = "siraloom.literature-search-idempotency.v1.";

async function sha256(value) {
  if (!globalThis.crypto?.subtle) {
    throw new Error("Secure browser cryptography is unavailable; search retry identity cannot be persisted safely.");
  }
  const bytes = new TextEncoder().encode(value);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function getOrCreateLiteratureSearchAttempt(storage, context, createKey, digest = sha256) {
  if (!storage || typeof storage.getItem !== "function" || typeof storage.setItem !== "function") {
    throw new Error("Session storage is unavailable; search retry identity cannot be persisted safely.");
  }
  const descriptor = JSON.stringify({
    version: 1,
    analysisId: String(context.analysisId ?? ""),
    variantId: String(context.variantId ?? ""),
    geneSymbol: String(context.geneSymbol ?? "").trim().toUpperCase(),
  });
  if (!context.analysisId || !context.variantId || !context.geneSymbol) {
    throw new Error("Analysis, variant, and annotated gene are required to create a search retry identity.");
  }
  const fingerprint = await digest(descriptor);
  if (!/^[a-f0-9]{64}$/.test(fingerprint)) {
    throw new Error("Search identity digest must be a lowercase SHA-256 hex value.");
  }
  const storageKey = STORAGE_PREFIX + fingerprint;
  let key = storage.getItem(storageKey);
  if (key === null) {
    key = createKey();
    if (typeof key !== "string" || !/^[!-~]{16,255}$/.test(key)) {
      throw new Error("Search idempotency key generator returned an invalid key.");
    }
    storage.setItem(storageKey, key);
    if (storage.getItem(storageKey) !== key) {
      throw new Error("Search idempotency key could not be persisted in this browser session.");
    }
  } else if (typeof key !== "string" || !/^[!-~]{16,255}$/.test(key)) {
    throw new Error("A malformed search idempotency key is stored for this search.");
  }
  return { key, storageKey, fingerprint };
}

export function clearLiteratureSearchAttempt(storage, attempt) {
  if (
    storage && attempt && typeof storage.getItem === "function" && typeof storage.removeItem === "function" &&
    storage.getItem(attempt.storageKey) === attempt.key
  ) {
    storage.removeItem(attempt.storageKey);
  }
}
