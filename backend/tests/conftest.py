"""Test configuration.

These tests never touch a real Firebase project: credential environment
variables are forced empty before the app is imported, so the lifespan hook
records "Firebase not configured" instead of reaching for a service-account
file. Anything that needs live Firestore/Auth behaviour belongs in a manual
checklist, not here (see docs/DEVELOPMENT.md).
"""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Must be set before `app.core.config` is imported anywhere.
os.environ["FIREBASE_PROJECT_ID"] = ""
os.environ["FIREBASE_STORAGE_BUCKET"] = ""
os.environ["FIREBASE_EMULATOR_HOST"] = ""
os.environ["FIREBASE_SERVICE_ACCOUNT_PATH"] = str(
    BACKEND_ROOT / "secrets" / "does-not-exist.json"
)
os.environ["BOOTSTRAP_ADMIN_EMAIL"] = ""
os.environ["ENVIRONMENT"] = "test"
os.environ["AI_API_URL"] = ""
os.environ["AI_API_KEY"] = ""
os.environ["AI_MODEL"] = ""
os.environ["ALLOWED_HOSTS"] = "testserver,localhost,127.0.0.1"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)


@pytest.fixture(scope="session")
def client() -> TestClient:
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
