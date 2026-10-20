const CASE_ACCESS_ADMIN_ROLES = new Set([
  "platform_admin",
  "organization_admin",
  "lab_director",
]);

export function canManageCaseAccessRole(role) {
  return CASE_ACCESS_ADMIN_ROLES.has(role);
}
