# ADR-005: Firestore-only runtime (legacy SQL stack removed)

## Status

Accepted — supersedes [ADR-001](./ADR-001-firebase-active-runtime.md).

## Date

2026-10-27

## Context

[ADR-001](./ADR-001-firebase-active-runtime.md) made the Firebase-native
backend the active runtime but kept the original Postgres + SQLAlchemy +
Alembic implementation in-tree as "reference only". In practice that meant:

- Two data models, two test suites, and two sets of docs in one repository.
  Contributors could not tell from the tree which one was authoritative.
- `pytest` needed a live Postgres and legacy mounts, so the default test
  command failed on a clean Firebase checkout and CI carried an advisory
  "legacy" job that could never block a regression.
- Every dependency review, security scan, and Docker rebuild included code
  that was never mounted, never deployed, and never exercised.
- The frontend already spoke the legacy REST contract (`invention_title`,
  `application_status`, Title-Case statuses, `roles`, `completion_percentage`
  as a string). A Firestore-native redesign would have forced a parallel
  frontend migration for no product benefit.

The Firebase implementation (`app/api/auth.py`, `app/api/resources.py`,
`app/services/*`) had reached feature coverage for every route the React
client calls, and an offline test suite could assert that coverage without
credentials.

## Decision

1. **Delete the legacy stack.** `app/models/`, `app/schemas/`, `alembic/`,
   the 13 unmounted routers, the SQL services, the legacy `core/` modules
   (`database`, `oauth`, `startup_checks`, `rate_limit`, `middleware`,
   `logging_config`), the old `tests/`, `seed.py`, `pytest.ini`, and
   `docker-entrypoint.sh` are removed. Nothing is "reference only" any more.
2. **Firebase is the only backend**: Firebase Authentication for identity and
   Cloud Firestore for application data, including uploaded and generated
   documents (see [ADR-006](./ADR-006-firestore-document-storage.md)). There
   is no database container, no migration step, and no `DATABASE_URL`.
3. **Preserve the REST contract in the service layer.** Firestore documents
   store lowercase internal state (`account_status`, `role_codes`,
   `application_status`), while `app/services/projections.py` serialises the
   exact snake_case shapes the frontend already consumes, including
   Title-Case account statuses and the API field `roles` (projected from
   `role_codes`, per ADR-002).
4. **String identifiers end to end.** Firestore document IDs replace the
   legacy integer primary keys; `Number(id)` casts are gone from the client.
   The only numeric IDs left are the code-defined role and permission catalog
   entries, which are never document IDs.
5. **Browser-side Firebase Auth.** The React client signs in with the
   Firebase JS SDK (Google popup, redirect fallback) and sends a fresh ID
   token on every request. The API verifies the token; it does not mint
   sessions, run a Google OAuth redirect, or expose a dev login.
6. **Code-defined RBAC with Firestore overrides.** The role/permission
   catalog and default matrix live in `app/services/rbac.py`; Super
   Admin toggles are stored in `rbac_overrides` / `report_permission_overrides`.
   A project without override documents therefore still boots with a working
   matrix.
7. **Offline verification.** `backend/tests/` forces empty Firebase
   configuration and asserts boot, the mounted frontend contract, and the
   pure-Python services (RBAC catalog, stub drafts, DOCX rendering). CI runs
   it on every push; there is no Postgres service and no advisory legacy job.

## Alternatives Considered

### Keep the dual stack until a later migration issue
- Pros: no large diff; the legacy suite can still be run by anyone who wants it.
- Cons: keeps the ambiguity, the failing default test command, and the
  dependency/CI overhead that ADR-001 already flagged; the removal has been
  scheduled twice without happening.
- Rejected: the Firebase path is now the only path the product uses.

### Rewrite the API in a Firestore-native shape and migrate the frontend
- Pros: no projection layer, idiomatic document names, cleaner payloads.
- Cons: touches every page, component, and type in the client for a purely
  cosmetic API change, while doing the backend removal in the same PR.
- Rejected as a separate concern: the REST contract is a stable seam. A
  future breaking rename deserves its own ADR and its own PR.

### Keep Postgres as an optional backend behind a flag
- Pros: teams that already run Postgres keep a path.
- Cons: two authorization models, two visibility implementations, no way to
  test both in CI without doubling the infrastructure; the product has no
  requirement for relational reporting.
- Rejected: optional backends are how the dual stack started.

## Consequences

- **Removed surface**: no Alembic, no SQLAlchemy, no asyncpg/psycopg, no
  `docker-entrypoint.sh`, no Postgres service in Compose, no server-minted
  JWT, no refresh endpoint, no dev login. The CI `docs-health` job fails the
  build if any of those names reappear in shipped code.
- **Deployment**: one backend container + one static/nginx frontend. Firebase
  project configuration (service account, project ID, Firestore database) is
  the only external dependency; no bucket or object store is provisioned.
- **Auth lifecycle**: Firebase refreshes ID tokens itself. The product's
  30-minute inactivity rule is enforced client-side in `AuthContext`; the API
  remains stateless.
- **Documents**: Word only. DOCX is rendered with `docxtpl` (template) or a
  built-in `python-docx` layout (fallback), gzip-compressed, and stored in
  Firestore; uploaded PDFs are converted to DOCX on the way in. Generated
  text keeps the draft-only warning. See
  [ADR-006](./ADR-006-firestore-document-storage.md).
- **Data model**: Firestore has no joins. Relations are string references and
  list endpoints filter in the service layer, which is acceptable at the
  project's tenant sizes (see `docs/ARCHITECTURE.md` §4).
- **Verification limit**: the offline suite proves contract and service
  behaviour, not live Firebase IAM or Firestore rules. Manual role
  walkthroughs against a real project remain the release check
  (`backend/README.md` §7).
