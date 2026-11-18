# Troubleshooting

Symptom-first fixes for local development. Setup walkthrough:
[`GETTING_STARTED.md`](./GETTING_STARTED.md). Design context:
[`ARCHITECTURE.md`](./ARCHITECTURE.md).

## Ports already in use

Developer machines often run other projects on the same ports this stack
defaults to (`8000` backend, `5173` frontend; Compose also maps `8000`/`5173`).
Symptoms: `uvicorn` fails with `address already in use`, Compose fails to
bind, or `http://localhost:8000/health` returns HTML from an unrelated app.

```powershell
# Find what owns a port:
netstat -ano | Select-String ":8000 "
Get-Process -Id <PID>   # confirm it isn't something you need before touching it
```

- **Do not kill other projects' processes.** Run this stack on free ports instead:
  ```powershell
  # Backend on 8001 (from backend/, venv active):
  python -m uvicorn app.main:app --reload --port 8001
  ```
  Then set `VITE_API_URL=http://localhost:8001` in `frontend/.env` and restart
  `npm run dev` (`VITE_*` values bake at start).
- For Compose, set `BACKEND_PORT` / `FRONTEND_PORT` instead of editing the
  file:
  ```powershell
  $env:BACKEND_PORT = "8001"; $env:FRONTEND_PORT = "5174"; docker compose up --build
  ```

## Backend

| Symptom | Cause | Fix |
|---|---|---|
| `GET /health` → `503 degraded` with Firebase detail | Service-account path wrong, project ID mismatch, or no network | Recheck `FIREBASE_PROJECT_ID`, `FIREBASE_SERVICE_ACCOUNT_PATH`, `secrets/` filename; unset `FIREBASE_EMULATOR_HOST` unless using the emulator |
| `GET /health` → `503` with "database (default) does not exist" | Firestore not provisioned for the project | Firebase Console → Firestore Database → Create database (Native mode), pick a region, then retry |
| `GET /health` → `503` with "default credentials were not found" | No service-account file and no ADC | Place the JSON at `backend/secrets/firebase-service-account.json` or set `FIREBASE_SERVICE_ACCOUNT_JSON` |
| `401` on every API call | Missing/expired Firebase ID token | Re-login; confirm `Authorization: Bearer <token>` is sent (`src/lib/api.ts`) and the token provider is registered |
| `429` on `/api/auth/sync` or `/api/auth/users/...` across several users | One `scope["client"]` bucket: the proxy address is used because `FORWARDED_ALLOW_IPS` is unset | Set `FORWARDED_ALLOW_IPS` to the proxy (e.g. `*` on Cloud Run) or raise `AUTH_RATE_LIMIT_PER_MINUTE`; `/api/auth/me` is exempt |
| `503` when opening a named Firestore database | `FIRESTORE_DATABASE_ID` set to a database that does not exist in the project | Create it in the console, or clear the variable to use `(default)` |
| Firestore rules missing on a named database | `firebase.json` has no `"database"` field, so deploys target `(default)` | Add `"database": "<id>"` under `"firestore"` before `firebase deploy --only firestore:rules` |
| `403 awaiting approval` | Account is pending | Ask an Admin to approve via Super Admin → Pending Approvals |
| `422 Unprocessable Entity` | Missing required body field | Compare against `API_OVERVIEW.md` payloads |
| CORS errors in browser console | Origin not in `CORS_ORIGINS` | Add the exact frontend origin; restart backend |
| `400` from TrustedHost | Host not in `ALLOWED_HOSTS` | Include `localhost,127.0.0.1` (or the real domain in prod) |
| Uploads fail | Size cap, an extension outside the allowlist, or the compressed file exceeds 900 KB | Check `MAX_UPLOAD_SIZE_BYTES`, `ALLOWED_UPLOAD_EXTENSIONS`, and backend logs (non-prod includes the reason) |
| Draft returns placeholder text | Expected without `AI_API_URL` + `AI_API_KEY` | Set both (and `AI_MODEL`); otherwise the stub is the intended behaviour (ADR-004) |
| `400` "PDF output is no longer supported" | Documents are Word-only | Download the DOCX and export a PDF from a word processor |
| `400` on a PDF upload | Damaged, encrypted, or over 100 pages | Re-export the PDF without a password, or upload a DOCX |
| `413` naming a compression limit | The gzip blob cannot fit one Firestore document | Upload a smaller file or split it; the cap is ~900 KB compressed |
| `PERMISSION_DENIED: Missing or insufficient permissions` from a browser script | Expected — direct client access to Firestore is denied by design | Call the API instead; deploy the checked-in rules with `firebase deploy --only firestore:rules` |

## Frontend

| Symptom | Cause | Fix |
|---|---|---|
| Login screen shows a configuration banner | One or more `VITE_FIREBASE_*` values are empty | Fill `frontend/.env`, restart `npm run dev` |
| `auth/unauthorized-domain` after Google sign-in | Origin not registered in Firebase | Firebase console → Authentication → Authorized domains |
| Blank page after `npm run dev` | `VITE_API_URL` points at a dead backend, or `5173` clash | Confirm backend URL/ports; only the login screen works without a backend |
| `tsc` unused-var errors | `noUnusedLocals` / `noUnusedParameters` | Remove unused imports/vars; run `npx tsc -b` locally |
| `npm run lint` fails with "eslint: command not found" | No eslint config/deps committed yet | Expected — lint is advisory in CI until the eslint setup lands; don't work around it by installing globals |
| Stale API URL after `.env` edit | `VITE_*` bake at dev-server start / build time | Restart `npm run dev`, or rebuild the Docker image with a new `--build-arg` |

## Docker

| Symptom | Cause | Fix |
|---|---|---|
| Backend container runs but is unhealthy | `/health` returns `503` because Firebase credentials are missing/invalid | Mount `secrets/` and pass `--env-file backend/.env`; the container is serving, just not connected |
| Frontend shows wrong API URL | `VITE_API_URL` baked at build time | Rebuild with the correct `--build-arg`; runtime `-e` cannot change it |
| Build is slow (backend) | `pdf2docx` pulls in PyMuPDF, the largest wheel | Expected; use BuildKit layer caching (`docker.yml` uses GHA cache) |
| `docker compose up` port conflict | Another backend/frontend on `8000`/`5173` | Set `BACKEND_PORT` / `FRONTEND_PORT`; never stop unrelated containers to win a port |
| `gunicorn: command not found` on Windows | Gunicorn is POSIX-only | Use `uvicorn --reload` locally; run the Linux image in Docker |

## CI

| Symptom | Cause | Fix |
|---|---|---|
| Docker workflow fails at "Set up job" with `Unable to resolve action` | Pinned action repo renamed or mistyped (this bit us with `docker/build-action` vs `docker/build-push-action`) | Verify the action repo exists; keep pins in `dependabot.yml` scope |
| `backend` job fails on `app.main imports` | A missing dependency or an import that touches Firebase at module scope | Reproduce with `python -c "import app.main"`; keep Firebase init lazy |
| `docs-health` red | Missing community file, a secret-looking file in the tree, or a stale SQL reference in shipped code | Add the file, remove/rotate the secret, or follow ADR-005 |
| `frontend` build fails with empty `VITE_*` values | Should not happen — `lib/firebase.ts` reports configuration at runtime | Check for an import that throws during module evaluation |

Still stuck? See [`SUPPORT.md`](../SUPPORT.md) — include commit SHA, OS,
Python/Node versions, and redacted logs.
