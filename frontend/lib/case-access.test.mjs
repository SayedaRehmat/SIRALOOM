import test from "node:test";
import assert from "node:assert/strict";
import { canManageCaseAccessRole } from "./case-access.mjs";

test("case assignment manager roles match the server authorization roles", () => {
  for (const role of ["platform_admin", "organization_admin", "lab_director"]) {
    assert.equal(canManageCaseAccessRole(role), true);
  }
  for (const role of ["reviewer", "bioinformatician", "read_only", null, undefined]) {
    assert.equal(canManageCaseAccessRole(role), false);
  }
});
