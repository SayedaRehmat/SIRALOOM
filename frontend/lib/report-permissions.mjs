// Keep visible report actions aligned with backend CASE_WRITE_ROLES and
// REPORT_FINALIZE_ROLES. The API remains the authorization boundary.
const REPORT_WRITE_ROLES = new Set([
  "platform_admin",
  "organization_admin",
  "lab_director",
  "clinical_geneticist",
  "bioinformatician",
  "lab_scientist",
]);

const REPORT_FINALIZE_ROLES = new Set([
  "platform_admin",
  "organization_admin",
  "lab_director",
  "clinical_geneticist",
]);

export function canGenerateOrEvaluateReports(role) {
  return REPORT_WRITE_ROLES.has(role);
}

export function canFinalizeClinicalReports(role) {
  return REPORT_FINALIZE_ROLES.has(role);
}

export function canSubmitReportSignout(role, reason) {
  return canFinalizeClinicalReports(role)
    && typeof reason === "string"
    && reason.trim().length > 0;
}
