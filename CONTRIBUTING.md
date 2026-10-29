# Contributing to patent_drafting_tool

Thank you for considering a contribution. This guide covers everything you
need to go from a fresh clone to a merged pull request.

---

## Table of contents

- [Code of Conduct](#code-of-conduct)
- [Ways to contribute](#ways-to-contribute)
- [Project overview](#project-overview)
- [Prerequisites](#prerequisites)
- [Getting the code](#getting-the-code)
- [Backend setup](#backend-setup)
- [Frontend setup](#frontend-setup)
- [Running with Docker](#running-with-docker)
- [Branching and commits](#branching-and-commits)
- [Commit discipline (atomic commits)](#commit-discipline-atomic-commits)
- [Making changes](#making-changes)
- [Required checks before a PR](#required-checks-before-a-pr)
- [Opening a pull request](#opening-a-pull-request)
- [Code style](#code-style)
- [Testing guide](#testing-guide)
- [Docs contributions](#docs-contributions)
- [Review process](#review-process)
- [Release process](#release-process)
- [Getting help](#getting-help)

---

## Code of Conduct

By participating you agree to follow the [Code of Conduct](./CODE_OF_CONDUCT.md).
Be respectful, assume good faith, and keep discussions focused on the work.

---

## Ways to contribute

- **Report bugs** — use the Bug report issue template, include repro steps,
  expected vs actual, logs, and environment.
- **Propose features** — use the Feature request template, describe the
  problem first, then the proposal and alternatives.
- **Improve docs** — typos, clarifications, missing steps, and new guides are
  all welcome (use the Documentation template).
- **Fix code** — pick an issue labeled `good first issue` or `help wanted`, or
  open an issue first for larger changes.
- **Review PRs** — thoughtful reviews are contributions too.

> Code changes should be small, surgical, and covered by the PR template.
> Large refactors need an approved issue first.

---

## Project overview

- `backend/` — FastAPI + Firebase Admin. Routers are `app/api/auth.py` and
  `app/api/resources.py`; services are `repository.py`, `projections.py`,
  `rbac.py`, `blobs.py`, `uploads.py`, `drafting.py`, `documents.py`.
- `frontend/` — React 18 + Vite 6 + TypeScript (`strict`) + Tailwind 3 +
  Firebase JS SDK. Role-guarded routes in `src/App.tsx`.
- `docker-compose.yml` — backend + frontend images. Firebase (Auth and
  Firestore, which also stores the documents) is external; there is no
  database container and no bucket.
- `.github/workflows/` — `ci.yml` (backend/frontend/docs-health), `docker.yml`
  (image builds), `codeql.yml` (security scan).

Detailed design: [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md),
[`docs/API_OVERVIEW.md`](./docs/API_OVERVIEW.md),
[`docs/DEVELOPMENT.md`](./docs/DEVELOPMENT.md), and the ADRs in
[`docs/decisions/`](./docs/decisions/). Firebase-only is **ADR-005**; do not
reintroduce SQL, an ORM, migrations, or a second system of record.

---

## Prerequisites

| Tool | Version | Check |
|---|---|---|
| Python | 3.11+ (3.13 recommended) | `python --version` |
| Node | 20.x | `node --version` |
| npm | 10+ | `npm --version` |
| Git | 2.40+ | `git --version` |
| Docker + Compose | 24+ / v2 (optional) | `docker --version` |
| Firebase project | Firestore + Auth | See `backend/README.md` §2 |

Windows contributors: use **Windows PowerShell 5.1+** (commands below assume
it). macOS/Linux contributors: translate `Copy-Item` → `cp` and venv
activation accordingly.

---

## Getting the code

```powershell
git clone https://github.com/auraflaa/patent_drafting_tool.git
cd patent_drafting_tool
git checkout -b <type>/<short-description>
```

Branch types: `feat/`, `fix/`, `docs/`, `chore/`, `ci/`, `refactor/`, `test/`.
Example: `docs/add-architecture-guide`.

Keep your branch up to date:

```powershell
git fetch origin
git rebase origin/main
```

---

## Commit discipline (atomic commits)

Every commit must do **one logical thing** and stay reviewable. This is
enforced in review — PRs with giant mixed commits are sent back for splitting.

- **Size targets:** ~100 lines per commit is ideal, ~300 acceptable for a
  single logical change (e.g. one complete guide), ~1000+ must be split. A
  commit that touches docs *and* workflows *and* repo config is three commits,
  not one.
- **Separate concerns:** docs, CI, community-health files, and repo hygiene
  each get their own commit(s). Never mix formatting-only changes with
  behaviour changes, and never bundle a refactor with a feature.
- **One commit = one type:** the commit-type prefix (`feat`, `fix`, `docs`,
  `ci`, `chore`, `refactor`, `test`) must describe the *whole* commit. If you
  need two prefixes, you need two commits.
- **Example stack** (how the open-source foundation of this repo was landed —
  each line is one commit):
  ```text
  docs: rewrite README with full product and setup guide
  docs: add getting-started, architecture, API, development, and Docker guides
  docs: add contributor documentation set (contributing, conduct, security, accessibility, support, changelog)
  docs: add Apache-2.0 license
  docs: add GitHub community-health files (PR template, issue forms, owners, dependabot)
  ci: add cross-OS lint/test/build matrix workflow
  ci: add Docker build+smoke and CodeQL workflows
  chore: standardise repo hygiene (gitignore, editorconfig, gitattributes, version pins)
  ```
- **Verify per commit:** each commit in the stack must leave the tree in a
  working state — run the relevant check (`python -m compileall app`,
  `npm run build`, YAML parse) before moving to the next slice, not just once
  at the end.
- **Messages explain why:** subject in imperative mood (<72 chars), blank line,
  body with intent and scope notes. `docs: expand getting-started Firebase
  steps` + why, not `update file`.

---

## Backend setup

```powershell
cd backend
py -3.13 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env: FIREBASE_PROJECT_ID, FIRESTORE_DATABASE_ID, BOOTSTRAP_ADMIN_EMAIL
python -m uvicorn app.main:app --reload --port 8000
```

Verify:

- http://127.0.0.1:8000/docs — interactive API docs
- http://127.0.0.1:8000/health — `200 ok` once Firebase is configured,
  `503 degraded` before that (expected)

Firebase setup (project creation, Firestore, Auth providers, service-account
JSON → `backend/secrets/firebase-service-account.json`):
[`backend/README.md`](./backend/README.md) §2 and
[`docs/GETTING_STARTED.md`](./docs/GETTING_STARTED.md).

> Never commit `.env` or `secrets/`. Both are git-ignored and CI never needs
> real credentials.

---

## Frontend setup

```powershell
cd frontend
npm ci
Copy-Item .env.example .env
# Edit .env: VITE_API_URL plus the six VITE_FIREBASE_* values from the
# Firebase console → Project settings → Your apps → Web app.
npm run dev
```

Open http://localhost:5173.

| Script | Purpose |
|---|---|
| `npm run dev` | Vite dev server (`:5173`) |
| `npm run build` | `tsc -b && vite build` → `dist/` |
| `npm run preview` | Preview the production build |
| `npm run lint` | `eslint .` |

Missing Firebase values do not break the build; the login screen shows a
configuration error instead. `VITE_*` values are baked at dev-server
start/build time.

---

## Running with Docker

```powershell
# Full local stack (backend + frontend; Firebase external):
$env:VITE_API_URL = "http://localhost:8000"
$env:VITE_FIREBASE_API_KEY = "..."
# ... the other five VITE_FIREBASE_* values ...
docker compose up --build

# Backend image only:
docker build -t patent-backend ./backend
docker run -p 8000:8000 --env-file backend/.env `
  -v "${PWD}/backend/secrets:/app/secrets:ro" patent-backend

# Frontend image only (every VITE_* value is baked at build time):
docker build --build-arg VITE_API_URL=http://localhost:8000 -t patent-frontend ./frontend
docker run -p 8080:80 patent-frontend
```

More: [`docs/DOCKER.md`](./docs/DOCKER.md).

---

## Branching and commits

- One logical change per PR. Keep diffs small and reviewable.
- Use [Conventional Commits](https://www.conventionalcommits.org/):
  - `feat: add patent submit confirmation dialog`
  - `fix: correct assignment accept guard for agents`
  - `docs: expand getting-started Firebase steps`
  - `ci: add windows runner to frontend build matrix`
  - `chore: bump vite to 6.x`
  - `test: cover questionnaire submit flow`
- Write imperative, specific subjects (<72 chars), blank line, then body
  explaining **why**.
- Never commit secrets, `.env` files, `secrets/*.json`, `dist/`,
  `__pycache__/`, or `venv/`.

---

## Making changes

1. **Find the right place.** Backend route → `backend/app/api/`; Firestore
   CRUD → `backend/app/services/repository.py`; REST shapes and visibility →
   `backend/app/services/projections.py`; permission catalog →
   `backend/app/services/rbac.py`; auth guards → `backend/app/core/security.py`.
   Frontend page → `frontend/src/pages/`; shared fetch →
   `frontend/src/lib/api.ts`; types → `frontend/src/lib/types.ts`; Firebase
   init → `frontend/src/lib/firebase.ts`.
2. **Match existing patterns.** Backend: `ensure_permission` /
   `require_roles` / `is_admin` guards, projections before returning documents,
   `404` via the repository helpers. Frontend: `ProtectedRoute` guards,
   `apiFetch`/`apiUpload`, `StatusBadge` colours, `DashboardShell` layout,
   `LoadingState`/`EmptyState`.
3. **Do not expand scope.** Don't reformat unrelated files, don't "clean up"
   adjacent systems, don't reintroduce a second data store (ADR-005).
4. **Update docs** when behaviour, env vars, or routes change (README + the
   relevant `docs/` page + `CHANGELOG.md` Unreleased).

---

## Required checks before a PR

Run these locally — CI runs the same across Linux, Windows, and macOS:

```powershell
# Backend (from backend/)
python -m compileall app
pip install -r requirements.txt
python -m pytest -q

# Frontend (from frontend/)
npm ci
npm run lint
npm run build
```

Notes:

- The backend suite is **offline** and needs no Firebase credentials. Live
  Auth/Firestore behaviour, real blob writes, and PDF conversion fidelity are
  manual checks (`backend/README.md` §7). Do not "fix" a red test by deleting
  it — open an issue instead.
- Frontend `npm run build` includes `tsc -b`; a clean build means types pass.
- Docker-affecting PRs: also run the relevant `docker build` from
  [`docs/DOCKER.md`](./docs/DOCKER.md).

---

## Opening a pull request

1. Push your branch and open a PR against `main`.
2. Fill in **every section** of the PR template
   (`.github/PULL_REQUEST_TEMPLATE.md`): summary, linked issues (`Fixes #123`),
   type, scope, testing evidence, screenshots for UI, checklist.
3. Keep the PR focused; link follow-ups instead of piling them in.
4. Respond to review comments; resolve threads when addressed; re-request
   review.
5. Maintainers squash-merge; your PR title becomes the squash message — keep
   it conventional-commit clean.

Draft PRs are welcome for early feedback — mark as draft and note what is
unfinished.

---

## Code style

**Python (backend):**

- Follow PEP 8, 4-space indents, double quotes where the file already uses them.
- Type-hint new functions; keep Firestore helpers thin (see
  `services/repository.py`).
- No `print()` in committed code; use the app logger.
- Keep imports sorted stdlib → third-party → local.

**TypeScript/React (frontend):**

- `strict` mode, `noUnusedLocals`/`noUnusedParameters` — no unused vars.
- Functional components + hooks; named exports (no default exports except
  pages where already used).
- Validate forms with React Hook Form + Zod; fetch via
  `apiFetch`/`apiUpload`/`apiDownload` only.
- Use `cn()`-style conditional classes consistently; reuse `StatusBadge`,
  `DashboardShell`, `ProtectedRoute`, `LoadingState`, `EmptyState`.

**General:**

- Add or update tests/docs alongside behaviour changes.
- Prefer the boring, obvious solution over clever abstractions.

---

## Testing guide

- Backend: `python -m pytest -q` (`pytest.ini` sets `testpaths` and quiet
  output). Tests live in `backend/tests/`; `conftest.py` forces empty Firebase
  configuration and provides a `TestClient`.
- Frontend: no unit-test runner is configured yet — verification is `tsc` +
  `vite build` + manual role walkthroughs (Innovator / Agent / Admin / Super
  Admin). If you add a test runner, document it in `docs/DEVELOPMENT.md` in the
  same PR.
- Manual QA checklist for workflow PRs: create team → create patent → fill
  questionnaire → submit → assign agent → accept → generate draft → generate
  DOCX → upload a PDF (arrives as DOCX) → approve user → export report → toggle
  a permission.

---

## Docs contributions

- Docs live in `README.md` + `docs/*.md` + `backend/README.md` +
  `DEPLOYMENT.md`.
- Keep headings sentence-case, code blocks labeled (`powershell`, `bash`,
  `text`), tables aligned, and links relative (`./docs/ARCHITECTURE.md`).
- If you add an env var, update `.env.example`, the README env table, and the
  relevant `docs/` page in the same PR.
- Architecture changes need an ADR under `docs/decisions/` (append a new
  number; do not rewrite accepted history except to mark it superseded).
- Check markdown rendering (VS Code preview or `npx markdownlint` if
  available) before pushing.

---

## Review process

- All PRs need at least one maintainer approval; `CODEOWNERS` auto-requests
  reviewers.
- CI (`ci.yml`, `docker.yml`, `codeql.yml`) must be green. Failures must be
  fixed or explicitly waived by a maintainer with a follow-up issue.
- Reviewers check: scope discipline, auth guards (`ensure_permission` /
  `ProtectedRoute`), no secrets, docs updated, tests evidence present, and no
  reintroduction of a second data store.

---

## Release process

Maintainers only. See [`CHANGELOG.md`](./CHANGELOG.md):

1. Curate `Unreleased` into a version section (`YYYY-MM-DD`, Keep a Changelog
   format).
2. Tag `vX.Y.Z`, push tag, verify CI + Docker builds on the tag.
3. Attach release notes summarizing features, fixes, and migration notes.

---

## Getting help

- Start with [`SUPPORT.md`](./SUPPORT.md) and
  [`docs/GETTING_STARTED.md`](./docs/GETTING_STARTED.md).
- Bugs: open an issue with the Bug template. Security issues: follow
  [`SECURITY.md`](./SECURITY.md) — do not open public issues.
- Discussions: https://github.com/auraflaa/patent_drafting_tool/discussions
