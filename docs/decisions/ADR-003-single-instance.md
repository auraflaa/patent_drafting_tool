# ADR-003: Single backend instance

## Status
Accepted — amended for the Firestore-only runtime (ADR-005) and Word-only
document storage (ADR-006).

## Date
2026-10-16 (amended 2026-10-27, 2026-10-29)

## Context
The backend runs document generation inside the API process: a request
renders a DOCX, compresses it, and writes it to Firestore. PDF uploads are
converted to DOCX in-process with `pdf2docx`. There is no job queue, no
distributed lock, and no shared cache; work either completes inside the
request or is recorded as a failed generation job. The deployment target is a
single container on a PaaS free/starter tier (see `DEPLOYMENT.md`).

The original version of this ADR also cited in-memory rate limiting and
boot-time Alembic migrations. The migrations are gone with the SQL stack:
Firestore needs none. The single-instance constraint survives for the reasons
above.

## Decision
Run exactly one backend replica. Multi-instance support is explicitly
deferred, not accidentally missing.

## Alternatives Considered

### Add a job queue and scale out
- Pros: correct under autoscaling; generation stops competing with request
  handling for CPU and file descriptors.
- Cons: adds a broker (Redis/Cloud Tasks), a worker image, retry semantics,
  and a second deployment unit — real work that nothing currently requires.
- Deferred: revisit when document volume or availability requirements demand
  a second replica.

### Multi-replica with the current code
- Pros: more capacity for ordinary reads.
- Cons: every replica runs its own in-process document work against the same
  CPU budget, and there is no shared coordination for long-running jobs;
  capacity planning becomes guesswork.
- Rejected: predictable single-container behaviour is better than silently
  oversubscribed replicas.

## Consequences
- `docker-compose.yml`, the Dockerfile, and the deployment docs describe one
  backend service. Do not raise `replicas` or worker count without first
  moving document generation off the request path.
- The Docker image runs two Gunicorn/Uvicorn workers. A PDF conversion or a
  large document write occupies one worker for its duration, so two workers
  is the practical concurrency floor for a responsive API.
- Authentication requests are limited in-process by
  `app/core/ratelimit.py` (`AUTH_RATE_LIMIT_PER_MINUTE`, 0 disables it). Its
  buckets live in each worker's memory, so the limits only hold while there
  is a single backend instance; a shared store is required before scaling
  out. General API limits still belong at the platform edge (PaaS/WAF/Firebase
  quotas).
