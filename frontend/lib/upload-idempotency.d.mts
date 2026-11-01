export type UploadIdempotencyContext = {
  file: Pick<File, "name" | "size" | "lastModified" | "type">;
  caseId: string;
  specimenId: string;
  genomeBuild: string;
};

export type UploadIdempotencyAttempt = {
  key: string;
  storageKey: string;
  fingerprint: string;
};

export type UploadIdempotencyStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function getOrCreateUploadIdempotencyAttempt(
  storage: UploadIdempotencyStorage,
  context: UploadIdempotencyContext,
  createKey: () => string,
  digest?: (value: string) => Promise<string>,
): Promise<UploadIdempotencyAttempt>;

export function clearUploadIdempotencyAttempt(
  storage: UploadIdempotencyStorage,
  attempt: UploadIdempotencyAttempt,
): void;
