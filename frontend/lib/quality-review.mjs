export function latestQualityAssessment(assessments) {
  return Array.isArray(assessments) ? assessments[0] ?? null : null;
}

// The quality API returns observations oldest first. Keep the latest recorded
// value per metric; null remains explicitly unavailable rather than passing.
export function qualityMetricsFromObservations(observations) {
  const metrics = {};
  for (const observation of Array.isArray(observations) ? observations : []) {
    if (!observation || typeof observation.metric_name !== "string" || !observation.metric_name) continue;
    const value = observation.metric_value;
    metrics[observation.metric_name] = value == null ? null : Number(value);
  }
  return metrics;
}
