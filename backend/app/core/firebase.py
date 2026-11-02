"""Lazy Firebase Admin initialization. Never store service-account keys in Git."""
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

import firebase_admin
from firebase_admin import credentials, firestore, auth
from google.api_core import exceptions as api_errors
from google.api_core import retry as api_retry

from app.core.config import settings

logger = logging.getLogger(__name__)

_app = None
_db = None
_db_lock = threading.Lock()

# Google stamps `iat`/`auth_time` with its own clock, so a workstation running
# even a second behind rejects a token minted a moment ago as "used too early".
# That reads as a dead session in the browser. Allow ordinary NTP-scale drift.
CLOCK_SKEW_SECONDS = 60

# Firestore's SDK retries for five minutes by default. When the gRPC channel is
# wedged (a network change leaves a half-dead socket, reported as `tcp
# handshaker shutdown`), that budget is spent inside the request: a worker
# thread blocks for the full five minutes and every API call behind it looks
# frozen. Bound both the single attempt and the retry loop, then recycle the
# cached client so the next attempt opens a fresh channel.
FIRESTORE_TIMEOUT_SECONDS = 8.0
FIRESTORE_RETRY_TIMEOUT_SECONDS = 8.0

FIRESTORE_RETRY = api_retry.Retry(
    predicate=api_retry.if_transient_error,
    initial=0.25,
    maximum=2.0,
    multiplier=2.0,
    timeout=FIRESTORE_RETRY_TIMEOUT_SECONDS,
)

# A broken transport, not a rejected security rule or a missing document.
# `RetryError` only appears here because FIRESTORE_RETRY retries transient
# errors; anything else is raised untouched.
TRANSPORT_ERRORS = (
    api_errors.ServiceUnavailable,
    api_errors.DeadlineExceeded,
    api_errors.Aborted,
    api_errors.InternalServerError,
    api_errors.RetryError,
)


class FirestoreUnavailable(RuntimeError):
    """Firestore could not be reached, so the operation did not complete.

    Raised instead of leaking a provider exception: the API answers 503, which
    tells the client to retry, rather than 500, which reads as a broken server.
    """


class FirebaseNotConfigured(RuntimeError):
    pass


class TokenUnverifiable(RuntimeError):
    """Firebase could not be reached, so a token's validity is unknown.

    Distinct from a rejected token: the caller answers 503 (retry later)
    instead of 401 (session is dead), so a network blip does not sign the
    user out of a perfectly good session.
    """


def _credentials_from_json(raw: str):
    """Parse inline service-account JSON, if configured."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FirebaseNotConfigured(
            'FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON.'
        ) from exc
    if not isinstance(info, dict):
        raise FirebaseNotConfigured(
            'FIREBASE_SERVICE_ACCOUNT_JSON must be a JSON object.'
        )
    try:
        return credentials.Certificate(info)
    except ValueError as exc:
        raise FirebaseNotConfigured(
            'FIREBASE_SERVICE_ACCOUNT_JSON is not a valid service-account certificate.'
        ) from exc


def initialize_firebase():
    global _app, _db
    if settings.firebase_emulator_host:
        os.environ['FIRESTORE_EMULATOR_HOST'] = settings.firebase_emulator_host
    if _app is None:
        try:
            _app = firebase_admin.get_app()
        except ValueError:
            key_path = Path(settings.firebase_service_account_path)
            options: dict[str, Any] = {}
            if settings.firebase_project_id:
                options['projectId'] = settings.firebase_project_id
            inline_credentials = _credentials_from_json(
                settings.firebase_service_account_json
            )
            if inline_credentials is not None:
                _app = firebase_admin.initialize_app(inline_credentials, options or None)
            elif key_path.is_file():
                _app = firebase_admin.initialize_app(credentials.Certificate(str(key_path)), options or None)
            elif settings.firebase_project_id:
                # Application Default Credentials are useful on supported hosts/emulators.
                _app = firebase_admin.initialize_app(options=options or None)
            else:
                raise FirebaseNotConfigured('Configure FIREBASE_PROJECT_ID and a service-account JSON path in .env.')
    # A failure above must not leave a half-initialised module: the next call
    # retries the missing client instead of returning None from db().
    if _db is None:
        _db = firestore.client(_app, database_id=settings.firestore_database_id or None)
    return _app

def db():
    if _db is None:
        initialize_firebase()
    return _db


def recycle_db(reason: str, error: Exception | None = None) -> None:
    """Drop the cached client so the next call opens a fresh gRPC channel.

    The dead client is detached rather than closed: other threads may still be
    inside a call on it, and closing the channel underneath them would replace
    their timed-out read with an unrelated cancellation. Only one failed
    request pays for the stale channel; the following one gets a new client.
    """
    global _db
    with _db_lock:
        if _db is None:
            return
        _db = None
    logger.warning(
        "firestore_client_recycled",
        extra={
            "reason": reason,
            "error_type": type(error).__name__ if error else None,
        },
    )


def firestore_read(operation):
    """Run a read, rebuilding it once against a fresh client on transport loss.

    `operation` must call `db()` itself instead of closing over references.
    A reference belongs to the client that created it, so replaying one after
    a recycle would keep talking to the dead channel.

    Reads are idempotent, so one transparent retry hides a client that went
    stale while the server sat idle (the long-uptime failure).
    """
    try:
        return operation()
    except TRANSPORT_ERRORS as exc:
        recycle_db("firestore_read", exc)
        try:
            return operation()
        except TRANSPORT_ERRORS as retry_exc:
            recycle_db("firestore_read_retry", retry_exc)
            raise FirestoreUnavailable(
                "Firestore is unreachable. Please retry."
            ) from retry_exc


def firestore_write(operation):
    """Run a write; recycle the client on transport loss but never replay it.

    A write that timed out may still have committed, so replaying it blindly
    could duplicate side effects (notifications, counters, activity rows).
    The caller gets a retryable 503 and the next attempt uses a fresh client.
    """
    try:
        return operation()
    except TRANSPORT_ERRORS as exc:
        recycle_db("firestore_write", exc)
        raise FirestoreUnavailable(
            "Firestore is unreachable. Please retry."
        ) from exc


def firestore_ping(timeout: float = 2.0) -> None:
    """Cheap liveness probe for `/health`, with no retry and a hard deadline.

    A failed probe also recycles the client, so simply asking the server how it
    is can heal it: the next real request builds a fresh channel.
    """
    try:
        db().collection("_health").limit(1).get(timeout=timeout, retry=None)
    except Exception as exc:
        recycle_db("firestore_ping", exc)
        raise


def verify_id_token(token: str) -> dict:
    initialize_firebase()
    try:
        return auth.verify_id_token(
            token,
            app=_app,
            check_revoked=True,
            clock_skew_seconds=CLOCK_SKEW_SECONDS,
        )
    except (auth.InvalidIdTokenError, auth.UserNotFoundError):
        # A real token problem: bad signature, expired, revoked, or the account
        # was deleted. The caller answers 401 and the browser signs out.
        raise
    except Exception as exc:
        # Everything else — DNS, TLS, Google returning 503, an unknown claim —
        # leaves the token's validity unknown. Reported as 503 (retry), never
        # as 401, so an outage cannot destroy a valid session.
        raise TokenUnverifiable(
            "Firebase could not be reached to verify the ID token."
        ) from exc
