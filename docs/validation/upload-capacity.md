# Upload capacity validation for a laboratory deployment

## Purpose and limits

Use this runbook against a **staging deployment** or an explicitly disposable lab workspace. The artifact endpoint is:

`POST /api/v1/cases/{case_id}/artifacts`

A successful HTTP 201 means an artifact was accepted; it does not mean the uploaded VCF is scientifically suitable for analysis. The endpoint stores one new artifact for each successful request. The smoke script does not delete artifacts.

The application enforces its configured upload cap while copying the already-parsed multipart upload into a staging file. That application check is **not** an ingress-level request limit and is not a concurrent disk reservation. Multipart parsing may already have consumed temporary disk before the route begins. The endpoint can also have both a multipart temporary file and an application staging copy at the same time.

## Before running

1. Use a non-production deployment and a disposable case with a specimen belonging to that case.
2. Use a small, valid VCF fixture with the correct build and no patient-identifying data.
3. Set the ingress/proxy body limit to the application upload cap plus reasonable multipart overhead. Confirm this limit is applied before requests reach the ASGI application.
4. Place proxy body-temp files, ASGI upload spooling, application staging files, and persistent artifact storage on monitored filesystems/volumes. Ensure temporary paths have sufficient free space and are not unintentionally shared with the OS root volume.
5. Configure alerts for free disk space/inodes, container restarts/OOM, API 4xx/5xx, request duration, worker queue age, and storage errors.
6. Confirm backup, retention, and cleanup policies for the disposable test case. Do not place real clinical data in a benchmark fixture.

## Run the concurrent upload smoke test

Install the repository dependencies, then set the token in the environment (do not put it in shell history or command-line arguments):

```bash
export SIRALOOM_API_TOKEN='…'
python scripts/validation/upload_capacity_smoke.py \
  --base-url 'https://staging.example.org/api/v1' \
  --case-id '<DISPOSABLE_CASE_UUID>' \
  --specimen-id '<SPECIMEN_UUID>' \
  --genome-build GRCh38 \
  --vcf '/path/to/non-sensitive-valid-fixture.vcf' \
  --requests 10 \
  --concurrency 2 \
  --confirm-disposable-case
```

Start with concurrency 1, then 2, then 4, increasing only while monitoring all relevant disks and service metrics. Do not jump straight to production-scale uploads. Repeat with representative compressed VCF sizes and at least one file near the configured maximum, using dedicated test cases or an approved artifact cleanup procedure.

The script exits non-zero if any request does not return HTTP 201. Review each response's `validation_status`; HTTP success alone is not sufficient. Keep the emitted JSON report with the deployment version and metric snapshots.

## Required ingress and disk tests

The smoke script measures client-observed latency and throughput; it does not establish ingress enforcement or measure peak temporary disk by itself. Separately verify:

- An upload above the proxy limit is rejected by the proxy with HTTP 413 and never reaches the application (confirm in proxy logs).
- An upload within the proxy limit but above the application cap is rejected with HTTP 413 by the application.
- Multiple simultaneous uploads do not exhaust temporary or persistent storage.
- Interrupted client uploads, API restarts, and worker restarts leave no orphaned temporary files or partially committed artifact records.
- Storage failures do not create an artifact row claiming success when the payload is missing or checksum verification fails.
- The service recovers after temporary storage pressure is relieved; retry behavior does not create duplicate analysis dispatches.

## Capacity calculation and acceptance record

Before testing, record the configured maximum file size, ingress body limit, request concurrency, proxy temp filesystem, API temp filesystem, staging filesystem, persistent storage backend, and worker count.

As an initial **capacity-planning estimate, not a guarantee**, budget temporary storage for several copies of the largest concurrent upload. The proxy may buffer the multipart body, the ASGI layer may spool it, and the application stages a copy. A conservative starting estimate is at least `3 × concurrency × maximum upload size` for temporary upload paths, plus headroom for unrelated workload and filesystem overhead. Measure actual peak use under the deployed proxy/ASGI configuration before setting the production limit.

Record these results before approving the deployment:

- All tested uploads either succeed or fail with the documented status; no unexplained 5xx responses.
- Oversized requests are rejected at the intended layer.
- Peak temp/persistent disk and inode usage remain within approved limits with alert headroom.
- No orphaned temporary files, inconsistent artifact records, or duplicate dispatches after interruption/recovery.
- Latency, throughput, API memory, CPU, and queue backlog meet lab-approved thresholds.

The lab owner must define the numeric thresholds and sign off the record. Do not infer production capacity from a single smoke run.
