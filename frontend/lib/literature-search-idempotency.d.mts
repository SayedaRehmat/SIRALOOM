export type LiteratureSearchAttempt = {
  key: string;
  storageKey: string;
  fingerprint: string;
};

export type LiteratureSearchContext = {
  analysisId: string;
  variantId: string;
  geneSymbol: string;
};

export type LiteratureSearchStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function getOrCreateLiteratureSearchAttempt(
  storage: LiteratureSearchStorage,
  context: LiteratureSearchContext,
  createKey: () => string,
  digest?: (value: string) => Promise<string>,
): Promise<LiteratureSearchAttempt>;

export function clearLiteratureSearchAttempt(
  storage: LiteratureSearchStorage,
  attempt: LiteratureSearchAttempt | null,
): void;
