# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once releases begin.

## [Unreleased]

### Added

- Statutory form set (ADR-008): FORM1/2/3/5 + Drawings bundled under `backend/app/templates/forms/`, deterministic sandboxed renderer with fail-closed variables, per-form documents/jobs/versions, finalize gate, and a Forms panel with per-form status, missing fields, version history, and filing-style downloads.
- Questionnaire registry (`questionnaire_schema.py`): 28 fields drive validation, projections, snapshots, and the UI; unknown keys return 422.
- AI field refinement: three grouped JSON calls with validation + repair + raw fallback, versioned editable review, optional vision input for embodiments, and a vision classification pass over figures.
- YOLO figure detection (Apache-2.0 DocLayNet weights, pluggable via `YOLO_MODEL_PATH`), deterministic screening, direct image uploads as figures, figure review UI with captions and use-anyway.
- Figure endpoints (text/figures/image/PATCH) and form endpoints (catalog/refine/form-fields/generate/status/finalize/classify) documented in `docs/API_OVERVIEW.md`; new env vars in `backend/.env.example`.

### Fixed

- FORM2 rendering defects: auto-numbering overlap fixed by widening the bracket-number indent, literal `[000NN]` prefixes removed (they doubled with auto-numbering), stray leading period and double-space typo fixed, dangling abstract FIG. 3 line removed, duplicated method dependent claim corrected to "The method of claim 3", redundant summary sentence condensed. Sample-specific boilerplate (wireless handset definitions, AI/ML primers, reference-numeral system description) removed from the template.
- AI system prompt rewritten around Indian complete-specification conventions (title ≤15 words, field statement, objective background, enablement-standard embodiments, exact reference numerals, single term per element); advantage fields validated as lowercase base verbs.

### Deprecated

- Legacy section-wise AI drafts (`ABSTRACT`…`CLAIMS`) and the single-document generation path remain for existing records but are superseded by refinement + forms. They keep their per-section draft-only warnings; generated forms carry one end-of-document disclosure instead.

- Full open-source documentation set: detailed `README.md`, `CONTRIBUTING.md`, Contributor Covenant `CODE_OF_CONDUCT.md`, `SECURITY.md`, `ACCESSIBILITY.md` (WCAG 2.2 AA target), `SUPPORT.md`, and `docs/` guides (`GETTING_STARTED`, `ARCHITECTURE`, `API_OVERVIEW`, `DEVELOPMENT`, `DOCKER`, `FAQ`, `TROUBLESHOOTING`).
- GitHub community health files: PR template, bug/feature/docs issue forms, `config.yml`, `CODEOWNERS`, `dependabot.yml`, Discussions-ready links.
- CI/CD: `ci.yml` (offline backend pytest, frontend build on `ubuntu`/`windows`/`macos`, docs-health), `docker.yml` (backend + frontend image builds + backend `/health` smoke test), `codeql.yml` (CodeQL for Python + JavaScript).
- Apache-2.0 `LICENSE` with `SPDX-License-Identifier` notice.
- Root `.editorconfig`, `.nvmrc` (Node 20), `backend/.python-version` (3.13), hardened root `.gitignore`.
- Architecture Decision Records in `docs/decisions/`: ADR-001 Firebase runtime (superseded), ADR-002 `role_codes` array, ADR-003 single instance, ADR-004 stub-first AI, ADR-005 Firestore-only runtime, ADR-006 Word-only documents in Firestore.
- `AGENTS.md` (agent instructions), `CITATION.cff`, `docs/FAQ.md`, `docs/TROUBLESHOOTING.md`; `ref-repos/` convention for ignored reference clones.
- Shared centred `LoadingState` / `EmptyState` frontend components replacing scattered left-aligned loading/empty paragraphs; wrapping dashboard header for small screens.
- Browser-side Firebase Authentication in the React client (`src/lib/firebase.ts`, `AuthContext`), with Google popup and redirect fallback, a configuration-error banner, and a 30-minute idle sign-out.
- Offline backend test suite (`backend/tests/`) covering boot, the mounted frontend contract, RBAC, stub drafting, and DOCX rendering — no Firebase credentials required.
- Runtime capability probe (`GET /api/config/capabilities`) and configurable deployment limits: `DEPLOYMENT_TARGET` and `MAX_UPLOAD_SIZE_BYTES`. The frontend pre-checks upload sizes before sending.
- Inline `FIREBASE_SERVICE_ACCOUNT_JSON` credentials for hosts without a mountable secret file, such as Vercel.
- Checked-in `firebase.json` and `firestore.rules`: the browser uses Firebase Auth only, and direct Firestore access is denied because the backend Admin SDK is the only data path.
- Upload allowlist (`ALLOWED_UPLOAD_EXTENSIONS`) plus magic-byte content sniffing; Office containers are checked for their required part and bounded against ZIP bombs (`backend/app/services/uploads.py`).
- Content-Security-Policy on API responses and the nginx frontend, and HSTS in production; the backend exempts Swagger/ReDoc paths so the docs stay usable.
- Profile-field validation (`/api/auth/sync`): per-field length bounds, string-only values, control-character rejection, and an http(s)-only `profile_picture`.
- Abandoned `Processing` document jobs are reaped into `Failed` after 15 minutes so the UI can retry them.
- Root `vercel.json` and `frontend/vercel.json` for a static frontend deployment: an SPA fallback rewrite, immutable caching for hashed assets, and the same security headers as nginx (including the Firebase Auth CSP allowances).
- Audit entries (`activity` documents) for account approval/rejection, role assignment/revocation, and RBAC/report-grant changes, so Super Admin actions are attributable after the fact.
- Length and type bounds for patent titles, applicant/inventor fields, questionnaire text, and AI output (60,000 characters); non-string and control-character payloads are rejected before they reach Firestore.
- Configurable auth rate limiting (`AUTH_RATE_LIMIT_PER_MINUTE`) keyed by client, with idle-bucket pruning; `/api/auth/me` and `/api/auth/logout` are exempt so a shared proxy address cannot sign users out.
- `FIRESTORE_DATABASE_ID` for projects that use a named Firestore database instead of `(default)`.
- Frontend route-level code splitting with a Suspense fallback, and a render error boundary that offers a way back to sign-in instead of a blank page.
- Versioned, shape-checked profile cache in `localStorage`, so a stale cache entry cannot crash the app after a schema change.
- Firestore blob storage (`app/services/blobs.py`): every upload, template, and generated document is gzip-compressed into a `blobs` document with a SHA-256 checksum, and the owning row keeps only the blob id. The 900 KB compressed cap is reported as a 413 instead of a provider error (ADR-006).
- Uploaded PDFs are converted to DOCX in-process with `pdf2docx` before storage, so no PDF is ever stored and no office suite is installed. Responses expose `source_file_name` and `converted_from_pdf` alongside the converted `original_file_name`.
- Offline tests for blob compression, the size cap, corruption detection, and PDF→Word conversion.

### Changed

- **Firebase is the only backend.** Postgres, SQLAlchemy, Alembic, asyncpg/psycopg, the legacy routers/models/schemas/services, `docker-entrypoint.sh`, the SQL test suite, and the advisory CI job are all removed (ADR-005).
- All application data now lives in Cloud Firestore, including uploaded files, templates, and generated documents. Database, storage-provider, and Storage bucket environment variables are gone.
- The REST API keeps the existing snake_case contract (`invention_title`, `application_status`, `roles`, Title-Case statuses) through `app/services/projections.py`; Firestore stores lowercase `account_status` / `role_codes`.
- Entity identifiers are Firestore strings end to end; `Number(id)` casts were removed from the frontend. Only RBAC role/permission catalog IDs remain numeric.
- `frontend/src/lib/api.ts` now registers an async token provider (`setTokenProvider`) and asks Firebase for a fresh ID token per request, replacing the cached-token `setAuthToken` approach.
- DOCX generation uses `docxtpl` when an active template exists and a built-in `python-docx` layout otherwise; documents are Word-only, and a PDF output request now returns 400 with export guidance.
- `docker-compose.yml` runs the backend + frontend images only; `backend/Dockerfile` drops the entrypoint, installs no office suite, and runs two Gunicorn/Uvicorn workers; `frontend/Dockerfile` accepts the five `VITE_FIREBASE_*` build args.
- CI runs the offline Firebase suite on Python 3.11/3.13 across three operating systems, and `docs-health` rejects stale SQL references in shipped code.
- `README.md`, `DEPLOYMENT.md`, `backend/README.md`, and every `docs/` guide rewritten for the Firebase-only runtime and offline workflow.
- AI drafting is configured through `AI_API_URL` / `AI_API_KEY` / `AI_MODEL` for any OpenAI-compatible endpoint (ADR-004), replacing `AI_PROVIDER` / `GEMINI_*`; partial configuration is rejected instead of silently falling back to the stub, and non-localhost endpoints must use https.
- `DEPLOYMENT.md` rewritten for a Firebase project + one backend container + static/nginx frontend, with no managed Postgres or object-store vendor.
- Document downloads stream from Firestore memory instead of an object-storage handle; the contract keys (`stored_path`, `storage_path`, `file_path`) keep their names but now carry blob ids.

### Removed

- Server-minted JWTs, the refresh endpoint, the backend Google OAuth redirect, dev login, and the legacy auth modules.
- The SQL-era in-memory rate limiter, the SQL startup checks, and the headless-LibreOffice PDF pipeline (see ADR-003 and ADR-006).
- `DATABASE_URL`, `JWT_SECRET`, `SESSION_SECRET`, `GOOGLE_CLIENT_ID`/`SECRET`, `STORAGE_PROVIDER`, `FIREBASE_STORAGE_BUCKET`, `STORAGE_EMULATOR_HOST`, `VITE_FIREBASE_STORAGE_BUCKET`, `PDF_CONVERSION_ENABLED`, and the `R2_*` variables from documentation and configuration.
- `storage.rules` and the separate `app/services/storage.py` layer; the `blobs` collection replaced both.

### Fixed

- Docker workflow used the non-existent `docker/build-action` (failed at "Set up job") — corrected to `docker/build-push-action`; action existence is verified before merging workflow changes.
- Frontend no longer crashes at import time when Firebase Web SDK values are missing; it renders a configuration error on the login screen instead.
- Document/template version numbers are claimed through a Firestore transaction, so two concurrent generations can no longer compute the same `vN` and overwrite each other.
- Unexpected generation failures store a stable message on the job instead of echoing exception text; curated `DocumentGenerationError` messages still reach the UI.
- `PendingApprovalPage` stops polling once the session is no longer pending, `ProtectedRoute` uses the shared `LoadingState`, and the generate button stays disabled while a generation is in flight.
- Sign-in failures show the mapped Firebase hint plus the raw error code when it is unrecognised, and an API session that cannot be described renders an alert instead of silently returning to the login screen.
- **User-friendly error handling**: Frontend `getFriendlyError()` maps HTTP status codes to user-friendly messages (401→session expired, 403→no permission, 429→too many requests, etc.) instead of surfacing raw technical details. Frontend `AuthContext` now resets `status` to `"unauthenticated"` when `loadMe()` fails, eliminating the blank-page-on-sign-in bug. All `err instanceof Error ? err.message : "..."` patterns replaced with `getFriendlyError()` calls across 16 frontend files.

- **Backend test fixes**: `ingestion.py` error message updated to include "Java" for `test_missing_java_is_reported_as_unavailable`; `documents.py` error message updated to match `could not be read` regex for `test_pdf_to_docx_rejects_bytes_that_are_not_a_pdf`.

- **Session persistence fix**: `AuthContext` `loadMe()` now always resets `status="unauthenticated"` on failure (previously only when no cached user existed), eliminating the blank-page-after-sign-in issue.

- **Login page loading state**: `LoginPage.tsx` now shows `<LoadingState label="Signing in…" />` during session restore instead of a blank page.

- **The nginx `/assets/` location repeats the security headers; nginx drops inherited `add_header` directives in a location that declares its own.
- The production CSP blocked Google sign-in because Firebase Auth loads `https://apis.google.com/js/api.js` and renders its auth iframe on `*.firebaseapp.com`; both nginx locations and both Vercel configs now allow those origins.
- The users report is hidden from the catalog for non-admins, and `run`/`export` reject it before querying Firestore, so a report grant cannot widen account data to Innovators or Patent Agents.
- Deleting a calendar event now requires `CALENDAR_MANAGE`, matching event creation.
- `reject_user` refuses to reject the caller's own account or another Super Admin, preventing an accidental lockout.
- Patent title, applicant/inventor, and questionnaire fields are length-bounded; Gemini output is capped before it is written to a Firestore document.
- Production startup warns when `ALLOWED_HOSTS` is still `*`.

### Known gaps (tracked, not yet fixed)

- Frontend has no unit-test runner yet; verification is `tsc` + `vite build` + manual role walkthroughs.
- The offline suite cannot prove live Firebase IAM, deployed Firestore rules, or real PDF rendering fidelity; a manual walkthrough against a real Firebase project remains the release check (`backend/README.md` §7).
- Application statuses beyond `Draft Generated` (filing, examination, grant) are accepted and displayed but have no transition endpoint yet.

## [0.1.0] - 2026-10-15 (pre-revolution baseline)

Baseline inherited from prior development (see git history):

- `58362d3 Implement patent workflow, reports, testing, and deployment`
- `8232dfb Integrate Firebase backend`

Included: role-based dashboards (Innovator / Agent / Admin / Super Admin), patent assignment state machine, questionnaire + versions, stub/Gemini draft generation, DOCX generation, file uploads, comments, calendar, notifications, templates, reports, Docker images, and Compose for local full-stack testing.
