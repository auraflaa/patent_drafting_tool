"""Lazy Firebase Admin initialization. Never store service-account keys in Git."""
import json
import os
from pathlib import Path
from typing import Any
import firebase_admin
from firebase_admin import credentials, firestore, auth
from app.core.config import settings

_app = None
_db = None

class FirebaseNotConfigured(RuntimeError):
    pass


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

def verify_id_token(token: str) -> dict:
    initialize_firebase()
    return auth.verify_id_token(token, app=_app, check_revoked=True)
