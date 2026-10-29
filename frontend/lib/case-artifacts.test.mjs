import assert from "node:assert/strict";
import test from "node:test";
import { selectCaseInputArtifacts, selectPrimaryAfterUpload, uploadValidationMessage } from "./case-artifacts.mjs";

test("keeps the displayed specimen and index paired to the selected primary VCF", () => {
  const specimens = [
    { specimen_id: "specimen-a" },
    { specimen_id: "specimen-b" },
  ];
  const artifacts = [
    { artifact_id: "index-wrong", artifact_type: "VCF_INDEX_TBI", paired_artifact_id: "vcf-old" },
    { artifact_id: "vcf-new", artifact_type: "VCF", validation_status: "VALID", specimen_id: "specimen-b" },
    { artifact_id: "index-right", artifact_type: "VCF_INDEX_CSI", paired_artifact_id: "vcf-new" },
    { artifact_id: "vcf-invalid", artifact_type: "VCF", validation_status: "INVALID", specimen_id: "specimen-a" },
  ];

  const selected = selectCaseInputArtifacts(artifacts, specimens);
  assert.equal(selected.primary?.artifact_id, "vcf-new");
  assert.equal(selected.index?.artifact_id, "index-right");
  assert.equal(selected.specimenId, "specimen-b");
});

test("does not display an orphaned index when no validated primary VCF exists", () => {
  const selected = selectCaseInputArtifacts(
    [{ artifact_id: "index", artifact_type: "VCF_INDEX_TBI", paired_artifact_id: "vcf" }],
    [{ specimen_id: "specimen-a" }],
  );
  assert.equal(selected.primary, null);
  assert.equal(selected.index, null);
  assert.equal(selected.specimenId, "specimen-a");
});

test("a rejected replacement does not discard an existing valid primary VCF", () => {
  const valid = { artifact_id: "valid", validation_status: "VALID" };
  const rejected = { artifact_id: "rejected", validation_status: "INVALID" };
  assert.equal(selectPrimaryAfterUpload(valid, rejected), valid);
  assert.equal(selectPrimaryAfterUpload(null, rejected), rejected);
  assert.equal(selectPrimaryAfterUpload(valid, { artifact_id: "new", validation_status: "VALID" }).artifact_id, "new");
});

test("case intake upload message preserves server validation warnings", () => {
  const message = uploadValidationMessage({
    status: "VALID",
    label: "Upload variant dataset",
    successText: "validated successfully.",
    warningLabel: "Warnings",
    failureText: "was stored but failed validation.",
    warnings: ["FORMAT/PL cardinality could not be checked without GT.", "  "],
  });

  assert.equal(
    message,
    "Upload variant dataset validated successfully. Warnings: FORMAT/PL cardinality could not be checked without GT.",
  );
});

test("case intake upload message reports errors for rejected input and omits empty lists", () => {
  assert.equal(
    uploadValidationMessage({
      status: "INVALID", label: "Upload", successText: "validated successfully.",
      warningLabel: "Warnings", failureText: "was stored but failed validation.",
      errors: ["Unsupported VCF version."],
    }),
    "Upload was stored but failed validation. Unsupported VCF version.",
  );
  assert.equal(
    uploadValidationMessage({
      status: "VALID", label: "Upload", successText: "validated successfully.",
      warningLabel: "Warnings", failureText: "failed validation.",
    }),
    "Upload validated successfully.",
  );
});

test("case intake upload message tolerates malformed warning and error fields", () => {
  assert.equal(
    uploadValidationMessage({
      status: "VALID", label: "Upload", successText: "validated successfully.",
      warningLabel: "Warnings", failureText: "failed validation.", warnings: "unexpected",
    }),
    "Upload validated successfully.",
  );
  assert.equal(
    uploadValidationMessage({
      status: "INVALID", label: "Upload", successText: "validated successfully.",
      warningLabel: "Warnings", failureText: "failed validation.", errors: { detail: "bad" },
    }),
    "Upload failed validation.",
  );
});
