export function phenotypeContextView(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const status = value.status === "SCORED" ? "CONTEXT_ONLY" : value.status;
  const matchedTerms = Array.isArray(value.matched_terms)
    ? value.matched_terms.filter((term) => typeof term === "string")
    : [];
  return {
    status,
    matchedTerms,
    showNoMatchedTerms: status === "CONTEXT_ONLY" && matchedTerms.length === 0,
    reason: typeof value.reason === "string" ? value.reason : null,
  };
}
