# Security Policy

## Supported versions

| Version / branch | Supported |
|---|---|
| `main` (active development) | Yes — security fixes land here first |
| Tagged releases `vX.Y.Z` (once published) | Latest tag only; older tags are not patched |
| Any fork or deployment with modified auth guards | Not supported — verify `ensure_permission` / `ProtectedRoute` are intact |

We have not yet published a stable release. Until `v1.0.0`, treat `main` as the
only supported line and keep deployments updated on every merge.

## Reporting a vulnerability

**Do not open a public GitHub issue for security reports.**

Instead, use one of these private channels:

1. **Preferred:** [GitHub Security Advisories — New draft advisory](https://github.com/auraflaa/patent_drafting_tool/security/advisories/new)
   (private by default).
2. **Fallback:** email **priyangshumukherjee07@gmail.com** with subject
   `[SECURITY] patent_drafting_tool: <short summary>`.

Include:

- Affected component and version/commit (`backend/app/api/...`,
  `frontend/src/...`, Docker tag).
- Steps to reproduce or proof of concept (redacted credentials).
- Impact assessment (what an attacker can read, modify, or escalate to).
- Your contact details and preferred disclosure timeline.

### What happens next

- **Acknowledgement** within **48 hours**.
- **Triage and initial assessment** within **5 business days**.
- **Fix + advisory** as fast as scope allows; we will coordinate a disclosure
  date with you before publishing.
- We will credit reporters in the advisory unless you ask to stay anonymous.

Reports about missing hardening without exploitability (e.g. "add header X")
are welcome as regular issues — mark them `security-hardening`, not
`vulnerability`.

## Scope and hardening notes

This project handles invention disclosures, identity data, and legal drafts.
Treat all of it as sensitive.

Current controls (Firebase runtime):

- **Identity:** Firebase ID tokens are verified with
  `auth.verify_id_token(..., check_revoked=True)`
  (`backend/app/core/firebase.py`). The API never mints tokens and has no
  refresh endpoint.
- **Authorization:** roles are read from `users/{uid}.role_codes` on every
  request; client-supplied roles are ignored. Guards are `ensure_permission`,
  `require_roles`, `is_admin`, and `is_super_admin`
  (`backend/app/core/security.py`). Visibility helpers restrict reads to
  creators, team members, assignees, and admins
  (`backend/app/services/projections.py`).
- **Account gating:** new users are `pending` until approved; the bootstrap
  admin is a single configured email. A Super Admin cannot reject their own
  account or another Super Admin, and approvals, rejections, role changes, and
  permission/report-grant changes write an `activity` audit entry.
- **Report access:** the users report is admin-only. It is omitted from the
  catalog for other roles, rejected by `run`/`export` before any Firestore
  query, and cannot be granted to non-admin roles through the report matrix.
- **Input bounds:** patent titles, applicant/inventor fields, questionnaire
  text, and AI output are length-bounded and type-checked; control characters
  are rejected (except newlines/tabs where a field is multi-line). This keeps
  a single document below Firestore's 1 MiB limit.
- **Upload validation:** non-empty content, `MAX_UPLOAD_SIZE_BYTES` cap, an
  `ALLOWED_UPLOAD_EXTENSIONS` allowlist, and content sniffing (magic bytes)
  so a renamed executable cannot pass as a PDF or image. Uploaded PDFs are
  converted to DOCX and the converted file is re-validated before storage.
  Office containers are checked for the required part and rejected when they
  exceed the ZIP bomb limits (entry count, entry size, total size, compression
  ratio, or encryption). The stored MIME type comes from the validated
  extension, not from the client. Templates are restricted to `.docx`.
- **Transport:** CORS allow-list (`CORS_ORIGINS`), trusted hosts
  (`ALLOWED_HOSTS`), HTTPS required in production, HSTS in production only,
  and a strict CSP on API responses (Swagger/ReDoc exempt). The static
  frontend CSP allows only the Firebase Auth loader (`apis.google.com`) and
  auth frame (`*.firebaseapp.com`, `accounts.google.com`) in addition to
  `'self'`; production startup warns when `ALLOWED_HOSTS` is still `*`.
- **Observability:** every response carries an `X-Request-ID` that is either a
  safe client value or a generated hex ID, and application logs are JSON lines
  carrying that ID and the event name.
- **Storage:** the service-account JSON is mounted/injected at run time and is
  git-ignored. Document bytes live in the `blobs` collection, gzip-compressed
  with a SHA-256 checksum that is verified on every read; they are served only
  through authorised API routes, never through public bucket URLs. Firestore
  rules deny all client access, so a blob id is not a capability.
- **Deployment:** one backend replica, auth-endpoint rate limiting, and a
  Firestore backup/retention policy (`DEPLOYMENT.md`).

Known limitations (do not rely on these for security):

- Firestore Security Rules **do not** replace backend authorization — the
  Admin SDK bypasses them; all checks live in `app/core/security.py` and
  `app/services/projections.py`.
- The in-app rate limiter covers `/api/auth/*` only and keeps its buckets per
  worker. Put general request limits at the platform edge (PaaS/WAF/Firebase
  quotas) before exposing the API publicly.
- The backend assumes a **single instance** (ADR-003); document generation and
  PDF conversion run in-process.
- Generated patent text is a **draft, not legal advice**; it must not be filed
  without professional review.
- Service-account JSON and `.env` files are **never** committed; rotation is
  required if exposed (deleting a later commit is not enough — revoke the
  key).

## Out of scope

- Social engineering, physical attacks, or third-party services (Firebase,
  Google, hosting) themselves.
- Denial-of-service via traffic floods (report tuning ideas as hardening
  issues).
- Vulnerabilities that require modifying the deployed auth guards or granting
  yourself Super Admin directly in Firestore.

## Safe harbour

We support good-faith research: do not access other users' data, do not
disrupt services, delete any data you inadvertently access, and give us
reasonable time to fix before disclosure. We will not pursue legal action
against researchers who follow this policy.
