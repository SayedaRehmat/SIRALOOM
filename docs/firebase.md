# Firebase setup

1. Create a Firebase project and enable Email/Password sign-in and email verification.
2. Create a web app and place its public configuration in the `NEXT_PUBLIC_FIREBASE_*` variables in the frontend environment. These values are identifiers, not secrets.
3. Deploy `firestore.rules` and `storage.rules` using the Firebase CLI. Rules default to deny.
4. Give the FastAPI deployment a Firebase service identity using Application Default Credentials, or set a server-only `FIREBASE_CREDENTIALS_PATH`. Never copy service-account JSON into frontend files, Git, or browser variables.
5. A verified user may use `/onboarding` to create their first organization. The backend—not the form—assigns the first `organization_admin` membership. Subsequent invitations/membership management must use a server-authorized administration flow.
6. In production set `FIREBASE_AUTH_REQUIRED=true`; FastAPI then rejects unauthenticated requests.

The initial roles are `platform_admin`, `organization_admin`, `lab_director`, `clinical_geneticist`, `reviewer`, `bioinformatician`, `lab_scientist`, and `read_only`.


## Phase 1 artifact access

SIRALOOM keeps genomic artifacts private and routes artifact operations through the authenticated FastAPI API. The Firebase Storage rules intentionally deny direct browser object access in Phase 1; the server derives organization/case ownership from PostgreSQL membership and uploads to tenant-derived object paths. This avoids maintaining a second, competing authorization database in Firestore.

Direct browser upload can be introduced later only with an explicit, tested authorization design that preserves the same tenant boundary.
