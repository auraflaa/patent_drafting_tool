# Development guide

## 1. Daily workflow

```powershell
# Terminal 1 — backend (from backend/, venv active):
python -m uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend (from frontend/):
npm run dev
```

- Backend docs: http://127.0.0.1:8000/docs · health: http://127.0.0.1:8000/health
- Frontend: http://localhost:5173 (`VITE_API_URL` must point at the backend)
- Firebase is external. Without credentials the backend still boots; `/health`
  reports `503 degraded` and authenticated calls fail.

## 2. Project conventions

**Backend (`backend/app/`):**

- Routers: `api/auth.py` (identity/profile/approval) and `api/resources.py`
  (everything else). There are no other routers.
- Core: `core/config.py` (settings), `core/firebase.py` (lazy Admin SDK init),
  `core/security.py` (`current_user`, `active_user`, `is_admin`,
  `is_super_admin`, `ensure_permission`).
- Services: `repository.py` (thin Firestore CRUD/query helpers, transactional
  counters), `projections.py` (REST shapes + visibility), `rbac.py`
  (role/permission catalog and overrides), `blobs.py` (gzip documents in
  Firestore), `uploads.py` (extension/sniffing/ZIP guards), `drafting.py`
  (legacy stub/OpenAI-compatible section drafts), `form_ai.py` (grouped AI
  refinement with validation/repair, optional vision), `form_generation.py`
  (per-form jobs, figure selection, finalize gate), `forms.py` (deterministic
  sandboxed form renderer), `form_specs.py` (five form specs),
  `questionnaire_schema.py` (28-field registry), `documents.py` (DOCX
  assembly, PDF→DOCX import), `extraction_store.py` (extraction/figure rows,
  drafting context), `ingestion.py` (PDF/DOCX/PPTX/text/image parsing),
  `figure_detection.py` (optional YOLO DocLayNet detector),
  `figure_quality.py` (deterministic figure screening).
- Guards: `active_user` → `ensure_permission("<CODE>")` and/or
  `require_roles(*codes)` / `is_admin()`; visibility via
  `services/projections.py` (`patent_visible`, `require_patent`).
- Firestore stores lowercase internal state (`account_status`, `role_codes`);
  never expose raw documents — serialise through `projections.py`.
- Never trust client-supplied roles or IDs. Firestore document IDs are opaque
  strings; RBAC catalog IDs are the only numbers.

**Frontend (`frontend/src/`):**

- `App.tsx` owns the route map; `ProtectedRoute` owns gating; `AuthContext`
  owns Firebase session state and the 30-minute idle sign-out.
- All HTTP goes through `lib/api.ts` (`apiFetch`, `apiUpload`, `apiDownload`);
  `setTokenProvider` is registered by `AuthContext` so every request gets a
  fresh Firebase ID token. Never call `fetch` with a manually cached token.
- `lib/firebase.ts` initialises the Web SDK lazily and throws
  `FirebaseConfigError` when `VITE_FIREBASE_*` values are missing.
- Types + constants live in `lib/types.ts` (`STATUS_COLOR`, `ROLE_HOME`,
  `SECTION_TYPES`, `NOTIFICATION_TEXT`, `CALENDAR_EVENT_TYPES`). Entity IDs
  are strings; only RBAC role/permission IDs are numeric.
- Layout via `DashboardShell`; status via `StatusBadge`; loading/empty states
  via `LoadingState` / `EmptyState` (centred, `role="status"`).
- TypeScript `strict` + `noUnusedLocals`/`noUnusedParameters`: keep imports clean.

## 3. Scripts reference

| Location | Command | Purpose |
|---|---|---|
| `backend/` | `python -m uvicorn app.main:app --reload --port 8000` | Dev server |
| `backend/` | `python -m compileall app` | Syntax check (CI gate) |
| `backend/` | `python -m pytest -q` | Offline test suite |
| `backend/` | `gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 2 -b 0.0.0.0:8000` | Prod serve (Docker CMD; Linux only) |
| `frontend/` | `npm run dev` | Dev server `:5173` |
| `frontend/` | `npm run lint` | `eslint .` (required gate) |
| `frontend/` | `npm run build` | `tsc -b && vite build` |
| `frontend/` | `npm run preview` | Preview `dist/` |
| Root | `docker compose up --build` | Backend + frontend images (Firebase external) |

## 4. Environment handling

- Backend: copy `backend/.env.example` → `backend/.env`; service-account JSON
  → `backend/secrets/firebase-service-account.json`. Both git-ignored.
  `config.py` uses `extra='ignore'`, so stale variables do not crash startup —
  but do not add new ones without updating `.env.example` and the docs.
- Firebase rules are committed: `firestore.rules` deny all direct client
  access. Deploy them with `firebase deploy --only firestore:rules`. Do not
  weaken a rule to unblock a local test — the browser only uses Firebase Auth
  and must go through the API. The Firebase CLI cache (`.firebase/`), its debug
  logs, and admin-SDK key files are git-ignored.
- Frontend: copy `frontend/.env.example` → `frontend/.env`. `VITE_*` bake at
  build time — changing them requires restarting `npm run dev` or rebuilding
  (`npm run build` / Docker build arg).
- Never log tokens, service-account JSON, or `AI_API_KEY`. Redact before
  pasting logs into issues.

## 5. Tests

- `backend/tests/conftest.py` forces empty Firebase credentials **before**
  importing the app, so the lifespan records "Firebase not configured"
  instead of reaching the network.
- `backend/tests/test_smoke.py` asserts:
  - the app boots and `/health` reports degraded without credentials;
  - every path the React client calls is mounted (`CONTRACT_PATHS`,
    including the forms/refine/classify and file-text/figure surfaces);
  - the RBAC catalog is internally consistent;
  - stub drafting always carries the not-legal-advice warning;
  - DOCX assembly produces a non-empty document.
- Focused suites sit beside it: `test_form_ai.py` (refinement validation,
  repair, numeral-invention guard, vision fallback), `test_forms.py`
  (golden statutory renders), `test_form_generation.py` (five-form sets,
  finalize gate), `test_ingestion.py` + `test_extraction_store.py`
  (offline extraction via an OpenDataLoader stub, context budgets),
  `test_figure_detection.py` (stub ONNX session, screening), plus guard,
  rate-limit, repository, projections, security-fix, version-race, and
  static-config suites. Total: ~200 tests, all offline.
- Live Firestore/Auth behaviour, real blob writes, and PDF conversion fidelity
  are **not** in pytest. Verify them with the manual checklist in
  `backend/README.md` §7.
- Frontend: no unit runner yet. Verify with `npm run lint` (required),
  `npm run build` (type-check + bundle) and manual walkthroughs per role.
  Adding `vitest` is a welcome `help wanted` contribution (document it here
  in the same PR).

## 6. Common errors

| Error | Cause | Fix |
|---|---|---|
| `firebase: not_configured_or_unreachable` (`503`) | Bad project ID / service-account path / no network | Recheck `FIREBASE_*`, filename under `secrets/`, emulator vars unset |
| `401 Invalid token` | Expired or non-Firebase token | Re-login; confirm the Bearer header and that `AuthContext` registered the token provider |
| `403 awaiting approval` | Pending account | Admin approval via `/super-admin` |
| `422 Unprocessable Entity` | Missing required body field | Compare against `API_OVERVIEW.md` payload |
| `CORS blocked` | Origin not in `CORS_ORIGINS` | Add the exact origin; restart backend |
| Login page shows a configuration error | `VITE_FIREBASE_*` empty | Fill `frontend/.env`, restart `npm run dev` |
| `auth/unauthorized-domain` | Frontend origin not registered | Firebase console → Authentication → Authorized domains |
| `tsc` unused-var errors | `noUnusedLocals` | Delete unused imports/params |
| PDF upload returns `400` | Damaged, encrypted, or over 100 pages | Re-export the PDF, remove its password, or upload a DOCX |
| `413` naming the compression limit | The gzip payload exceeds 900 KB, so it cannot fit one Firestore document | Upload a smaller file or split it |
| | `429 Too Many Requests` | Auth or API rate limit exceeded | Wait, or raise `AUTH_RATE_LIMIT_PER_MINUTE` / `API_RATE_LIMIT_PER_MINUTE`, or set FORWARDED_ALLOW_IPS to your proxy |

## 7. Debugging tips

- Backend: run uvicorn with `--reload`, read non-prod 500 messages
  (`Type: msg`), and inspect `/health` for the Firebase error detail.
- Frontend: open DevTools → Network, confirm requests go to `VITE_API_URL`
  and carry an `Authorization` header. There is no token in `localStorage` —
  Firebase owns the session.
- Firestore: use Firebase Console → Firestore Data viewer to confirm document
  shapes (`role_codes`, `account_status`, `patent_application_id` links).
- Documents: open the `blobs` collection to inspect stored files —
  `size_bytes` is the original size, `stored_bytes` the gzip size (cap
  900,000), and `sha256` the integrity hash. The owning `files`, `templates`,
  `documents`, or `document_versions` row points at the blob id.
- No bucket or emulator is involved: a Firestore emulator suffices for offline
  work (`FIREBASE_EMULATOR_HOST`), because documents and app data live in the
  same database.

## 8. Performance notes

- Firestore list helpers cap at 1,000 docs (`MAX_QUERY_LIMIT`); the two
  biggest user-facing lists (`GET /api/patents`, `GET .../files`) additionally
  take a `limit` (default/max 1000), and report CSVs stream row by row, so one
  response cannot balloon. For larger tenants, prefer query filters (e.g.
  `?team_id=`) over raising caps.
- `FullCalendar` is the heaviest frontend dep; every page (including calendar)
  is route-split with `React.lazy`, so keep it out of the login bundle.
- The backend Docker image stays small: there is no office suite, and PDF
  import is the pure-Python `pdf2docx` dependency (extraction needs a JRE for
  OpenDataLoader — see `Dockerfile`).
- Document generation, PDF conversion, extraction, and AI batches run
  in-process on two gunicorn workers; the deployment assumes one backend
  replica (ADR-003). Bind per-request work with the existing timeouts and
  budgets (`--timeout 240`, `BATCH_DEADLINE_SECONDS`) rather than adding
  workers.

## 9. Rate limiting

`backend/app/core/ratelimit.py` implements in-memory sliding windows:

- Strict cap on mutating `/api/auth/*`: `AUTH_RATE_LIMIT_PER_MINUTE=60`
  (set `0` to disable).
- Looser per-IP budget across all other `/api/` routes:
  `API_RATE_LIMIT_PER_MINUTE=300` (set `0` to disable) — covers draft
  generation, AI refinement, uploads, and exports, the paid-quota and CPU
  hotspots.
- Exempt paths: `/api/auth/me` and `/api/auth/logout` (authenticated polling
  must never be rate-limited), plus framework paths (`/`, `/health`, `/docs`,
  `/redoc`, `/openapi.json`) for the API budget.
- The limiter keys on `X-Forwarded-For`; set `FORWARDED_ALLOW_IPS` to your
  proxy (e.g. `*` on Cloud Run) so every user gets their own bucket rather
  than sharing the proxy IP. Without this, every user shares one limit.
- The limit is per gunicorn worker; with `-w 2` the effective limit is
  approximately doubled. For production replicas, rate-limit at the
  platform/edge (WAF, Cloud Run concurrency, etc.) rather than in-process.

## 10. AI drafting configuration

Backend drafting (`app/services/drafting.py`) supports three environment
variables:

| Variable | Required | Example | Purpose |
|---|---|---|---|
| `AI_API_URL` | No (empty = stub) | `https://api.groq.com/openai/v1/chat/completions` | OpenAI-compatible chat endpoint |
| `AI_API_KEY` | Required if `AI_API_URL` set | `gsk_...` | Bearer token, sent in `Authorization` header |
| `AI_MODEL` | Required if `AI_API_URL` set | `qwen/qwen3.8-27b` | Model name sent in the request body |

All three must be set together; providing only one or two raises a clear
error. When unset, the stub provider returns a clearly labelled placeholder
(no network calls).

Refinement and vision add three more knobs (`app/services/form_ai.py`):

| Variable | Default | Purpose |
|---|---|---|
| `AI_VISION_ENABLED` | off | Allow figure images into the embodiments refinement prompt (capped count/size) |
| `AI_VISION_MAX_IMAGES` / `AI_VISION_MAX_EDGE_PX` | 3 / 512 | Vision cost guard per request |
| `YOLO_MODEL_PATH` | empty (off) | ONNX DocLayNet weights for figure detection; empty means embedded images only |

## 11. Session persistence

`AuthContext` persists `profile`, `permissions`, and `status` to
`localStorage` under `patent-platform:profile:v2`. On reload, the cached
state renders immediately while Firebase restores the session in the
background. On logout or 401, the cache is cleared.

## 12. Error boundary

`frontend/src/components/ErrorBoundary.tsx` wraps `<App />` in `main.tsx`.
React errors during render produce a friendly UI instead of a blank page.
All frontend errors are logged via `lib/api.ts#logError` (console in
development, monitoring endpoint in production); user-facing messages are
always generic (e.g. "Your session has expired. Please sign in again.")
