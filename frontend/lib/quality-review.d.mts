export type QualityAssessment = {
  id?: string;
  status?: string;
  gate_status?: string;
  clinical_gate_status?: string;
  is_current?: boolean;
  profile_name?: string | null;
  profile_version?: string | null;
  reviewer_note?: string | null;
  evaluated_rules?: Array<{
    metric: string;
    value: number | null;
    status: string;
    direction: string;
    threshold?: number | null;
    minimum?: number | null;
    maximum?: number | null;
    severity?: string;
  }>;
};

export function latestQualityAssessment(
  assessments: QualityAssessment[] | null | undefined,
): QualityAssessment | null;

export function qualityMetricsFromObservations(
  observations: Array<{ metric_name?: string; metric_value?: number | string | null }> | null | undefined,
): Record<string, number | null>;
