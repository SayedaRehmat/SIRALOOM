import assert from "node:assert/strict";
import test from "node:test";
import { attemptSignOut } from "./signout.mjs";

test("reports a successful identity-provider signout", async () => {
  assert.equal(await attemptSignOut(async () => {}), true);
});

test("turns identity-provider signout rejection into a handled failure", async () => {
  assert.equal(await attemptSignOut(async () => { throw new Error("network unavailable"); }), false);
});
