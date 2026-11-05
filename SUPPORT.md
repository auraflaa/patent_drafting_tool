# Support

## Where to get help

| Channel | Use for | Link |
|---|---|---|
| Getting Started guide | First run, Firebase setup, first admin login | [`docs/GETTING_STARTED.md`](./docs/GETTING_STARTED.md) |
| Troubleshooting | Symptom-first fixes (ports, auth, Docker, CI) | [`docs/TROUBLESHOOTING.md`](./docs/TROUBLESHOOTING.md) |
| Architecture / API / Docker docs | Design questions, endpoint reference, container help | [`docs/`](./docs/) |
| GitHub Discussions | Questions, ideas, show-and-tell | https://github.com/auraflaa/patent_drafting_tool/discussions |
| Issue tracker | Confirmed bugs, feature requests, docs gaps | https://github.com/auraflaa/patent_drafting_tool/issues |
| Security reports | Vulnerabilities — **private only** | [`SECURITY.md`](./SECURITY.md) |

## Before asking

1. Check [`docs/TROUBLESHOOTING.md`](./docs/TROUBLESHOOTING.md),
   [`docs/GETTING_STARTED.md`](./docs/GETTING_STARTED.md) §8, and
   [`docs/DEVELOPMENT.md`](./docs/DEVELOPMENT.md) §6.
2. Search existing issues and discussions — your question may already be
   answered.
3. Collect: commit SHA (`git rev-parse --short HEAD`), OS, Python/Node
   versions, backend vs frontend logs, and exact error text.

## Response expectations

- Maintainers aim to acknowledge new issues within **5 business days**.
- `good first issue` / `help wanted` issues are the best place for new
  contributors to start.
- Security reports follow the timelines in [`SECURITY.md`](./SECURITY.md)
  (48-hour acknowledgement), not the general queue.

## Troubleshooting quick table

| Symptom | Likely cause | Fix |
|---|---|---|
| `GET /health` → `503 degraded` | Firebase credentials missing/unreachable | Verify `FIREBASE_PROJECT_ID`, service-account path, network; see `backend/README.md` §2 |
| `401` on every API call | Missing/expired Firebase ID token | Re-login; confirm `Authorization: Bearer <token>` is sent |
| `403 awaiting approval` | Account is pending | Ask an Admin to approve via Super Admin → Pending Approvals |
| Login shows a configuration banner | `VITE_FIREBASE_*` values empty | Fill `frontend/.env`, restart `npm run dev` |
| `auth/unauthorized-domain` | Frontend origin not registered | Firebase console → Authentication → Authorized domains |
| `npm run build` type errors | `noUnusedLocals` / strict violations | Remove unused imports/vars; run `tsc -b` locally |
| Docker `/health` fails | Firebase env missing or port mismatch | Confirm `--env-file`, mounted `secrets/`, port `8000` (backend) / `80` (frontend), `VITE_API_URL` build arg |

If none of this helps, open a Discussion with your environment details and
logs (redact secrets and tokens).
