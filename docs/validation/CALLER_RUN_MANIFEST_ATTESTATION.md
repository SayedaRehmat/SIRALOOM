# Laboratory-signed caller run manifests

## Purpose and trust boundary

A VCF header is descriptive input, not authenticated evidence of the executable, release, assay, pipeline run, or laboratory that produced the callset. SIRALOOM therefore accepts a caller-specific semantic exception only when the exact uploaded artifact is bound to a run manifest signed by a key trusted for the authenticated organization.

The signature proves that the configured laboratory signer attested to the manifest. It does **not** independently prove that a binary executed, qualify the assay, or establish clinical validity. The laboratory signing service must obtain caller identity, release, assay, reference build, and run identity from its controlled execution environment before signing.

## Manifest schema version 1

The multipart upload field caller_attestation_json accepts a JSON envelope with exactly these fields:

- manifest: schema_version, manifest_id, organization_id, artifact_sha256, caller_profile_id, caller_release, pipeline_run_id, assay_id, reference_build, issued_at, signer_id
- key_id
- signature

Example manifest values:

- schema_version: 1
- manifest_id: urn:uuid:8d28c3d0-55c2-45d2-85f0-7d7c4a6e8c20
- organization_id: 11111111-2222-4333-8444-555555555555
- artifact_sha256: lowercase SHA-256 digest of the exact uploaded bytes
- caller_profile_id: dragen_snv_germline
- caller_release: 4.2
- pipeline_run_id: run-HG002-2026-001
- assay_id: WGS-GERMLINE-35X
- reference_build: GRCh38
- issued_at: 2026-11-13T08:00:00+00:00
- signer_id: lab-pipeline-attestor
- key_id: caller-run-key-2026-01
- signature: lowercase hexadecimal HMAC-SHA-256 digest

The artifact digest is SHA-256 over the exact uploaded bytes, including compression bytes for .vcf.gz or .vcf.bgz. The organization UUID must match the authenticated tenant. The manifest reference build must match the assembly selected during upload and analysis. Caller family and any release declared in the VCF header must not conflict with the signed manifest.

## Signature and key configuration

The signature is HMAC-SHA-256 over the UTF-8 bytes of the manifest serialized using JSON with sorted keys, compact separators (comma and colon), and ensure_ascii=False. The signature is lowercase hexadecimal.

Generate a key outside the application host and store it in the laboratory secret manager:

    python -c 'import secrets; print(secrets.token_hex(32))'

Configure the verifier in the API and validation-worker environments using the same organization-scoped trust registry:

    CALLER_ATTESTATION_HMAC_KEYS_JSON='{"11111111-2222-4333-8444-555555555555":{"caller-run-key-2026-01":"<64-or-more-hex-character-secret>"}}'

Replace the example organization, key identifier, and secret with actual laboratory values. Never commit signing keys to Git, include them in VCF headers, return them from an API, or send them to the browser. The external pipeline signer and SIRALOOM verifier must use the same key bytes. Keep old verification keys available for the retention period of artifacts that may be reanalysed; rotate by adding a new key identifier before retiring the old one.

Example signing operation for a controlled pipeline service:

    import hashlib
    import hmac
    import json

    canonical = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    signature = hmac.new(
        bytes.fromhex(secret_hex), canonical, hashlib.sha256
    ).hexdigest()
    envelope = {"manifest": manifest, "key_id": key_id, "signature": signature}

The pipeline service must calculate artifact_sha256 from the final immutable VCF bytes after caller execution and before upload. It must not sign a digest from a temporary or pre-transformation file if a different file is uploaded.

## Runtime behavior

1. The API parses the envelope, enforces the schema, checks tenant identity, stores the envelope with immutable artifact metadata, and includes its digest in the upload idempotency fingerprint.
2. The durable validation worker re-verifies the HMAC, tenant, exact artifact digest, caller family/release consistency, and selected reference build.
3. The validation result and audit event retain the verified manifest identity, signer, key ID, run ID, assay ID, release, reference build, and artifact hash.
4. The analysis workflow re-verifies the same signed envelope against the persisted artifact digest and analysis reference build. It does not trust a previous API response or VCF header alone.
5. Missing, malformed, untrusted, mismatched, or tampered manifests cannot authorize caller-specific semantics. Ordinary VCF validation remains fail-closed.
6. A signed DRAGEN 4.2 manifest permits the documented Phred-scaled FORMAT/GP representation to be structurally validated when GP is present. The original values are preserved. This is recorded as a caller/spec semantic deviation with clinical interpretation REVIEW_REQUIRED; it does not authorize genotype inference, clinical classification, or report generation using GP as standard posterior probabilities.

## Current limitations

- HMAC trust is only as strong as the laboratory's key custody and signer controls. Deployments should isolate the signer from ordinary users and application processes.
- This manifest does not constitute caller analytical validation, assay qualification, sample identity confirmation, or clinical accreditation.
- The public HG002 DRAGEN fixture attestation used by the dedicated real-caller smoke test remains a separate exact allowlist test path. It is not a production trust mechanism.
