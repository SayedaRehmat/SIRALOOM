export type UploadIdempotencyContext = {
  file: File;
  caseId: string;
  specimenId: string;
  genomeBuild: string;
};

export type UploadIdempotencyAttempt = UploadIdempotencyContext & {
  key: string;
};

export function getOrCreateUploadIdempotencyAttempt(
  previous: UploadIdempotencyAttempt | null,
  next: UploadIdempotencyContext,
  createKey: () => string,
): UploadIdempotencyAttempt;
