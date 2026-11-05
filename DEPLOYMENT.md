# Deployment Guide

Production deployment for **patent_drafting_tool** on the Firebase-only runtime
(ADR-005), with documents stored in Firestore (ADR-006). The shape is:

```text
    Firebase Authentication + Cloud Firestore   (managed, external)
              ^                    ^
              |                    |
    one backend container        one static/nginx frontend
    (FastAPI + Admin SDK)        (Vite bundle, nginx SPA fallback)
```

There is no database container, no migration step, and no object-storage
vendor. The backend is stateless: every request verifies a Firebase ID token
and reads/writes Firestore, so redeploys do not move data.

The steps below generalize to any Dockerfile-based PaaS (Koyeb, Render,
Fly.io, Railway, Cloud Run, ECS) and to a plain VM. Swap the dashboard
sections for your platform's equivalent.

> This guide has not been executed against a live production Firebase project
> from this repository's CI. Treat the checklist in §6 as the release gate.
> Generated patent text remains a draft, never legal advice.

## 1. Create the production Firebase project

1. Create a Firebase project at https://console.firebase.google.com/.
2. **Build → Firestore Database** → create the database in the region closest
   to your users. The location cannot be changed later.
3. **Build → Authentication → Sign-in method** → enable **Google**. Add the
   production frontend domain under **Authorized domains**.
4. **Project settings → Your apps → Web app** → register the production web
   app. Copy the `VITE_FIREBASE_*` values for the frontend build.
5. From the repository root, install the Firebase CLI
   (`npm i -g firebase-tools`), run `firebase login` and `firebase use --add`,
   then deploy the checked-in rules with
   `firebase deploy --only firestore:rules`. They deny all direct browser
   access because only the backend Admin SDK reads and writes Firestore. Do
   not enable the Realtime Database, and do not create a Storage bucket —
   documents live in Firestore.
6. **Project settings → Service accounts → Generate new private key** → store
   the JSON in your platform's secret manager. Never commit it.

Use separate Firebase projects for staging and production. Auth users and
Firestore data are per project.

## 2. Configure the backend

The backend reads `backend/.env` locally and environment variables in
production (`pydantic-settings`; see `backend/app/core/config.py`). Set:

| Variable | Production value |
|---|---|
| `ENVIRONMENT` | `production` |
| `FIREBASE_PROJECT_ID` | The production project ID |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | Path to the mounted service-account JSON (for example `/run/secrets/firebase-service-account.json`) |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | _(optional)_ Inline JSON for hosts that cannot mount a file; takes precedence over the path |
| `FIRESTORE_DATABASE_ID` | Empty for the `(default)` database, otherwise the named database |
| `FIREBASE_EMULATOR_HOST` | Empty (never set in production) |
| `BOOTSTRAP_ADMIN_EMAIL` | An address you control, for the first login |
| `CORS_ORIGINS` | The exact frontend origin, e.g. `https://app.example.com` |
| `ALLOWED_HOSTS` | The exact backend host, e.g. `api.example.com` |
| `FORWARDED_ALLOW_IPS` | The proxy that sets `X-Forwarded-For` (`*` on Cloud Run); see the rate-limit note |
| `AUTH_RATE_LIMIT_PER_MINUTE` | `60`, or `0` to disable the limiter |
| `DEPLOYMENT_TARGET` | `self_hosted`, or `vercel` (see the Vercel notes) |
| `MAX_UPLOAD_SIZE_BYTES` | `0` for the profile default (10 MiB self-hosted, 4 MiB Vercel); lower it to restrict uploads further |
| `ALLOWED_UPLOAD_EXTENSIONS` | Keep the default allowlist; remove types you do not need |
| `AI_API_URL` | Unset for the stub; the OpenAI-compatible endpoint (https) to enable drafting |
| `AI_API_KEY` | Only with `AI_API_URL`; store as a secret |
| `AI_MODEL` | Only with `AI_API_URL`; e.g. `qwen/qwen3.8-27b` |

Rules:

- `CORS_ORIGINS` must not contain `*` or a `localhost` origin in production.
- `ALLOWED_HOSTS` must contain the real backend host; the default `*` is a
  development convenience, not a production setting.
- The service-account JSON is mounted read-only or injected by the platform's
  secret manager. Do not bake it into the image.
- Set `FORWARDED_ALLOW_IPS` to the proxy that terminates TLS. Uvicorn trusts
  only `127.0.0.1` by default, so without this every user shares one rate-limit
  bucket; a burst then 429s unrelated accounts.
- Rotate `AI_API_KEY` and the service-account key if either is exposed;
  deleting a later commit is not enough.
- A named database (`FIRESTORE_DATABASE_ID`) is not covered by
  `firebase deploy --only firestore:rules` unless `firebase.json` names it with
  a `"database"` field; otherwise the repo's rules only reach `(default)`.

## 3. Deploy the backend

1. Point the platform at this repository, root directory `backend/`, build
   method Dockerfile (`backend/Dockerfile`).
2. Expose port `8000`.
3. Set the health check to `GET /health`. It returns `200` only when the
   Firestore probe succeeds; `503` means the credentials, project ID, or
   network are wrong.
4. Mount the service-account JSON at the path in
   `FIREBASE_SERVICE_ACCOUNT_PATH`.
5. Deploy. There is no entrypoint and no migration step: Gunicorn starts
   two Uvicorn workers and serves immediately. Boot logs should show the
   workers binding `0.0.0.0:8000`; a `503` health check with a Firebase
   message means configuration, not a stuck migration.

The image installs no office suite: documents are Word-only, PDF uploads are
converted in-process with `pdf2docx`, and generated files are gzip-compressed
into Firestore (ADR-006). The worker count is two because one PDF conversion or
one large document write occupies a worker for its duration, and the
deployment assumes a single container (ADR-003).

## 4. Deploy the frontend

The frontend is a static Vite bundle. `VITE_*` values are fixed at build
time; runtime environment variables cannot change them.

**A. Static hosting** (Cloudflare Pages, Netlify, Vercel, Firebase Hosting,
S3 + CDN):

```powershell
cd frontend
npm ci
$env:VITE_API_URL = "https://api.example.com"
$env:VITE_FIREBASE_API_KEY = "..."
# ... the other VITE_FIREBASE_* values ...
npm run build
# upload frontend/dist/ with a catch-all rewrite to index.html
```

**B. Container** (`frontend/Dockerfile`, nginx with SPA fallback):

```powershell
docker build `
  --build-arg VITE_API_URL=https://api.example.com `
  --build-arg VITE_FIREBASE_API_KEY=... `
  --build-arg VITE_FIREBASE_AUTH_DOMAIN=my-project.firebaseapp.com `
  --build-arg VITE_FIREBASE_PROJECT_ID=my-project `
  --build-arg VITE_FIREBASE_MESSAGING_SENDER_ID=... `
  --build-arg VITE_FIREBASE_APP_ID=... `
  -t patent-frontend ./frontend
docker run -p 8080:80 patent-frontend
```

Either way:

- Add the production frontend domain to Firebase Authentication →
  **Authorized domains**, otherwise Google sign-in fails with
  `auth/unauthorized-domain`.
- Keep the SPA rewrite (`/*` → `index.html`) so deep links such as
  `/agent/patents/<id>/draft` work on refresh.
- Serve over HTTPS. Firebase Auth requires a secure context outside
  `localhost`.

## 5. First login and role bootstrap

1. Open the deployed frontend and sign in with `BOOTSTRAP_ADMIN_EMAIL`.
2. The first `/api/auth/me` call creates `users/{uid}` with
   `role_codes = ["SUPER_ADMIN"]` and `account_status = approved`
   (`app/core/security.py`).
3. Approve subsequent users from `/super-admin` → Pending Approvals.
4. After the first login, remove or change `BOOTSTRAP_ADMIN_EMAIL` according
   to your policy. It is a bootstrap escape hatch, not a permanent role grant.

## 6. Verify the deployment

Run this checklist against the real project before calling the deployment
done:

1. `GET https://<backend-host>/health` → `200` with Firestore connected.
2. Load the frontend, open DevTools → Network, and confirm `/api/auth/me`
   returns `{user, permissions}` with an `Authorization: Bearer …` header.
3. Sign in with a non-bootstrap Google account → lands on
   `/pending-approval`; approve it from the Super Admin dashboard.
4. Innovator path: create team → create patent → add applicant/inventor →
   complete questionnaire → submit.
5. Admin path: assign the patent to an approved `PATENT_AGENT`; try
   auto-assign as well.
6. Agent path: accept → generate a draft section → generate a DOCX → download
   and open it → comment.
7. Upload a DOCX, a PDF, and an image; confirm the PDF arrives as a `.docx`
   download, then delete each file. Blobs are documents in Firestore, so the
   console's `blobs` collection should gain and lose rows.
8. Upload/activate a `.docx` template, then generate a document from it.
9. Confirm a PDF generation request returns `400` with the DOCX guidance.
10. Export a report CSV; toggle a report permission and confirm the export is
    denied for the affected role.
11. Check the backend logs for unhandled `500`s and confirm the production
    error response stays terse.

## 7. Scale and availability

This release assumes **one backend replica** (ADR-003). Document generation
runs inside the request and writes to Firestore; there is no job queue and the
rate limiter keeps per-worker buckets. Before adding replicas:

- move document generation to a worker/job queue with retries and a shared
  status store, and
- put rate limiting at the platform edge (PaaS/WAF/Firebase quotas) or back
  it with a shared store.

Ordinary read traffic can be scaled at the frontend/CDN layer without
touching the backend.

## 8. Backups and retention

- Firestore: enable scheduled backups with point-in-time recovery (PITR) and
  test a restore at least quarterly — an untested backup is a hope, not a
  plan. Firestore has no `pg_dump`. Backups cover the `blobs` collection
  too, so stored documents are protected by the same schedule. Suggested
  posture: daily scheduled backups with a 7-day retention, PITR enabled for
  the gaps between them, and a restore drill recorded with its date.
- Firebase Authentication: user records are managed by Firebase; document
  the export/recovery process you rely on.
- Generated drafts and documents are drafting aids. Retain them according to
  your firm's records policy, not indefinitely by default.

## 9. Rollback

- Backend: redeploy the previous image tag. There is no schema migration to
  reverse; Firestore documents are forward/backward compatible as long as
  field names do not change.
- Frontend: redeploy the previous static build. `VITE_*` values are part of
  that build, so a rollback also restores the previous Firebase project
  configuration.
- Data: Firestore writes are not transactional across collections. If a
  release changes document shapes, ship a read-compatible projection first
  (the pattern used by `app/services/projections.py`) and remove the old
  shape in a later release.

## Vercel deployment notes

Vercel is a good fit for the static frontend. It can also run the Python
backend, but the platform's request/response size limits still change the
shape. Two supported deployments:

| Shape | Frontend | Backend |
|---|---|---|
| Split (recommended) | Vercel static | Container per §3 (Cloud Run, Fly.io, Render, …) |
| Single vendor | Vercel static | Vercel Python function, `DEPLOYMENT_TARGET=vercel` |

### Static frontend on Vercel

The repository ships two configs because Vercel only reads `vercel.json`
from the project's **Root Directory**:

| Root Directory | Config | Behaviour |
|---|---|---|
| Repository root (default) | `vercel.json` | Runs `npm --prefix frontend ci` / `npm --prefix frontend run build`, publishes `frontend/dist`. |
| `frontend` | `frontend/vercel.json` | Vercel's Vite preset installs and builds in place, publishing `dist`. |

Pick one and leave the other untouched; do not set Root Directory to
`frontend` while also expecting the root config to apply. Both files contain
the same SPA rewrite and security headers; `backend/tests/test_smoke.py`
checks that the two configs stay in step and that the Firebase Auth origins
remain allowed alongside the nginx policy.

Set these **build-time** variables in the Vercel project (Project → Settings →
Environment Variables) before the first deployment:

- `VITE_API_URL` — the backend origin, e.g. `https://api.example.com`.
- `VITE_FIREBASE_API_KEY`
- `VITE_FIREBASE_AUTH_DOMAIN` — normally `<project>.firebaseapp.com`.
- `VITE_FIREBASE_PROJECT_ID`
- `VITE_FIREBASE_MESSAGING_SENDER_ID`
- `VITE_FIREBASE_APP_ID`

Vite inlines `VITE_*` values at build time, so changing one requires a new
deployment, not a restart. On the backend, add the Vercel production domain to
`CORS_ORIGINS`; add preview domains too if you use preview deployments.

The static CSP allows `https://apis.google.com` (Firebase Auth's loader) and
the `https://*.firebaseapp.com` / `https://accounts.google.com` frames the
Google popup needs. If `VITE_FIREBASE_AUTH_DOMAIN` is a custom domain, add it
to `frame-src` in `frontend/nginx.conf`, `vercel.json`, and
`frontend/vercel.json`.

Do not add an `api/index.py` backend entry point to this Vercel project while
using the split shape: the static frontend and the Python backend deploy
separately, and the backend needs a host that can mount (or inject)
credentials and run a PDF conversion without hitting the function timeout.

Running the backend as a Vercel Python function:

1. Set `DEPLOYMENT_TARGET=vercel`, so the effective upload cap is 4 MiB and
   the whole-request cap is 4.5 MB. Explicit `MAX_UPLOAD_SIZE_BYTES` values
   above that are clamped, never honoured.
2. PDF uploads are converted to DOCX in-process with `pdf2docx`, so no
   LibreOffice is needed on any target. The conversion and the gzip write
   both count against the function duration; a large scan may time out, in
   which case the caller gets a 400/504 rather than a stored file.
3. Inject `FIREBASE_SERVICE_ACCOUNT_JSON` from Vercel's secret store. The
   function filesystem is read-only except `/tmp`, so the path-based
   credential file from §2 is not available. `pdf2docx` writes its working
   files through `tempfile`, which uses `/tmp` on this runtime.
4. Keep `CORS_ORIGINS` and `ALLOWED_HOSTS` set to the deployed domains; do not
   widen them to `*` to work around a CORS error.
5. Document generation is synchronous. It must finish inside the function
   duration limit (300 s Hobby / 800 s Pro); the container shape has no such
   ceiling.

What still does not fit: files that compress to more than ~900 KB. Firestore
caps a document at 1 MiB, so this is a storage limit, not a Vercel one, and
raising `MAX_UPLOAD_SIZE_BYTES` does not move it. Downloads are streamed from
memory, and the API reports the over-cap case as a 413 that names the limit.

What changed from the old design: there is no direct-to-Cloud-Storage upload
flow, because there is no bucket. Large-file support would need chunking a
blob across several Firestore documents (rejected in ADR-006 until a real
document approaches the cap).

## What this guide deliberately does not cover

- **No automated deploy job.** CI builds and tests; wiring a platform deploy
  needs an account-specific token and is left to the maintainer.
- **No CDN configuration.** nginx/static-host caching is the extent of it;
  add a CDN when traffic justifies it.
- **No secrets-manager integration.** Use your platform's secret store; the
  repository only documents which values are secret.
- **No multi-region Firestore.** Choose the region in §1; changing it later
  is a migration project.
