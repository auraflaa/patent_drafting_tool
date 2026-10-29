<div align="center">
  <h1>patent_drafting_tool</h1>
  <p><em>An open-source collaborative platform for drafting, reviewing, and managing patent applications — from invention disclosure to filing-ready documents.</em></p>
  <p>
    <a href="https://github.com/auraflaa/patent_drafting_tool/actions/workflows/ci.yml"><img src="https://github.com/auraflaa/patent_drafting_tool/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
    <a href="https://github.com/auraflaa/patent_drafting_tool/actions/workflows/docker.yml"><img src="https://github.com/auraflaa/patent_drafting_tool/actions/workflows/docker.yml/badge.svg" alt="Docker status"></a>
    <a href="./LICENSE"><img src="https://img.shields.io/badge/License-Apache--2.0-blue.svg" alt="License: Apache-2.0"></a>
    <a href="./CODE_OF_CONDUCT.md"><img src="https://img.shields.io/badge/Code%20of%20Conduct-Contributor%20Covenant-4baaaa.svg" alt="Code of Conduct"></a>
    <a href="./CONTRIBUTING.md"><img src="https://img.shields.io/badge/Contributing-Guide-green.svg" alt="Contributing guide"></a>
    <a href="./SECURITY.md"><img src="https://img.shields.io/badge/Security-Policy-red.svg" alt="Security policy"></a>
    <a href="./ACCESSIBILITY.md"><img src="https://img.shields.io/badge/Accessibility-WCAG%202.2%20AA-purple.svg" alt="Accessibility: WCAG 2.2 AA"></a>
    <a href="./CONTRIBUTING.md"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs welcome"></a>
  </p>
</div>

---

## Table of contents

- [1. What this is](#1-what-this-is)
- [2. Features](#2-features)
- [3. Who it is for (roles)](#3-who-it-is-for-roles)
- [4. Patent lifecycle](#4-patent-lifecycle)
- [5. Tech stack](#5-tech-stack)
- [6. Repository layout](#6-repository-layout)
- [7. Quickstart](#7-quickstart)
  - [7.1 Prerequisites](#71-prerequisites)
  - [7.2 Option A — Docker Compose](#72-option-a--docker-compose)
  - [7.3 Option B — Run backend + frontend locally](#73-option-b--run-backend--frontend-locally)
  - [7.4 First admin login](#74-first-admin-login)
- [8. Configuration (environment variables)](#8-configuration-environment-variables)
  - [8.1 Backend (`backend/.env`)](#81-backend-backenvenv)
  - [8.2 Frontend (`frontend/.env`)](#82-frontend-frontendenv)
- [9. Usage walkthrough](#9-usage-walkthrough)
- [10. API overview](#10-api-overview)
- [11. Development](#11-development)
- [12. Testing](#12-testing)
- [13. Docker](#13-docker)
- [14. Deployment](#14-deployment)
- [15. Documentation index](#15-documentation-index)
- [16. Contributing](#16-contributing)
- [17. Code of Conduct](#17-code-of-conduct)
- [18. Security](#18-security)
- [19. Accessibility](#19-accessibility)
- [20. Support](#20-support)
- [21. Changelog](#21-changelog)
- [22. License](#22-license)
- [23. Acknowledgements](#23-acknowledgements)

---

## 1. What this is

**patent_drafting_tool** is a full-stack web application that helps teams prepare patent applications:

- **Innovators** disclose inventions through structured questionnaires, track status, and collaborate with agents.
- **Patent agents** review disclosures, accept assignments, generate draft sections (with optional AI assistance), and produce Word documents.
- **Admins and Super Admins** manage users, approve accounts, assign agents, manage templates, and view reports.

The stack is **Firebase-only**:

- **Identity:** Firebase Authentication (Google sign-in, browser-side Firebase JS SDK; the API verifies ID tokens).
- **Data:** Cloud Firestore is the only system of record. There is no Postgres, no ORM, no migrations, and no `DATABASE_URL`.
- **Files:** Firestore also stores uploads, templates, and generated documents, gzip-compressed in a `blobs` collection. There is no bucket or object storage.
- **Backend:** FastAPI with Firebase Admin SDK, mounting exactly two routers (`app/api/auth.py`, `app/api/resources.py`).
- **Frontend:** React 18 + Vite 6 + TypeScript `strict`, talking to the backend through one thin API wrapper.

The REST API deliberately keeps the legacy snake_case contract (`invention_title`, `application_status`, `roles`, Title-Case statuses) so the existing UI did not need a parallel rewrite. Firestore stores lowercase internal state (`account_status`, `role_codes`); serialisation lives in `backend/app/services/projections.py`. The reasoning is recorded in [ADR-005](./docs/decisions/ADR-005-firestore-only-runtime.md).

> Generated patent text is a **draft only** and is **not legal advice**. Final review by a qualified patent professional is required before filing.

---

## 2. Features

| Area | What you get |
|---|---|
| Invention intake | Teams, patent records, applicant/inventor parties, structured questionnaire with version snapshots |
| Agent workflow | Available-agent listing with workload counts, assign / auto-assign / reassign, accept / reject with reasons |
| Drafting | Section-wise draft generation (`ABSTRACT`, `BACKGROUND`, `SUMMARY`, `DESCRIPTION`, `CLAIMS`), version history; deterministic stub by default, optional OpenAI-compatible provider |
| Documents | DOCX generation from questionnaire answers, optional `.docx` templates via `docxtpl`, version list, retry, streamed downloads |
| Files | Patent-scoped uploads stored compressed in Firestore, PDF→DOCX conversion on upload, size/extension validation, streamed downloads, uploader/admin delete |
| Collaboration | Comments, calendar events, notifications (unread count, mark read) |
| Templates | Admin-managed `.docx` templates per document type, activate/deactivate, unknown-placeholder warnings |
| Reports & dashboard | Status counts, action-required queue, patent/document/user/calendar reports, CSV export, per-report permission matrix |
| Auth & RBAC | Firebase ID-token auth, `role_codes` (`INNOVATOR`, `PATENT_AGENT`, `ADMIN`, `SUPER_ADMIN`), pending → approved onboarding, bootstrap super admin, 27-permission matrix |
| Frontend | Role-based dashboards, patent workflow tabs, draft workspace, calendar (FullCalendar) |
| Ops | `/health` Firestore probe, CORS + TrustedHost, Docker images for backend + frontend, Compose for local full-stack |

---

## 3. Who it is for (roles)

| Role | Home route | Can do |
|---|---|---|
| `INNOVATOR` | `/innovator` | Create teams + patents, fill questionnaire, upload files, comment, submit for review, view own calendar/reports |
| `PATENT_AGENT` | `/agent` | View assignment queue, accept/decline, generate drafts, generate documents, collaborate |
| `ADMIN` | `/admin` | Approve users, assign/reassign agents, manage templates, view all patents, reports |
| `SUPER_ADMIN` | `/super-admin` | Everything admins can do, plus RBAC user/role management and the report-permission matrix |

New users land in `Pending` until an `ADMIN`/`SUPER_ADMIN` approves them. The single exception is the `BOOTSTRAP_ADMIN_EMAIL` address, which becomes `SUPER_ADMIN` + approved on first sign-in. See [`docs/GETTING_STARTED.md`](./docs/GETTING_STARTED.md#6-first-admin-login).

---

## 4. Patent lifecycle

The full status vocabulary (Title-Case, as returned by the API):

```text
Draft → Submitted → Awaiting Patent Agent Acceptance → Under Review
→ Changes Requested → Ready for Draft Generation → Draft Generated
→ Ready for Filing → Filed → Examination Requested → FER Received
→ FER Response Submitted → Hearing Scheduled → Granted / Rejected / Withdrawn / Abandoned
```

Transitions the API currently produces:

```text
create (Draft) → submit (Submitted) → assign/auto-assign (Awaiting Patent Agent Acceptance)
  → accept (Under Review) → generate draft or document (Draft Generated)
  → reject (back to Submitted, assignment cleared) → reassign
```

Guards live in `backend/app/api/resources.py` and `backend/app/services/projections.py`:

- `submit`: patent creator or admin, only while `Draft`.
- `assign` / `auto-assign` / `reassign`: admin only; the assignee must be an approved `PATENT_AGENT`.
- `accept` / `reject`: the assigned agent (admins may act on their behalf).
- Basic info, applicants, and inventors are editable only while `Draft`.
- Draft generation requires `Under Review` and a completed questionnaire; document generation requires `Under Review` or `Draft Generated`.

Statuses beyond `Draft Generated` (filing, examination, grant) are display/import states today; no endpoint moves an application into them yet. See [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md#5-patent-lifecycle).

---

## 5. Tech stack

**Backend (`backend/`)**

| Layer | Technology |
|---|---|
| API | FastAPI `>=0.115,<1.0`, Uvicorn, Pydantic Settings |
| Auth / data | `firebase-admin >=6.6,<8.0` — Firebase Authentication and Cloud Firestore |
| Documents | `python-docx`, `docxtpl` (templates), `pdf2docx` (PDF uploads converted to Word in-process) |
| HTTP / uploads | `httpx`, `python-multipart` |
| Tests | `pytest >=8.3` (offline; no Firebase credentials) |
| Runtime | Python 3.11+ (Docker: `python:3.13-slim`), Gunicorn + Uvicorn workers in production |

**Frontend (`frontend/`)**

| Layer | Technology |
|---|---|
| UI | React 18.3, React Router 6.28, Tailwind CSS 3.4 |
| Auth | Firebase JS SDK 13.x (Google popup with redirect fallback) |
| Domain widgets | FullCalendar 6.1 (calendar) |
| Build | Vite 6.0, TypeScript 5.7 (`strict`, `noUnusedLocals/Parameters`) |
| Runtime | Node 20 (Docker build stage), nginx 1.27-alpine (serve stage) |

**Infrastructure**

- `docker-compose.yml`: backend + frontend, with Firebase external. No database container.
- `backend/Dockerfile`: multi-stage Python build, no office suite, non-root `appuser`, `HEALTHCHECK /health`, two Gunicorn/Uvicorn workers.
- `frontend/Dockerfile`: Node build → nginx serve with SPA fallback (`frontend/nginx.conf`).
- CI: `.github/workflows/ci.yml` (offline pytest + frontend build + docs health), `docker.yml` (image builds + health smoke test), `codeql.yml` (CodeQL).

---

## 6. Repository layout

```text
patent_drafting_tool/
├── README.md                  # You are here
├── LICENSE                    # Apache-2.0
├── CODE_OF_CONDUCT.md         # Contributor Covenant 2.1
├── CONTRIBUTING.md            # How to set up, branch, test, and open PRs
├── SECURITY.md                # How to report vulnerabilities + hardening notes
├── ACCESSIBILITY.md           # WCAG 2.2 AA commitments + known gaps
├── SUPPORT.md                 # Where to get help
├── CHANGELOG.md               # Release history (Keep a Changelog)
├── DEPLOYMENT.md              # Production deployment guide
├── docker-compose.yml         # Local backend + frontend (Firebase external)
├── firebase.json              # Firestore rules deploy config
├── firestore.rules            # Deny all direct client access
├── docs/
│   ├── GETTING_STARTED.md     # Step-by-step first run
│   ├── ARCHITECTURE.md        # System, auth, data, and workflow design
│   ├── API_OVERVIEW.md        # Endpoint catalog
│   ├── DEVELOPMENT.md         # Conventions, scripts, debugging
│   ├── DOCKER.md              # Image, compose, and env reference
│   ├── FAQ.md                 # Repeated questions
│   ├── TROUBLESHOOTING.md     # Symptom-first fixes
│   └── decisions/             # ADR-001 … ADR-006
├── .github/
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── CODEOWNERS
│   ├── dependabot.yml
│   ├── ISSUE_TEMPLATE/
│   └── workflows/
│       ├── ci.yml             # Backend + frontend + docs health
│       ├── docker.yml         # Docker build + smoke test
│       └── codeql.yml         # CodeQL security scanning
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, lifespan, /health, router mounts
│   │   ├── api/               # auth.py + resources.py (only routers)
│   │   ├── core/              # config, firebase, security
│   │   └── services/          # repository, projections, rbac, blobs,
│   │                          # drafting, documents
│   ├── tests/                 # Offline pytest suite
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── .env.example
│   └── README.md              # Firebase setup guide
└── frontend/
    ├── src/
    │   ├── App.tsx            # Route map + role guards
    │   ├── context/AuthContext.tsx
    │   ├── lib/firebase.ts    # Lazy Web SDK init
    │   ├── lib/api.ts         # apiFetch/apiUpload/apiDownload
    │   ├── lib/types.ts       # DTOs, status colors, role homes
    │   ├── components/        # Shell, ProtectedRoute, panels, badges
    │   └── pages/             # 14 role-scoped pages
    ├── Dockerfile
    ├── nginx.conf
    ├── package.json
    ├── vite.config.ts
    ├── tailwind.config.js
    └── .env.example
```

---

## 7. Quickstart

### 7.1 Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11+ (3.13 recommended, see `backend/Dockerfile`) | `python --version` |
| Node | 20.x (see `frontend/Dockerfile` build stage) | `node --version` |
| npm | 10+ | Ships with Node 20 |
| Docker + Compose | 24+ / v2 | Only for Option A |
| Firebase project | Firestore + Authentication; no Realtime Database or Storage bucket | See `backend/README.md` §2 |

### 7.2 Option A — Docker Compose

```powershell
# From the repo root, with the Firebase values exported in your shell or .env:
docker compose up --build
```

- Backend: http://localhost:8000 (`GET /health`, docs at `/docs`)
- Frontend: http://localhost:5173
- Firestore and Auth are **external**; there is no database container and no bucket.

`VITE_*` values are build args, not runtime variables — exporting them before `docker compose build` is what bakes them into the bundle. The backend reads `backend/.env` through `env_file`.

### 7.3 Option B — Run backend + frontend locally

**Backend (Windows PowerShell):**

```powershell
cd backend
py -3.13 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env — at minimum FIREBASE_PROJECT_ID, FIRESTORE_DATABASE_ID, BOOTSTRAP_ADMIN_EMAIL
python -m uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000/docs and http://127.0.0.1:8000/health.
`/health` returns `503` until Firebase credentials are valid — that is expected before setup.

**Frontend (new terminal):**

```powershell
cd frontend
npm ci
Copy-Item .env.example .env
# Edit .env: VITE_API_URL plus the six VITE_FIREBASE_* values from the Firebase console
npm run dev
```

Open http://localhost:5173.

Full step-by-step walkthrough: [`docs/GETTING_STARTED.md`](./docs/GETTING_STARTED.md).

### 7.4 First admin login

1. Set `BOOTSTRAP_ADMIN_EMAIL` in `backend/.env` to an email you control.
2. Save your Firebase service-account JSON to `backend/secrets/firebase-service-account.json` (git-ignored).
3. From the repository root, run `firebase login`, `firebase use --add`, and `firebase deploy --only firestore:rules` (one-time per project). The rules deny direct browser access; the backend Admin SDK bypasses them.
4. Enable the Google provider in Firebase Authentication and register `localhost` as an authorized domain.
5. Start the backend and frontend, then sign in with that email.
6. Your profile is auto-created as `SUPER_ADMIN` + approved.
7. Approve subsequent users via Super Admin dashboard → Pending Approvals.

---

## 8. Configuration (environment variables)

### 8.1 Backend (`backend/.env`)

Copy from `backend/.env.example`. Never commit `.env` or `secrets/`.

| Variable | Required | Default / example | Purpose |
|---|---|---|---|
| `FIREBASE_PROJECT_ID` | Yes | `your-firebase-project-id` | Firebase project for Auth + Firestore |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | Yes | `secrets/firebase-service-account.json` | Admin SDK credentials (server only) |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | No | _(empty)_ | Inline credentials JSON for hosts without a mountable file (Vercel); keep it in the platform secret manager |
| `FIRESTORE_DATABASE_ID` | No | _(empty = `(default)`)_ | Named Firestore database; see the rules note in `DEPLOYMENT.md` |
| `FIREBASE_EMULATOR_HOST` | No | _(empty)_ | Only when using the Firebase Emulator Suite |
| `BOOTSTRAP_ADMIN_EMAIL` | Yes (first run) | `you@example.com` | First login with this email → `SUPER_ADMIN` |
| `ENVIRONMENT` | Yes | `development` | `development` \| `production` (error detail differs) |
| `CORS_ORIGINS` | Yes | `http://localhost:5173,http://127.0.0.1:5173` | Allowed frontend origins (no `*` in prod) |
| `ALLOWED_HOSTS` | Yes | `localhost,127.0.0.1` | Trusted hosts (real domain in prod) |
| `DEPLOYMENT_TARGET` | No | `self_hosted` | `self_hosted` \| `vercel` (clamps uploads below Vercel's 4.5 MB cap) |
| `MAX_UPLOAD_SIZE_BYTES` | No | `0` (profile default) | Per-file cap; `0` = 10 MiB self-hosted / 4 MiB Vercel; explicit values are clamped on Vercel |
| `ALLOWED_UPLOAD_EXTENSIONS` | No | `.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.odt,.txt,.csv,.md,.rtf,.png,.jpg,.jpeg,.gif,.webp,.tif,.tiff` | Upload allowlist; content is sniffed against the extension, and PDFs are converted to DOCX before storage |
| `AI_API_URL` | No | _(empty)_ | OpenAI-compatible `chat/completions` endpoint (https, or http for localhost) |
| `AI_API_KEY` | With `AI_API_URL` | _(empty)_ | Provider key; stored as a secret, never logged |
| `AI_MODEL` | With `AI_API_URL` | _(empty)_ | Model ID, e.g. `qwen/qwen3.8-27b` |
| `AUTH_RATE_LIMIT_PER_MINUTE` | No | `60` | Per-client cap on mutating `/api/auth` routes; `0` disables |

There are no database, JWT, OAuth-client, or storage-provider variables: `app/core/config.py` reads only the settings above (ADR-005).

### 8.2 Frontend (`frontend/.env`)

Copy from `frontend/.env.example`. `VITE_*` values are **baked at build time**.

| Variable | Required | Purpose |
|---|---|---|
| `VITE_API_URL` | Yes | Backend base URL (Docker build arg) |
| `VITE_FIREBASE_API_KEY` | Yes | Web SDK config from Firebase console → Project settings → Your apps |
| `VITE_FIREBASE_AUTH_DOMAIN` | Yes | Usually `<project>.firebaseapp.com` |
| `VITE_FIREBASE_PROJECT_ID` | Yes | Firebase project ID |
| `VITE_FIREBASE_MESSAGING_SENDER_ID` | Yes | Web SDK config |
| `VITE_FIREBASE_APP_ID` | Yes | Web SDK config |

These values are public by design (they identify the Firebase project). The service-account JSON is the secret and stays server-side. Missing Web SDK values do **not** break the build: `src/lib/firebase.ts` reports a configuration error on the login screen instead.

For a static Vercel deployment, set the same `VITE_*` values in the Vercel project and use the checked-in `vercel.json` (repo-root project) or `frontend/vercel.json` (Root Directory = `frontend`); see `DEPLOYMENT.md` → Vercel deployment notes.

The browser uses the Web SDK for **Authentication only**. Firestore is reached exclusively by the backend Admin SDK, so the checked-in `firestore.rules` deny every direct client read and write. Deploy them with `firebase deploy --only firestore:rules` after `firebase use --add`. There is no Realtime Database or Cloud Storage in this architecture.

---

## 9. Usage walkthrough

**As an Innovator:**

1. Log in → you land on `/innovator`.
2. Create a team, then create a patent inside it.
3. Open `/innovator/patents/:id` → fill **Basic Info** (applicants/inventors) → fill **Questionnaire** → upload supporting files → **Submit**.
4. Track status; respond to agent comments; check Calendar and Reports.

**As a Patent Agent:**

1. Log in → `/agent` shows the assignment queue (`Awaiting decision` vs rest).
2. Accept (or decline with reason) an assignment.
3. Open `/agent/patents/:id/draft` → generate sections (`Abstract`, `Background`, `Summary`, `Detailed Description`, `Claims`) → review versions → generate the DOCX → collaborate via comments/files/calendar.

**As an Admin / Super Admin:**

1. `/admin` → All Patents, Templates; `/super-admin` → Pending Approvals, RBAC Matrix, All Users, Templates, Report Permissions.
2. Approve/reject users, assign/reassign agents (auto-assign picks the least-loaded approved agent), manage `.docx` templates, export CSV reports.

---

## 10. API overview

Both routers are mounted in `backend/app/main.py` (`/api/auth` + `/api`). Full catalog with auth requirements: [`docs/API_OVERVIEW.md`](./docs/API_OVERVIEW.md).

Highlights:

- `GET /health` — Firestore probe (`200 ok` / `503 degraded`).
- `GET /api/auth/me`, `POST /api/auth/sync`, `POST /api/auth/logout`, `GET /api/auth/pending-users`, `POST /api/auth/users/{uid}/approve|reject`.
- `GET/POST /api/teams`, `GET /api/teams/{id}`, member add/remove.
- `GET/POST /api/patents`, `GET /api/patents/{id}`, `POST .../submit`, `.../assign|reassign|auto-assign`, `.../assignment/accept|reject`.
- `GET/PATCH/POST /api/patents/{id}/questionnaire…`, `POST .../draft/generate`, `GET .../draft…`.
- `GET/POST /api/patents/{id}/files…`, `.../documents…`, applicants/inventors/comments/calendar-events CRUD + reorder.
- `GET /api/notifications…`, `GET /api/calendar/events`, `GET/POST /api/templates…`, `GET /api/reports…`, `GET/POST /api/rbac…`.

Authenticated calls require `Authorization: Bearer <Firebase ID token>`.

---

## 11. Development

See [`docs/DEVELOPMENT.md`](./docs/DEVELOPMENT.md) and [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the full guide. Essentials:

```powershell
# Backend checks (from backend/)
python -m compileall app
pip install -r requirements.txt
python -m pytest -q

# Frontend checks (from frontend/)
npm ci
npm run lint
npm run build
```

Conventions: TypeScript `strict` + `noUnusedLocals`; functional React components; route guards via `ProtectedRoute`; backend permission guards via `ensure_permission` / `is_admin`; never commit `.env` or `secrets/`. See [`AGENTS.md`](./AGENTS.md) for the short operator/agent checklist.

---

## 12. Testing

| Suite | Command | Notes |
|---|---|---|
| Backend (pytest) | `cd backend; python -m pytest -q` | Offline suite: forces empty Firebase config, asserts boot, the mounted frontend contract, and pure-Python services. No credentials needed. |
| Frontend build | `cd frontend; npm run build` | Runs `tsc -b && vite build` — type-check + bundle. |
| Frontend lint | `cd frontend; npm run lint` | `eslint .` (advisory until a shared config lands). |
| CI | GitHub Actions `ci.yml` | Backend on ubuntu/windows/macos × Python 3.11/3.13; frontend on the same three OSes; docs-health on ubuntu. |
| Docker | `docker.yml` + `docs/DOCKER.md` | Image builds + backend `/health` smoke test. |

The offline suite cannot prove live Firebase IAM or that the deployed `firestore.rules` match this repository. The manual checklist for a real project is in [`backend/README.md`](./backend/README.md) §7.

---

## 13. Docker

| Image | Dockerfile | Run |
|---|---|---|
| Backend | `backend/Dockerfile` | `docker build -t patent-backend ./backend` → `docker run -p 8000:8000 --env-file backend/.env patent-backend` |
| Frontend | `frontend/Dockerfile` | `docker build --build-arg VITE_API_URL=https://api.example.com --build-arg VITE_FIREBASE_API_KEY=... -t patent-frontend ./frontend` → `docker run -p 8080:80 patent-frontend` |
| Compose | `docker-compose.yml` | `docker compose up --build` (backend + frontend; Firebase external) |

Details, env mapping, and production notes: [`docs/DOCKER.md`](./docs/DOCKER.md).

---

## 14. Deployment

Full guide: [`DEPLOYMENT.md`](./DEPLOYMENT.md) (Firebase project setup, container/PaaS steps, env checklist, single-instance scale notes, verification).

Production checklist:

- `ENVIRONMENT=production`, `CORS_ORIGINS` restricted to the real frontend origin, `ALLOWED_HOSTS` set to the real backend host.
- Firebase service-account JSON mounted as a secret (never baked into the image); `FIREBASE_PROJECT_ID` / `FIRESTORE_DATABASE_ID` point at the production project.
- `BOOTSTRAP_ADMIN_EMAIL` set for the first login, then removed or changed per policy.
- One backend replica: document generation runs in-process and holds a worker while it writes to Firestore (ADR-003).
- Health check: `GET /health` → `200`; `503` means Firebase is not configured or reachable.
- Generated documents and uploads live in Firestore, compressed, not on the container filesystem.

---

## 15. Documentation index

| Document | Purpose |
|---|---|
| [`docs/GETTING_STARTED.md`](./docs/GETTING_STARTED.md) | First-run tutorial, Firebase setup, login |
| [`docs/TROUBLESHOOTING.md`](./docs/TROUBLESHOOTING.md) | Symptom-first fixes (ports, auth, Docker, CI) |
| [`docs/FAQ.md`](./docs/FAQ.md) | Short answers to repeated questions |
| [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) | System diagram, auth model, Firestore collections, lifecycle, AI providers |
| [`docs/decisions/`](./docs/decisions/) | ADRs 001–005 (Firebase runtime, roles, single instance, stub-first AI, Firestore-only) |
| [`docs/API_OVERVIEW.md`](./docs/API_OVERVIEW.md) | Endpoint catalog with methods, auth, and payloads |
| [`docs/DEVELOPMENT.md`](./docs/DEVELOPMENT.md) | Dev workflow, code style, scripts, common errors |
| [`docs/DOCKER.md`](./docs/DOCKER.md) | Docker + Compose reference |
| [`backend/README.md`](./backend/README.md) | Firebase backend setup + endpoint list |
| [`DEPLOYMENT.md`](./DEPLOYMENT.md) | Production deployment guide |
| [`CHANGELOG.md`](./CHANGELOG.md) | Release history |
| [`CONTRIBUTING.md`](./CONTRIBUTING.md) | How to contribute |
| [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md) | Community standards |
| [`SECURITY.md`](./SECURITY.md) | Vulnerability reporting + hardening |
| [`ACCESSIBILITY.md`](./ACCESSIBILITY.md) | Accessibility commitments + gaps |
| [`SUPPORT.md`](./SUPPORT.md) | Getting help |
| [`AGENTS.md`](./AGENTS.md) | Agent-oriented repo instructions (commands, conventions, boundaries) |
| [`CITATION.cff`](./CITATION.cff) | How to cite this project |

---

## 16. Contributing

We welcome issues, docs improvements, bug fixes, and features. Please read [`CONTRIBUTING.md`](./CONTRIBUTING.md) first — it covers:

- Good-first-issue workflow, branch naming, conventional commits.
- Backend + frontend setup, required checks (`pytest`, `tsc`, `eslint`, Docker build).
- PR process (template, linked issues, screenshots for UI, no secrets).

By contributing you agree to abide by the [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md).

---

## 17. Code of Conduct

This project follows the **Contributor Covenant v2.1**. Be kind, be respectful, assume good faith. Enforcement is described in [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md).

---

## 18. Security

If you find a vulnerability, **do not open a public issue**. Follow [`SECURITY.md`](./SECURITY.md) (private report, what to include, response timeline, supported versions, hardening notes).

---

## 19. Accessibility

We target **WCAG 2.2 AA** for the frontend. Scope, keyboard support, known gaps (FullCalendar density, PDF canvas, colour-contrast debt), and how to report barriers: [`ACCESSIBILITY.md`](./ACCESSIBILITY.md).

---

## 20. Support

- Questions / ideas: [GitHub Discussions](https://github.com/auraflaa/patent_drafting_tool/discussions) (or open a docs issue).
- Bugs: [issue tracker](https://github.com/auraflaa/patent_drafting_tool/issues) with the Bug template.
- Response expectations and troubleshooting: [`SUPPORT.md`](./SUPPORT.md).

---

## 21. Changelog

See [`CHANGELOG.md`](./CHANGELOG.md) (Keep a Changelog format). The Unreleased section tracks the Firestore-only migration and the offline test suite.

---

## 22. License

Apache-2.0 — see [`LICENSE`](./LICENSE).

```text
Copyright 2026 auraflaa and patent_drafting_tool contributors.
SPDX-License-Identifier: Apache-2.0
```

---

## 23. Acknowledgements

- Built with FastAPI, React, Vite, Firebase Authentication, and Cloud Firestore.
- Word pipeline via `python-docx` + `docxtpl`; PDF uploads converted to DOCX with `pdf2docx`.
- Calendar via FullCalendar.
- Thanks to all contributors — see commit history.
