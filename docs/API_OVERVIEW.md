# API overview

Base URL: `VITE_API_URL` (default `http://localhost:8000`). Interactive schema: `GET /docs` (OpenAPI at `/openapi.json`).

Auth: `Authorization: Bearer <Firebase ID token>` unless noted. The token is obtained by signing in with the Firebase JS SDK on the client; the API never mints tokens.

Conventions:

- "Approved user" means `active_user`: a valid Firebase ID token plus `account_status = approved` (Title-Case `Approved` in responses).
- "`<PERMISSION>`" means the caller's effective permission set must include that code. Super Admin implicitly holds all 27.
- Errors are `{detail: string}`. `204` returns no body. Downloads stream the file with `Content-Disposition: attachment`.
- IDs are Firestore document IDs (strings). RBAC role/permission IDs are catalog numbers.

## Health

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/` | No | Service info `{name, version, docs, health}` |
| `GET` | `/health` | No | Firestore probe; `200 ok/connected` or `503 degraded` |
| `GET` | `/api/config/capabilities` | No | Runtime limits: `{deployment_target, max_upload_size_bytes, max_request_body_bytes, max_stored_size_bytes}` |

The frontend reads `/api/config/capabilities` once per page load and rejects
oversized files before uploading. Uploads over the cap return `413`; an upload
that cannot fit in one Firestore document after compression also returns
`413`, with the ~900 KB limit named in the message. Document generation is
Word-only, so a `PDF` output request returns `400`.

## Auth (`/api/auth`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/auth/me` | Firebase user | `{user, permissions}`; creates the profile on first call; refreshes `last_login_at` at most every 5 min |
| `POST` | `/api/auth/sync` | Firebase user | Merge `{full_name, phone_number, designation, organization, bio, profile_picture}`; returns `{user, permissions}` |
| `POST` | `/api/auth/logout` | Firebase user | `204` acknowledgment; the real sign-out happens in the browser |
| `GET` | `/api/auth/pending-users` | `<USERS_APPROVE>` | Accounts with `account_status = pending` |
| `POST` | `/api/auth/users/{user_id}/approve` | `<USERS_APPROVE>` | Body `{role_codes: ["INNOVATOR", …]}` (at least one); sets approved. Granting `SUPER_ADMIN`, or changing a Super Admin account's roles at all, requires a Super Admin caller, and no change may leave zero Super Admins |
| `POST` | `/api/auth/users/{user_id}/reject` | `<USERS_APPROVE>` | Sets `rejected`; cannot reject your own account or a Super Admin |

The bootstrap email (`BOOTSTRAP_ADMIN_EMAIL`) is always projected as an approved `SUPER_ADMIN`, even if an older profile said otherwise.

## Teams (`/api/teams`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/teams` | `<TEAMS_VIEW>` | List visible teams (admin sees all, else owned/joined) |
| `POST` | `/api/teams` | `<TEAMS_MANAGE>` | Body `{team_name}`; creator becomes owner and first member |
| `GET` | `/api/teams/{team_id}` | `<TEAMS_VIEW>` + membership/admin | Team with `members[]` |
| `POST` | `/api/teams/{team_id}/members` | `<TEAMS_MANAGE>` + team owner/admin | Body `{email}` of an existing user |
| `DELETE` | `/api/teams/{team_id}/members/{member_id}` | `<TEAMS_MANAGE>` + team owner/admin | Remove member |

Membership is a `teams/{id}/members/{uid}` subcollection; removing a member removes that row.

## Patents (`/api/patents`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/patents` | `<PATENTS_VIEW>` | Visible patents only; `?team_id=` scopes to one team (404/403 for invisible teams), `?limit=` caps the response (default 1000, max 1000) |
| `POST` | `/api/patents` | `<PATENTS_CREATE>` | Body `{team_id, invention_title}`; starts as `Draft` |
| `GET` | `/api/patents/available-agents` | `<PATENTS_ASSIGN>` | Approved `PATENT_AGENT` users with active assignment counts |
| `GET` | `/api/patents/{patent_id}` | `<PATENTS_VIEW>` + visibility | One patent |
| `PATCH` | `/api/patents/{patent_id}` | `<PATENTS_EDIT>` + creator/admin, status `Draft` | Body `{invention_title}`; renames the application |
| `POST` | `/api/patents/{patent_id}/submit` | `<PATENTS_SUBMIT>` + creator/admin, status `Draft` | → `Submitted` |
| `POST` | `/api/patents/{patent_id}/assign` | `<PATENTS_ASSIGN>` + creator/admin | Body `{patent_agent_id}`; → `Awaiting Patent Agent Acceptance` |
| `POST` | `/api/patents/{patent_id}/auto-assign` | `<PATENTS_ASSIGN>` + creator/admin | Picks the least-loaded approved agent |
| `POST` | `/api/patents/{patent_id}/reassign` | `<PATENTS_REASSIGN>` + admin | Body `{patent_agent_id, reason}`; appends assignment history |
| `POST` | `/api/patents/{patent_id}/assignment/accept` | Assigned agent | → `Under Review` |
| `POST` | `/api/patents/{patent_id}/assignment/reject` | Assigned agent | Body `{reason?}`; clears the assignment, → `Submitted` |

## Applicants and inventors

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/patents/{patent_id}/applicants` | Visible | List ordered by `display_order` |
| `POST` | `/api/patents/{patent_id}/applicants` | Visible + editable (`Draft`) | Create applicant |
| `PATCH` | `/api/patents/{patent_id}/applicants/{applicant_id}` | Visible + editable | Partial update |
| `DELETE` | `/api/patents/{patent_id}/applicants/{applicant_id}` | Visible + editable | `204` |
| `POST` | `/api/patents/{patent_id}/applicants/reorder` | Visible + editable | Body `{ordered_ids: [...]}` |
| `GET` | `/api/patents/{patent_id}/inventors` | Visible | List ordered by `inventor_order` |
| `POST` | `/api/patents/{patent_id}/inventors` | Visible + editable | Create inventor |
| `PATCH` | `/api/patents/{patent_id}/inventors/{inventor_id}` | Visible + editable | Partial update |
| `DELETE` | `/api/patents/{patent_id}/inventors/{inventor_id}` | Visible + editable | `204` |
| `POST` | `/api/patents/{patent_id}/inventors/reorder` | Visible + editable | Body `{ordered_ids: [...]}` |

"Editable" is `can_edit_basic_info`: application status `Draft` and caller is the creator or an admin.

## Questionnaire

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/patents/{patent_id}/questionnaire` | Visible | Existing questionnaire or a `Not Started` default |
| `PATCH` | `/api/patents/{patent_id}/questionnaire` | Visible + editable | Merge fields; recomputes status and `completion_percentage` |
| `POST` | `/api/patents/{patent_id}/questionnaire/submit` | Visible + editable | Requires all required fields; snapshots a version; → `Completed` |
| `GET` | `/api/patents/{patent_id}/questionnaire/versions` | Visible | Version history, newest first |

Questionnaire fields: `invention_type`, `problem_statement`, `proposed_solution`, `novelty_description`, `technical_description`, `advantages`, `prior_art`, `keywords`, `has_existing_drawings`, plus the form input fields `invention_keyword`, `title_keyword`, `problem_keyword`, `claim_keyword`, `data1`, `data2`, `field`, `domain`, `area`, `one_line_about_field`, `two_lines_about_domain`, `three_lines_about_area`, `four_lines_about_problem`, `four_lines_about_solution`, `advantage1`, `advantage2`, `exemplary_scenario`, `detailed_exemplary_scenario`, `best_working_method`. Unknown keys return `422`.

## Drafting (`drafts`) — legacy, deprecated

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/patents/{patent_id}/draft` | `<DRAFTS_VIEW>` + assigned agent/admin | Latest output per section (5 slots, `latest: null` where absent) |
| `POST` | `/api/patents/{patent_id}/draft/generate` | `<DRAFTS_GENERATE>` + assigned agent/admin | Body `{section_types?: [...]}`; requires `Under Review` + completed questionnaire |
| `GET` | `/api/patents/{patent_id}/draft/{section_type}/versions` | `<DRAFTS_VIEW>` + assigned agent/admin | Versions for one section |

Section types: `ABSTRACT`, `BACKGROUND`, `SUMMARY`, `DESCRIPTION`, `CLAIMS`. Stub provider by default; every response text carries the draft-only warning (ADR-004). Superseded by form-field refinement below; kept for existing records.

## Form-field refinement and statutory forms

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/forms/catalog` | Signed in | Form codes, labels, required/optional variables |
| `POST` | `/api/patents/{patent_id}/forms/refine` | `<DRAFTS_GENERATE>` + assigned agent/admin | Body `{groups?: [...]}`; AI rephrases questionnaire answers into filing values, stored versioned per group |
| `GET` | `/api/patents/{patent_id}/form-fields` | `<DRAFTS_VIEW>` + assigned agent/admin | Latest refined group per group code |
| `PATCH` | `/api/patents/{patent_id}/form-fields` | `<DRAFTS_GENERATE>` + assigned agent/admin | Body `{group, fields}`; edits save as a new version, never touch the questionnaire |
| `POST` | `/api/patents/{patent_id}/figures/classify` | `<DRAFTS_GENERATE>` + assigned agent/admin | Vision second opinion over figure candidates (needs `AI_VISION_ENABLED`) |
| `POST` | `/api/patents/{patent_id}/forms/generate` | `<DOCUMENTS_GENERATE>` + assigned agent/admin | Body `{codes?: [...], counts?: {page_count, claim_count, claims_page_count, abstract_page_count, drawing_page_count}}`; only allowlisted count keys are accepted (unknown keys are rejected, values capped at 40 chars). `drawing_count` is always derived from the selected figures. Renders each form with its own job row |
| `GET` | `/api/patents/{patent_id}/forms` | `<DOCUMENTS_VIEW>` | Per-form status, missing fields, usable-figure count, finalize state |
| `POST` | `/api/patents/{patent_id}/forms/finalize` | `<DOCUMENTS_GENERATE>` + assigned agent/admin | Locks the set; requires all forms, complete fields, ≥1 usable figure, and no failed job newer than its document |
| `GET` | `/api/patents/{patent_id}/forms/{code}/download` | `<DOCUMENTS_VIEW>` | Stream the latest DOCX (`<title>-FORM1-v3.docx`) |
| `GET` | `/api/patents/{patent_id}/forms/{code}/versions` | `<DOCUMENTS_VIEW>` | Version list with embedded/omitted figures |

Refinement groups: `FORM_METADATA`, `FORM_BACKGROUND`, `FORM_EMBODIMENTS`. Form codes: `FORM1`, `FORM2`, `FORM3`, `FORM5`, `DRAWINGS`. Every generated form ends with one "This is for drafting purposes only and is not legal advice; a qualified patent professional must review it before filing." disclosure (ADR-008); the legacy per-section warnings stay on the old path only.

## Files

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/patents/{patent_id}/files` | Visible | List metadata; `?limit=` caps the response (default 1000, max 1000) |
| `POST` | `/api/patents/{patent_id}/files` | `<FILES_UPLOAD>` | Multipart field `upload`; validates non-empty, size cap, extension allowlist. A PDF is converted to DOCX before storage and returns `source_file_name` + `converted_from_pdf`. Extraction runs in-process: text plus figure candidates with screening. |
| `GET` | `/api/patents/{patent_id}/files/{file_id}/download` | Visible | Streams the stored file as an attachment |
| `GET` | `/api/patents/{patent_id}/files/{file_id}/text` | Visible | Extracted markdown the drafting model reads |
| `GET` | `/api/patents/{patent_id}/files/{file_id}/figures` | Visible | Figure rows with `usable`, `reason`, captions |
| `GET` | `/api/patents/{patent_id}/files/{file_id}/figures/{figure_id}/image` | Visible | Streams the figure crop |
| `PATCH` | `/api/patents/{patent_id}/files/{file_id}/figures/{figure_id}` | `<FILES_UPLOAD>` | Body `{caption?, include_in_drawings?, usable?, display_order?}`; `"usable"` on a rejected figure records "approved by user". A user decision is recorded and vision never overrides it |
| `DELETE` | `/api/patents/{patent_id}/files/{file_id}` | Uploader, admin, or `<FILES_DELETE>` | Delete blob + metadata + extraction rows; `204` |

Image uploads (`.png`, `.jpg`, `.jpeg`) become single figure candidates. Figure rows carry `usable` (`usable`/`rejected`/`unknown`), `reason`, `vision_description`, `include_in_drawings`, `display_order`.

## Documents — legacy single-document path, deprecated

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/patents/{patent_id}/documents` | `<DOCUMENTS_VIEW>` | List documents |
| `GET` | `/api/patents/{patent_id}/documents/jobs` | `<DOCUMENTS_VIEW>` | List generation jobs |
| `POST` | `/api/patents/{patent_id}/documents/generate` | `<DOCUMENTS_GENERATE>` + assigned agent/admin | Body `{output_format: "DOCX"}`; status `201`, returns the job. `"PDF"` returns `400`. |
| `POST` | `/api/patents/{patent_id}/documents/jobs/{job_id}/retry` | `<DOCUMENTS_GENERATE>` + assigned agent/admin | Re-runs a failed job |
| `GET` | `/api/patents/{patent_id}/documents/{document_id}/versions` | `<DOCUMENTS_VIEW>` | Version list |
| `GET` | `/api/patents/{patent_id}/documents/{document_id}/download` | `<DOCUMENTS_VIEW>` | Stream the generated DOCX |
| `GET` | `/api/patents/{patent_id}/documents/versions/{version_id}/download` | `<DOCUMENTS_VIEW>` | Stream a specific version |

Generation requires the application to be `Under Review` or `Draft Generated`.
Documents are Word-only (ADR-006): the DOCX is gzip-compressed into Firestore,
and a generated file that cannot fit one document is reported as a failed job
with the limit in `error_message`.

## Comments and calendar

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/patents/{patent_id}/comments` | Visible | List comments with author names |
| `POST` | `/api/patents/{patent_id}/comments` | `<COMMENTS_POST>` | Body `{comment_text}` |
| `GET` | `/api/patents/{patent_id}/calendar-events` | Visible | Patent-scoped events |
| `POST` | `/api/patents/{patent_id}/calendar-events` | `<CALENDAR_MANAGE>` | Body `{event_type, event_date}` |
| `DELETE` | `/api/patents/{patent_id}/calendar-events/{event_id}` | `<CALENDAR_MANAGE>` | `204` |
| `GET` | `/api/calendar/events` | `<CALENDAR_VIEW>` | Events visible to the caller |

Event types: `Filing Deadline`, `Examination`, `Hearing`, `Reminder`.

## Notifications

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/notifications` | `<NOTIFICATIONS_VIEW>` | Own notifications, newest first, with `invention_title` |
| `GET` | `/api/notifications/unread-count` | `<NOTIFICATIONS_VIEW>` | `{unread_count}` |
| `PATCH` | `/api/notifications/{notification_id}/read` | Owner | Mark one read |
| `POST` | `/api/notifications/read-all` | `<NOTIFICATIONS_VIEW>` | Mark all read |

## Templates

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/templates` | `<TEMPLATES_VIEW>` | All templates |
| `GET` | `/api/templates/document-types` | `<TEMPLATES_VIEW>` | Supported document types |
| `POST` | `/api/templates` | `<TEMPLATES_MANAGE>` | Multipart `upload` + query `document_type`, `activate`; accepts `.docx` and `.pdf` (PDFs are converted to DOCX; legacy `.doc` is rejected). Templates with unknown placeholders or parse errors are stored inactive and cannot be activated |
| `POST` | `/api/templates/{template_id}/activate` | `<TEMPLATES_MANAGE>` | Deactivates siblings of the same type |
| `DELETE` | `/api/templates/{template_id}` | `<TEMPLATES_MANAGE>` | Delete blob + metadata |

Document types: `Patent Application`, `Provisional Specification`, `Complete Specification`, `PCT Application`. Known placeholders: `TITLE`, `WATERMARK_TEXT`, `ABSTRACT`, `BACKGROUND`, `SUMMARY`, `DESCRIPTION`, `CLAIMS`.

## Reports

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/reports` | `<REPORTS_VIEW>` | Catalog with per-type `can_download` |
| `GET` | `/api/reports/dashboard` | Approved user | Status counts, action-required count, unread notifications, upcoming events, recent activity (admins) |
| `GET` | `/api/reports/{report_type}` | `<REPORTS_VIEW>` | Rows for one report type |
| `GET` | `/api/reports/{report_type}/export` | `<REPORTS_VIEW>` | CSV attachment |
| `GET` | `/api/reports/permissions/matrix` | `<RBAC_MANAGE>` | Roles × report types |
| `POST` | `/api/reports/permissions/toggle?grant=true\|false` | `<RBAC_MANAGE>` | Body `{role_id, report_type}`; the `users` report can never leave admin hands |

Report types: `patent_applications`, `documents`, `calendar_events`, `users`. Report downloads can additionally be restricted per role through the report-permission matrix.

## RBAC

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/rbac/matrix` | `<RBAC_MANAGE>` | Roles, 27 permissions, effective grants |
| `POST` | `/api/rbac/toggle?grant=true\|false` | `<RBAC_MANAGE>` | Body `{role_id, permission_id}`; Super Admin grants are immutable |
| `GET` | `/api/rbac/users` | `<RBAC_MANAGE>` | Users with roles and status |
| `POST` | `/api/rbac/users/{target_id}/roles` | `<RBAC_MANAGE>` | Body `{role_code}`; adds a role. Granting `SUPER_ADMIN` requires a Super Admin caller |
| `DELETE` | `/api/rbac/users/{target_id}/roles/{role_code}` | `<RBAC_MANAGE>` | Removes a role; cannot remove your own `SUPER_ADMIN`, cannot leave zero Super Admins, every user keeps at least one role |

The catalog is code-defined (`app/services/rbac.py`); overrides are stored in Firestore (`rbac_overrides`, `report_permission_overrides`). Role/permission IDs in these payloads are numeric catalog IDs.
