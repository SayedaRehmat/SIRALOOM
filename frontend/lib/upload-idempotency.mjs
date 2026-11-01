/**
 * Reuse one opaque idempotency key for retries of the same logical browser upload.
 * A changed file or upload scope receives a new key.
 */
export function getOrCreateUploadIdempotencyAttempt(previous, next, createKey) {
  if (
    previous &&
    previous.file === next.file &&
    previous.caseId === next.caseId &&
    previous.specimenId === next.specimenId &&
    previous.genomeBuild === next.genomeBuild
  ) {
    return previous;
  }
  return { ...next, key: createKey() };
}
