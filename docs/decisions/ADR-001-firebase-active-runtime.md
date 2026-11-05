# ADR-001: Firebase-native backend as the active runtime

## Status
Superseded by [ADR-005](./ADR-005-firestore-only-runtime.md) (2026-10-27).

Kept for history: the decision below selected the Firebase runtime but
deliberately retained the SQL stack as reference. ADR-005 removes it.

## Date
2026-10-16

## Context
The repository contains two backend stacks: the original Postgres + SQLAlchemy + Alembic implementation (`app/models/`, `alembic/`, 13 routers, SQL services, `tests/`) and a Firebase-native implementation (Firebase Authentication, Cloud Firestore, Cloud Storage) mounted by `app/main.py` via only two routers (`app/api/auth.py`, `app/api/resources.py`). Running two systems of record was untenable, and managed Postgres operations (migrations on boot, connection pooling, JSONB dependence) added ops burden for a small team.

## Decision
The Firebase-native stack is the active runtime and deployment target. The Postgres/SQLAlchemy code remains in-tree as **reference only**: unmounted, undeployed, and scheduled for removal once the migration is validated (see `CHANGELOG.md` Unreleased → Known gaps).

## Alternatives Considered

### Stay on Postgres + SQLAlchemy
- Pros: relational integrity, existing tests target it, Alembic migrations.
- Cons: keeps the ops burden (managed Postgres, boot-time migrations that race with multiple replicas); the Firebase port was already built and mounted.
- Rejected: would discard completed migration work and keep two sources of truth.

### Full rewrite with no legacy code retained
- Pros: cleanest tree, no confusion about which stack is live.
- Cons: destroys the reference implementation before the Firebase path is validated feature-for-feature; `backend/README.md` explicitly warns the port is not yet a verified feature-for-feature port.
- Rejected: premature — removal requires an approved migration-completion issue.

## Consequences
- Firestore is the system of record: string IDs, no joins, no migrations; relations are string references (`patent_id`, `owner_uid`, `member_uids`).
- Backend authorization lives entirely in `app/core/security.py` + `app/services/repository.py` — Firestore Security Rules do not constrain Admin SDK calls.
- `backend/tests/` still target the legacy API and must be realigned to the Firebase path (tracked gap; CI runs them as an advisory job).
- Deployment target shifts from Neon Postgres to a Firebase project; `DATABASE_URL` is legacy-only.

> Superseded on 2026-10-27 by [ADR-005](./ADR-005-firestore-only-runtime.md): the legacy stack, its tests, and these transitional caveats were removed.
