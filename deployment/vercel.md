# SIRALOOM frontend — Vercel configuration

- Vercel **Root Directory**: `frontend`
- Framework preset: Next.js
- Node.js: `22.x`
- Install command: `npm ci`
- Build command: `npm run build`
- Output directory: leave default
- Do not add a second backend to Vercel.

Required production environment variables:

- `NEXT_PUBLIC_SIRALOOM_API_BASE=https://<cloud-run-api>/api/v1`
- `NEXT_PUBLIC_FIREBASE_API_KEY=<Firebase Web API key>`
- `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=<Firebase Auth domain>`
- `NEXT_PUBLIC_FIREBASE_PROJECT_ID=<Firebase project id>`
- `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=<Firebase Storage bucket>`
- `NEXT_PUBLIC_FIREBASE_APP_ID=<Firebase Web app id>`

The Firebase web configuration values above are client configuration, not server secrets. GeneBe keys, database passwords, Redis credentials, and service-account credentials must never be placed in these variables.
