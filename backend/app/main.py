import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from app.core.config import settings
from app.core.errors import UnhandledErrorMiddleware
from app.core.firebase import FirestoreUnavailable, firestore_ping, initialize_firebase
from app.core.headers import SecurityHeadersMiddleware
from app.core.limits import RequestBodyLimitMiddleware
from app.core.logging import RequestIDMiddleware, configure_logging
from app.core.ratelimit import RateLimitMiddleware
from app.api.auth import router as auth_router
from app.api.resources import router as resources_router

configure_logging()

logger = logging.getLogger(__name__)


def warn_insecure_hosts() -> None:
    """Warn when a production deployment accepts any Host header.

    `TrustedHostMiddleware` cannot defend against Host-header attacks when
    `ALLOWED_HOSTS=*`, and the permissive default is easy to ship by accident.
    """
    hosts = [
        value.strip()
        for value in settings.allowed_hosts.split(',')
        if value.strip()
    ]
    if settings.environment == 'production' and (not hosts or '*' in hosts):
        logger.warning(
            "ALLOWED_HOSTS accepts every Host header in production. Set it to "
            "the deployed API host(s) so Host-header attacks cannot reach the app."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    warn_insecure_hosts()
    # Keep startup usable before credentials are configured; /health reports setup status.
    try:
        initialize_firebase()
        app.state.firebase_ready = True
    except Exception as exc:
        app.state.firebase_ready = False
        app.state.firebase_error = str(exc)
    yield

app = FastAPI(title=settings.app_name, version='1.0.0', description='Firebase-backed Patent Platform API', lifespan=lifespan)
# add_middleware() prepends, so the last one added is the outermost layer.
# CORS goes near the end: it must wrap the 413 from the body guard, the 400
# from the host check, and every route response so the browser can read them.
# The body guard stays innermost so an oversized body is rejected before
# routing. Security headers wrap everything the app produces; the catch-all
# error handler sits inside CORS so even a 500 is readable. Request IDs are
# outermost so every response and log line can be correlated.
app.add_middleware(UnhandledErrorMiddleware, production=settings.environment == 'production')
app.add_middleware(RequestBodyLimitMiddleware)
app.add_middleware(RateLimitMiddleware, limit=settings.auth_rate_limit_per_minute)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=[x.strip() for x in settings.allowed_hosts.split(',') if x.strip()] or ['*'])
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in settings.cors_origins.split(',') if x.strip()],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
    expose_headers=['Content-Disposition', 'X-Request-ID'],
)
app.add_middleware(SecurityHeadersMiddleware)
# Outermost: every response (including the body guard's 413 and the host
# check's 400) carries an ID, and every app log line can be traced to a
# request.
app.add_middleware(RequestIDMiddleware)

@app.get('/', tags=['health'])
def root():
    return {'name': settings.app_name, 'version': '1.0.0', 'docs': '/docs', 'health': '/health'}

@app.get('/health', tags=['health'])
def health(request: Request):
    try:
        # Bounded and unretried: a wedged Firestore channel must not hold this
        # route for the SDK's five-minute default. A failed probe also recycles
        # the cached client, so the next real request opens a fresh channel.
        firestore_ping()
        return {'status': 'ok', 'firebase': 'connected', 'environment': settings.environment}
    except Exception as exc:
        return JSONResponse(status_code=503, content={'status': 'degraded', 'firebase': 'not_configured_or_unreachable', 'detail': str(exc) if settings.environment != 'production' else 'Firebase unavailable', 'environment': settings.environment})


@app.exception_handler(FirestoreUnavailable)
def firestore_unavailable(request: Request, exc: FirestoreUnavailable):
    """A datastore outage is retryable, not a broken server.

    500 tells the client nothing and reads as a bug; 503 tells it to try again,
    which the UI already renders as "try again shortly" instead of signing the
    user out.
    """
    logger.warning(
        "firestore_unavailable",
        extra={'path': request.url.path, 'error_type': type(exc).__name__},
    )
    return JSONResponse(
        status_code=503,
        content={
            'detail': 'The datastore is temporarily unreachable. Please try again.'
        },
    )

app.include_router(auth_router, prefix='/api/auth', tags=['Authentication'])
app.include_router(resources_router, prefix='/api', tags=['Patent Platform'])
