# AGENTS.md

Guidance for AI coding agents working with or on patent_drafting_tool.

## Stack at a glance

- Backend: FastAPI + Firebase Admin (Auth, Firestore; documents are gzip blobs in Firestore), Python 3.11+ (Docker: 3.13). Routers are `app/api/auth.py` + `app/api/resources.py` only. Firestore is the only system of record (ADR-005/ADR-006).
- Frontend: React 18 + Vite 6 + TypeScript `strict` + Tailwind 3 + Firebase JS SDK, Node 20.
- Decisions live in `docs/decisions/` (ADRs) — read the relevant one before changing auth, data, deployment, or AI code.

## Commands

```powershell
# Backend (from backend/, venv active)
python -m uvicorn app.main:app --reload --port 8000
python -m compileall app
python -m pytest -q            # offline suite: no Firebase credentials needed

# Frontend (from frontend/)
npm ci
npm run dev                    # :5173
npm run build                  # tsc -b && vite build
```

## Conventions

- Conventional commits with one type per commit; atomic commits (~100 lines ideal, ~300 max) — see `CONTRIBUTING.md` → Commit discipline, including the 8-commit stack example.
- Backend guards: `active_user` → `ensure_permission("<CODE>")` / `is_admin()`; visibility via `services/projections.py`. Never trust client-supplied roles.
- API responses keep the legacy REST shapes (`invention_title`, `application_status`, Title-Case statuses, `roles`) through `services/projections.py`; Firestore stores lowercase internal state (`account_status`, `role_codes`).
- Frontend: all HTTP through `lib/api.ts` (`apiFetch`/`apiUpload`/`apiDownload`); auth through `context/AuthContext.tsx` + `lib/firebase.ts`; gating through `ProtectedRoute`; loading/empty UI through `components/LoadingState` / `components/EmptyState` (always centred, `role="status"`).
- Loading states: full/panel loads use `<LoadingState />`, tight inline slots use `<LoadingState compact />`.
- Entity IDs are Firestore strings. The only numeric IDs are role/permission catalog entries.

## Boundaries (do not cross without an approved issue)

- Do not reintroduce SQL, an ORM, migrations, a `DATABASE_URL`, or a second system of record. The CI docs-health job fails on those names in shipped code (ADR-005).
- Do not reintroduce server-minted JWTs, a refresh endpoint, a backend Google redirect, or a dev login. Sign-in is browser-side Firebase Auth only.
- Never commit `.env`, `secrets/*.json`, `dist/`, `venv/`, `node_modules/`, or model binaries.
- Never widen CORS/hosts, weaken upload validation, or bypass permission checks for convenience.
- `ref-repos/` holds ignored reference clones for inspiration — never import from it, never commit it.
- Single backend instance assumption (ADR-003): document generation and PDF conversion run in-process; no multi-replica changes without a job queue.
- Generated patent text is draft-only, never legal advice — keep the warning on every stub/AI surface.
- Seed only foundation accounts (and, when explicitly requested, empty containers). Never seed questionnaires, drafts, generated documents, figures, comments, or other sample content: those are entered manually so the system is exercised with real user actions.
