# Architecture

## 1. System overview

```text
                    +-------------------------+
                    |      React + Vite       |
                    |  frontend/ :5173 / :80  |
                    +-----------+-------------+
                       |                 |
        Firebase JS SDK|                 | HTTPS / JSON + multipart
        (Google sign-in)                 | Authorization: Bearer <ID token>
                       v                 v
             +------------------+  +--------------------+
             |  Firebase Auth   |  |  FastAPI backend   |
             |  (identity)      |  |  backend/ :8000    |
             +------------------+  |  app/main.py       |
                       ^           +---------+----------+
                       | verify ID token      |
                       |            +---------+----------+
                       +------------| Firebase Admin SDK|
                                    +----+---------+----+
                                         |
                                 Cloud Firestore
                                 (all app data, including
                                  gzip-compressed documents)
```

- **Frontend** (`frontend/`): React 18 SPA with React Router role-guarded routes and FullCalendar for the calendar view. Firebase JS SDK performs Google sign-in; `VITE_*` values are baked at build time, so there is no runtime env. There is deliberately no client state library: server state flows through `lib/api.ts` (`apiFetch`/`apiUpload`/`apiDownload`) with per-component `useState`, and auth/session state lives in `AuthContext`.
- **Backend** (`backend/app/main.py`): FastAPI with a `lifespan` that attempts `initialize_firebase()` but never blocks boot. `/health` probes Firestore. Mounts exactly two routers: `auth` (`/api/auth`) and `resources` (`/api`). CORS + TrustedHost middleware; a generic 500 handler that stays terse in production.
- **Firebase**: Authentication is the identity provider; Firestore is the system of record and also stores the document bytes (ADR-006). The browser uses Firebase Auth only — all data access goes through the API, whose Admin SDK runs privileged. The checked-in `firestore.rules` therefore deny every direct client read and write; Security Rules do **not** replace backend authorization. The Realtime Database and Cloud Storage are not used.

## 2. Request lifecycle

1. The browser signs in through Firebase Auth (Google popup, redirect fallback) and holds a Firebase **ID token**.
2. `src/lib/api.ts` registers an async token provider (`setTokenProvider`), so every request asks Firebase for a current token before calling the API. There is no cached token to expire in the client.
3. `app/core/security.py:current_user` verifies the token (`verify_id_token`), loads `users/{uid}`, and creates the profile on first sight (bootstrap email → `SUPER_ADMIN` + approved; everyone else → `INNOVATOR` + pending).
4. `active_user` rejects non-approved or disabled accounts (`403`).
5. Endpoints then use `ensure_permission(user, "<CODE>")` and/or `is_admin()` / `is_super_admin()`.
6. `app/services/projections.py` decides visibility (`patent_visible`, `visible_patents`, `require_patent`) and serialises documents into the REST shapes the client expects.

## 3. Roles, permissions, and auth model

| Role code | Granted by | Meaning |
|---|---|---|
| `INNOVATOR` | Default for new users | Own teams + patents |
| `PATENT_AGENT` | Role assignment (`RBAC_MANAGE`; Super Admin only for the Super Admin role) | Can be assigned patents |
| `ADMIN` | Role assignment | Approve users, assign agents, manage templates |
| `SUPER_ADMIN` | Bootstrap email, then Super Admins only | Full control incl. role assignment |

- Roles are stored as `role_codes: string[]` on the user document (ADR-002). The API projects them as `roles`.
- Internal state is lowercase (`account_status`: `pending` → `approved` / `rejected`); the API projects Title-Case values (`Pending`, `Approved`, …) for the existing UI.
- The permission catalog is code-defined in `app/services/rbac.py`: 4 roles × 27 permissions, with sensible defaults per role. Super Admin always holds every permission. Super Admin toggles are stored in `rbac_overrides`; report-download grants live in `report_permission_overrides`. No seed script is required — an empty Firebase project falls back to the code-defined matrix.
- Admins can toggle the matrix (`/api/rbac/toggle`), and `RBAC_MANAGE` holders can assign or revoke non-Super-Admin roles. Granting or revoking `SUPER_ADMIN` — or changing a Super Admin account's roles at all — requires a Super Admin, and no change may leave zero Super Admins.
- Sign-in is browser-side only: no server-minted JWT, no refresh endpoint, no dev login. The product's 30-minute inactivity rule is enforced by `AuthContext`, which signs the Firebase session out after idling.
- Route guards: `ProtectedRoute(requireRole=[...], requirePermission=...)` redirects to `/login`, `/pending-approval`, or `/not-authorized`.

## 4. Firestore collections

No joins, no migrations — documents are linked by string IDs and filtered in the service layer.

| Collection | Key fields | Linked by |
|---|---|---|
| `users` | `role_codes[]`, `account_status`, `approved_by/at`, `last_login_at` | `uid` (doc ID) |
| `teams` | `team_name`, `team_status`, `created_by` | `created_by` + `members` subcollection |
| `teams/{id}/members` | membership row per user | `user_id` (doc ID) |
| `patents` | `team_id`, `invention_title`, `application_status`, `assigned_patent_agent_id`, `assignment_history[]`, lifecycle sub-statuses | `created_by`, `team_id`, `assigned_patent_agent_id` |
| `applicants`, `inventors` | `patent_application_id`, order fields | `patent_application_id` |
| `questionnaires` | `patent_application_id`, status, answers | `patent_application_id` |
| `questionnaire_versions` | snapshot + `version_number` | `patent_application_id` |
| `drafts` | `patent_application_id`, `section_type`, `version_number`, `ai_response` | `patent_application_id` |
| `documents` | `patent_application_id`, `output_format`, `stored_path` (blob id) | `patent_application_id` |
| `document_versions` | `document_id`, `version_number`, `storage_path` (blob id) | `document_id` |
| `document_jobs` | `patent_application_id`, `status`, `error_message` | `patent_application_id` |
| `files` | `patent_application_id`, `blob_id`, `uploaded_by`, `converted_from_pdf`, `extraction_status`, `extraction_error` | `patent_application_id` |
| `file_extractions` | `file_id`, `status`, `method`, `text_blob_id`, `figure_count`, `error`, `extracted_at` | `file_id` (doc ID), `patent_application_id` |
| `file_figures` | `file_id`, `usable`, `include_in_drawings`, `caption`, `caption_override`, `image_blob_id`, `display_order` | `file_id`, `patent_application_id` |
| `comments` | `patent_application_id`, `user_id`, `comment_text` | `patent_application_id` |
| `calendar_events` | `patent_application_id`, `event_type`, `event_date` | patent and/or creator |
| `notifications` | `recipient_uid`, `notification_type`, `is_read` | recipient |
| `templates` | `document_type`, `is_active`, `file_path` (blob id) | one active per type |
| `activity` | `user_id`, `event_type`, `entity_type/id` | dashboard feed |
| `rbac_overrides` | `granted` per `role_id:permission_id` | RBAC matrix |
| `report_permission_overrides` | `granted` per `role_id:report_type` | report matrix |
| `blobs` | `data` (gzip), `encoding`, `content_type`, `size_bytes`, `stored_bytes`, `sha256` | referenced by `blob_id` / `stored_path` / `storage_path` / `file_path` |

Probe collection `_health` is used only by `/health`.

## 5. Patent lifecycle

The API accepts and returns the full product vocabulary, using Title-Case statuses:

```text
Draft → Submitted → Awaiting Patent Agent Acceptance → Under Review
→ Changes Requested → Ready for Draft Generation → Draft Generated
→ Ready for Filing → Filed → Examination Requested → FER Received
→ FER Response Submitted → Hearing Scheduled → Granted / Rejected / Withdrawn / Abandoned
```

Transitions currently produced by the API:

```text
create (Draft) → submit (Submitted) → assign/auto-assign (Awaiting Patent Agent Acceptance)
  → accept (Under Review) → generate draft or document (Draft Generated)
  → reject (back to Submitted, assignment cleared) → reassign
```

Guards in `app/api/resources.py` and `app/services/projections.py`:

- `submit`: patent creator or admin, and only while `Draft`.
- `assign` / `auto-assign` / `reassign`: `ADMIN`/`SUPER_ADMIN`; assignee must be an approved `PATENT_AGENT`; auto-assign picks the lowest active assignment count. Assignment history is appended to the patent document.
- `accept` / `reject`: the assigned agent (admins may act on their behalf); rejection clears the assignment.
- Basic info + applicants/inventors are editable only while `Draft` (`can_edit_basic_info`).
- Draft generation requires `Under Review` and a completed questionnaire; document generation requires `Under Review` or `Draft Generated` and the assigned agent/admin.
- Statuses beyond `Draft Generated` (filing, examination, grant) are display/import states today; no endpoint moves an application into them yet.

## 6. AI drafting and refinement

Two paths share the stub-first contract (ADR-004): with no `AI_*` configured, deterministic stubs keep every flow exercisable offline; half-configured AI fails loudly.

- **Legacy section drafts** (`app/services/drafting.py`, deprecated): five fixed sections (`ABSTRACT` … `CLAIMS`) from the questionnaire plus capped extraction context, stored as `drafts` rows. Questionnaire answers and extracted text travel inside delimited data-only blocks; invented reference numerals are logged, not blocked.
- **Form refinement** (`app/services/form_ai.py`, current): three field groups (`FORM_METADATA`, `FORM_BACKGROUND`, `FORM_EMBODIMENTS`) refined from raw answers plus keyword-ranked excerpts (`select_context`) and optional vision input for embodiments only. `validate_group_output` enforces exact keys, lengths, noun-phrase/verb grammar, control-character bans, numeral-invention checks, and `[[FIG:alias]]` marker consistency — with one text-only repair retry, then a stub fallback whose rows satisfy the same rules. A provider image refusal falls back per request, never process-wide.

Figure aliases are row-id derived (`extraction_store.figure_alias`) so markers stored in refined text survive re-renders; `forms.substitute_figure_markers` resolves them to sheet numbers at render time and fails closed on unknown aliases. Delimiters are advisory only — enforcement lives in code (ADR-008 §"Prompt-security posture").

## 7. Documents and files

- **Documents**: `POST .../documents/generate` runs a generation job synchronously. `app/services/documents.py` renders DOCX with `docxtpl` when an active template exists for the document type, otherwise with the built-in `python-docx` layout. Word is the only output format: the DOCX is gzip-compressed by `app/services/blobs.py` into a `blobs` document (capped at 900 KB compressed, ADR-006), `documents` / `document_versions` / `document_jobs` rows are written, and the patent moves to `Draft Generated`.
- **Downloads**: files and documents are streamed through the API with `Content-Disposition: attachment`; there are no signed URLs to expire. The API decompresses the blob, verifies its SHA-256, and streams it from memory.
- **Files**: `POST .../files` (multipart) validates non-empty content, size cap, and the extension allowlist. A PDF is converted to DOCX in-process with `pdf2docx` first; the result is compressed into a blob and a `files` row records `blob_id`, the converted name, `source_file_name`, and `converted_from_pdf`. Delete removes blob + row + extraction rows + figure blobs (uploader, `FILES_DELETE`, or admin).
- **Extraction** (`app/services/ingestion.py`, `extraction_store.py`): after the upload is stored, OpenDataLoader (JVM) reads PDFs into text plus figure bounding boxes; DOCX/PPTX/text/images are parsed in-process. Captions bind to the next image only. Rows land in `file_extractions` (text blob, status, error) and `file_figures` (usable/screening flags, captions, image blobs). Extraction never fails the upload. Deterministic screening (`figure_quality.py`) plus an optional YOLO DocLayNet detector (`figure_detection.py`, weights mounted never committed; failures are reported on the extraction row, not raised) feed the drawings sheet.
- **Templates**: `POST /api/templates` (admin, multipart `.docx` or `.pdf`; legacy `.doc` is rejected, PDFs are converted to DOCX) stores the template as a blob referenced by `templates.file_path`, records unknown placeholders and parse errors, and stores bad templates inactive — activation of a broken template is refused. `render_docx` renders through a sandboxed Jinja environment with `StrictUndefined`, so unknown placeholders fail loudly instead of rendering blanks.

## 8. Frontend architecture

- Entry `index.html` → `src/main.tsx` (`QueryClientProvider` + `StrictMode`) → `src/App.tsx` (`BrowserRouter` + `AuthProvider` + role routes).
- `ROLE_HOME` maps the first matching role to its dashboard; `ProtectedRoute` handles gating and pending accounts.
- Data flow: pages → `apiFetch`/`apiUpload`/`apiDownload` → React Query (where used) → `StatusBadge` / `DashboardShell` / feature panels.
- Entity IDs are Firestore strings throughout; only the RBAC catalog keeps numeric role/permission IDs.
- 14 pages (4 dashboards + workflow + draft workspace + admin patent list/detail + calendar + reports + auth pages) and shared components (`DashboardShell`, `ProtectedRoute`, `LoadingState`, `EmptyState`, `StatusBadge`, panels).

## 9. Cross-cutting concerns

- **Config**: `app/core/config.py` (`pydantic-settings`, `.env`, `extra='ignore'`) — Firebase, app, upload, and AI settings only.
- **Observability**: JSON application logs carrying `event` plus the per-request `X-Request-ID` (accepted from the client when safe, minted otherwise), uvicorn/gunicorn access logs, and a `/health` probe that answers `200` connected or `503` degraded (which the Docker healthcheck accepts as "up"). No metrics pipeline yet.
- **Scaling**: single-instance assumption — document generation, PDF conversion, extraction, and AI batches run in-process on two gunicorn workers. See ADR-003.
- **Verification**: `backend/tests/` is an offline suite (no Firebase credentials). Live Auth/Firestore behaviour is covered by the manual checklist in `backend/README.md` §7.
- **Rate limiting**: `app/core/ratelimit.py` implements in-memory sliding windows: a strict cap on mutating `/api/auth/*` (`AUTH_RATE_LIMIT_PER_MINUTE`, default `60`) plus a looser per-IP budget across all other `/api/` routes (`API_RATE_LIMIT_PER_MINUTE`, default `300`) covering draft generation, refinement, uploads, and exports. Session endpoints and framework paths are exempt. Set `FORWARDED_ALLOW_IPS` to your proxy so each user gets their own bucket; otherwise every user shares the proxy IP. The bucket is per gunicorn worker; with multiple workers the effective limit multiplies — rate-limit at the platform edge (WAF, Cloud Run concurrency) for production multi-replica deployments.
- **Session persistence**: `AuthContext` persists profile, permissions, and status to `localStorage` under `patent-platform:profile:v2`. On reload the cached state renders immediately while Firebase restores the session in the background; on logout or 401 the cache is cleared.
- **Error boundary**: `ErrorBoundary` wraps `<App>` in `main.tsx`. Render errors produce a friendly UI instead of a blank page; all frontend errors are logged via `lib/api.ts#logError` and user-facing messages are generic (e.g. "Your session has expired. Please sign in again.").

## 10. Decision records

The reasoning behind the significant choices above is recorded in [`decisions/`](./decisions/):

- [ADR-001](./decisions/ADR-001-firebase-active-runtime.md) — Firebase-native backend as the active runtime (superseded)
- [ADR-002](./decisions/ADR-002-role-codes-array.md) — Roles as a `role_codes` array on the user document
- [ADR-003](./decisions/ADR-003-single-instance.md) — Single backend instance
- [ADR-004](./decisions/ADR-004-stub-first-ai.md) — Stub-first AI drafting with optional OpenAI-compatible provider
- [ADR-005](./decisions/ADR-005-firestore-only-runtime.md) — Firestore-only runtime; legacy SQL stack removed
- [ADR-006](./decisions/ADR-006-firestore-document-storage.md) — Word-only documents stored as compressed Firestore blobs
- [ADR-007](./decisions/ADR-007-document-ingestion.md) — Document ingestion pipeline (OpenDataLoader extraction, figure candidates)
- [ADR-008](./decisions/ADR-008-sheet-driven-forms.md) — Sheet-driven statutory forms with AI-assisted refinement
