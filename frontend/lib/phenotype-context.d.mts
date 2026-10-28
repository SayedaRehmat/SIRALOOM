export type PhenotypeContextView = {
  status: string | undefined;
  matchedTerms: string[];
  showNoMatchedTerms: boolean;
  reason: string | null;
};

export function phenotypeContextView(value: unknown): PhenotypeContextView | null;
