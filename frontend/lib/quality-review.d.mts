export type QualityAssessment = {
  id?: string;
  status?: string;
  gate_status?: string;
  profile_name?: string | null;
  profile_version?: string | null;
  reviewer_note?: string | null;
};

export function latestQualityAssessment(
  assessments: QualityAssessment[] | null | undefined,
): QualityAssessment | null;

export function qualityMetricsFromObservations(
  observations: Array<{ metric_name?: string; metric_value?: number | string | null }> | null | undefined,
): Record<string, number | null>;
