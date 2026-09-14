# Security notes

Tenant identity is resolved on the FastAPI server from a verified Firebase token and an active server-side membership. Case and artifact routes enforce organization ownership and return 404 for cross-tenant case access.

Firestore and Storage rules default deny all unmatched paths. Artifact/report paths are organization scoped. Rules are defence in depth; the FastAPI service must also authorize every database object and storage operation.

`GENEBE_API_KEY`, Firebase Admin credentials, database passwords, and other server secrets belong only in the deployment secret manager or private runtime environment. They must never be in `NEXT_PUBLIC_*`, source control, browser requests, logs, or generated reports.
