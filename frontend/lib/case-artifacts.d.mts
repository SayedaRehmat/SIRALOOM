export function selectCaseInputArtifacts(
  artifacts: Array<Record<string, any>>,
  specimens: Array<Record<string, any>>,
): {
  primary: Record<string, any> | null;
  index: Record<string, any> | null;
  specimenId: string;
};
export function selectPrimaryAfterUpload<T extends { validation_status?: string }>(
  currentPrimary: T | null,
  uploadedPrimary: T | null,
): T | null;
