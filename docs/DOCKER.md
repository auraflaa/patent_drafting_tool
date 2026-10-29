# Docker guide

## 1. Images

| Image | Dockerfile | Base | Purpose |
|---|---|---|---|
| Backend | `backend/Dockerfile` | `python:3.13-slim` (builder + runtime) | FastAPI via Gunicorn + Uvicorn workers |
| Frontend | `frontend/Dockerfile` | `node:20-slim` → `nginx:1.27-alpine` | Vite build → static serve with SPA fallback |

Firebase (Auth and Firestore, which also stores the documents) is external to
both images. There is no database container, no bucket, and no migration step
(ADR-005, ADR-006).

## 2. Backend image details

Stages:

1. **builder**: creates `/opt/venv`, `pip install -r requirements.txt`.
2. **runtime**: installs `ca-certificates` only — no office suite, because
   documents are Word-only and PDF uploads are converted by `pdf2docx`.
   Creates non-root `appuser` (uid 1000), copies the venv + source,
   `USER appuser`.

```dockerfile
# No entrypoint: Firestore needs no migrations and there is no boot-time
# secret materialisation. Configuration comes from the environment exactly as
# pydantic-settings reads it. Gunicorn is in requirements.txt.
CMD ["gunicorn", "app.main:app",
     "--worker-class", "uvicorn.workers.UvicornWorker",
     "--workers", "2",
     "--bind", "0.0.0.0:8000",
     "--access-logfile", "-", "--error-logfile", "-", "--timeout", "120"]
```

- `EXPOSE 8000`; `HEALTHCHECK` hits `http://localhost:8000/health` (30 s
  interval, 15 s start period). The container stays **unhealthy** until
  Firebase credentials resolve, because `/health` returns `503` until then.
- Worker count is two on purpose: a PDF conversion or a large blob write
  occupies a worker for its duration, and the deployment assumes one backend
  replica (ADR-003).
- Env comes from `--env-file` or orchestrator variables (see
  `backend/.env.example`). The service-account JSON is mounted, not copied
  into the image.

Build + run:

```powershell
docker build -t patent-backend ./backend
docker run -p 8000:8000 --env-file backend/.env `
  -v "${PWD}/backend/secrets:/app/secrets:ro" patent-backend
```

Verify: `GET http://localhost:8000/health` → `200` once Firebase is reachable.

## 3. Frontend image details

Stages:

1. **build** (`node:20-slim`): `npm ci`, copy source, bake `VITE_API_URL` and
   the five `VITE_FIREBASE_*` values as build args, `npm run build` → `dist/`.
2. **serve** (`nginx:1.27-alpine`): copy `dist/` →
   `/usr/share/nginx/html`, copy `nginx.conf` →
   `/etc/nginx/conf.d/default.conf`.

- `EXPOSE 80`; `HEALTHCHECK` via `wget http://localhost/health`.
- `nginx.conf` provides the SPA fallback (all routes → `index.html`) plus
  caching/security headers.

Build + run:

```powershell
# Every VITE_* value is baked at build time — it cannot be changed at run time.
docker build `
  --build-arg VITE_API_URL=http://localhost:8000 `
  --build-arg VITE_FIREBASE_API_KEY=... `
  --build-arg VITE_FIREBASE_AUTH_DOMAIN=my-project.firebaseapp.com `
  --build-arg VITE_FIREBASE_PROJECT_ID=my-project `
  --build-arg VITE_FIREBASE_MESSAGING_SENDER_ID=... `
  --build-arg VITE_FIREBASE_APP_ID=... `
  -t patent-frontend ./frontend
docker run -p 8080:80 patent-frontend
```

Verify: open http://localhost:8080 → login page; confirm API calls hit the
baked URL (DevTools → Network). Missing Firebase values render a
configuration banner instead of the Google button.

## 4. Compose (local full stack)

`docker-compose.yml` services:

| Service | Image | Ports | Notes |
|---|---|---|---|
| `backend` | Built from `./backend` | `${BACKEND_PORT:-8000}:8000` | `env_file: ./backend/.env`; `/health` healthcheck; Firebase external |
| `frontend` | Built from `./frontend` | `${FRONTEND_PORT:-5173}:80` | Firebase + API URL passed as build args; `depends_on: backend` |

```powershell
# Export the Firebase Web SDK values first — they are build args.
$env:VITE_API_URL = "http://localhost:8000"
$env:VITE_FIREBASE_API_KEY = "..."
# ...
docker compose up --build
docker compose down
```

What to check:

- Backend logs show Gunicorn workers binding `0.0.0.0:8000`.
- `GET http://localhost:8000/health` → `200` with a real Firebase project.
- The frontend origin is registered under Firebase Authentication →
  Authorized domains (`localhost` is there by default).

There is no Postgres service, no `pgdata` volume, and no `DATABASE_URL`
override. Redis is absent until a job queue actually needs it.

## 5. Production notes

- Backend: expose `8000`, health check `GET /health`, **one replica** until
  document generation moves to a job queue (ADR-003). Set
  `ENVIRONMENT=production`, a real `CORS_ORIGINS`, and the real
  `ALLOWED_HOSTS` (see `DEPLOYMENT.md` §2).
- Frontend: pass the real backend URL and the real Firebase Web SDK values as
  build args; serve `dist/` statically or via the nginx image with an SPA
  rewrite.
- Never bake secrets into images — the service-account JSON is mounted or
  injected at run time, and `secrets/*.json` is excluded by `.dockerignore`
  and `.gitignore`.
- `gunicorn` does not run on Windows (`fcntl`); use the Linux image in
  production and `uvicorn --reload` for local development.
