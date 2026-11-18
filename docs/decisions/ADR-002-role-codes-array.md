# ADR-002: Roles stored as a `role_codes` array on the user document

## Status
Accepted

## Date
2026-10-16

## Context
Every request must answer "what roles does this caller hold?" (`INNOVATOR`, `PATENT_AGENT`, `ADMIN`, `SUPER_ADMIN`). The active auth path (`app/core/security.py`) verifies the Firebase ID token, then loads `users/{uid}` from Firestore on each call. Role storage had to fit Firestore querying (e.g. `available-agents` lists approved users whose `role_codes` contain `PATENT_AGENT`) and the pending → approved onboarding flow.

## Decision
Roles are stored as a `role_codes: string[]` array on the user document. Guards (`require_roles`, `is_admin`) intersect the required set with this array; `SUPER_ADMIN`-only endpoints mutate it via `/api/rbac/users/{id}/roles`.

## Alternatives Considered

### Firebase custom claims
- Pros: roles travel inside the ID token, no document read needed.
- Cons: claim changes propagate only on token refresh (stale-role windows after approval/revocation); Firestore cannot query users by claim, so listings like available-agents would need a parallel store anyway.
- Rejected: worse consistency story and no query benefit.

### Separate `user_roles` collection (SQL-style join table)
- Pros: mirrors the legacy `user_roles` table; unbounded role history.
- Cons: every auth check becomes two reads; Firestore has no joins, so the service layer would fake them per request.
- Rejected: extra reads on the hottest path for no product requirement (four fixed roles, no history needed).

## Consequences
- Role checks cost one user-document read per request (already required for `account_status` gating, so no extra round trip).
- Role revocation takes effect on the next request — no token-refresh lag.
- Roles are data, not identity: never trust client-supplied role values; assignment is `SUPER_ADMIN`-only server-side (bootstrap email excepted on first run).
- The REST API exposes the same array as `roles` (via `app/services/projections.py`); the stored field stays `role_codes` so Firestore queries and the guard helpers keep one spelling. Do not rename the stored field without an ADR.
