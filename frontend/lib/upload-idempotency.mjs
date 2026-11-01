const STORAGE_PREFIX = "siraloom.upload-idempotency.v1.";

/**
 * Build a privacy-preserving identity for one logical browser upload.
 * Only a SHA-256 digest of file metadata and upload scope is used as the
 * sessionStorage key; filenames and case identifiers are never persisted.
 *
 * The server remains authoritative: its request fingerprint includes the
 * uploaded byte digest, so metadata collisions cannot cause different bytes
 * to be accepted under an existing idempotency key.
 */
async function uploadFingerprint(context, digest) {
  const descriptor = JSON.stringify({
    version: 1,
    fileName: String(context.file.name ?? ""),
    fileSize: Number(context.file.size ?? 0),
    fileLastModified: Number(context.file.lastModified ?? 0),
    mediaType: String(context.file.type ?? ""),
    caseId: context.caseId,
    specimenId: context.specimenId || null,
    genomeBuild: context.genomeBuild,
  });
  const fingerprint = await digest(descriptor);
  if (!/^[a-f0-9]{64}$/.test(fingerprint)) {
    throw new Error("Upload identity digest must be a lowercase SHA-256 hex value.");
  }
  return fingerprint;
}

async function sha256(value) {
  if (!globalThis.crypto?.subtle) {
    throw new Error("Secure browser cryptography is unavailable; upload retry identity cannot be persisted safely.");
  }
  const bytes = new TextEncoder().encode(value);
  const digestBytes = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digestBytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/**
 * Get the pending idempotency key for this upload, or persist a new one.
 * sessionStorage survives reloads in the same tab but is cleared when the tab
 * session ends. Storage failures are surfaced rather than sending a key that
 * cannot be reused after a browser reload.
 */
export async function getOrCreateUploadIdempotencyAttempt(
  storage,
  context,
  createKey,
  digest = sha256,
) {
  if (
    !storage ||
    typeof storage.getItem !== "function" ||
    typeof storage.setItem !== "function"
  ) {
    throw new Error("Session storage is unavailable; upload retry identity cannot be persisted safely.");
  }
  const fingerprint = await uploadFingerprint(context, digest);
  const storageKey = STORAGE_PREFIX + fingerprint;
  let key = storage.getItem(storageKey);
  if (key === null) {
    key = createKey();
    if (typeof key !== "string" || !/^[!-~]{16,255}$/.test(key)) {
      throw new Error("Upload idempotency key generator returned an invalid key.");
    }
    storage.setItem(storageKey, key);
    if (storage.getItem(storageKey) !== key) {
      throw new Error("Upload idempotency key could not be persisted in this browser session.");
    }
  } else if (!/^[!-~]{16,255}$/.test(key)) {
    throw new Error("A malformed upload idempotency key is stored for this upload.");
  }
  return { key, storageKey, fingerprint };
}

/** Remove a completed attempt without disturbing a newer key at the same key. */
export function clearUploadIdempotencyAttempt(storage, attempt) {
  if (
    storage &&
    attempt &&
    typeof storage.getItem === "function" &&
    typeof storage.removeItem === "function" &&
    storage.getItem(attempt.storageKey) === attempt.key
  ) {
    storage.removeItem(attempt.storageKey);
  }
}
