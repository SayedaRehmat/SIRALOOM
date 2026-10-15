export function selectCaseInputArtifacts(
  artifacts: Array<Record<string, any>>,
  specimens: Array<Record<string, any>>,
): {
  primary: Record<string, any> | null;
  index: Record<string, any> | null;
  specimenId: string;
};
export function selectPrimaryAfterUpload(
  currentPrimary: Record<string, any> | null,
  uploadedPrimary: Record<string, any> | null,
): Record<string, any> | null;
