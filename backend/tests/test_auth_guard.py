"""Auth-guard regressions: clock drift and unreachable-Firebase handling.

A token minted a second ahead of this machine used to be rejected as "used too
early", which the browser could only read as an expired session. A network
failure while fetching Firebase's keys used to do the same.
"""
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core import firebase as fb
from app.core import security


def _credentials() -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")


def test_verify_id_token_allows_clock_drift(monkeypatch):
    seen: dict = {}

    def fake_verify(token, app=None, check_revoked=False, clock_skew_seconds=0):
        seen.update(token=token, revoked=check_revoked, skew=clock_skew_seconds)
        return {"uid": "uid-1"}

    monkeypatch.setattr(fb, "initialize_firebase", lambda: None)
    monkeypatch.setattr(fb.auth, "verify_id_token", fake_verify)

    assert fb.verify_id_token("token") == {"uid": "uid-1"}
    assert seen["skew"] >= 30, "clock skew must be tolerated, not zero"
    assert seen["revoked"] is True, "revocation checks must stay on"


def test_verify_id_token_separates_network_failure(monkeypatch):
    def unreachable(*args, **kwargs):
        raise fb.auth.CertificateFetchError("keys unreachable", None)

    monkeypatch.setattr(fb, "initialize_firebase", lambda: None)
    monkeypatch.setattr(fb.auth, "verify_id_token", unreachable)

    with pytest.raises(fb.TokenUnverifiable):
        fb.verify_id_token("token")


def test_current_user_returns_401_for_a_bad_token(monkeypatch):
    def reject(token):
        raise fb.auth.InvalidIdTokenError("bad token")

    monkeypatch.setattr(security, "verify_id_token", reject)

    with pytest.raises(HTTPException) as raised:
        security.current_user(_credentials())

    assert raised.value.status_code == 401


def test_current_user_returns_503_when_firebase_is_unreachable(monkeypatch):
    def unreachable(token):
        raise fb.TokenUnverifiable("keys unreachable")

    monkeypatch.setattr(security, "verify_id_token", unreachable)

    with pytest.raises(HTTPException) as raised:
        security.current_user(_credentials())

    # 503 keeps the browser's session alive; 401 would sign the user out.
    assert raised.value.status_code == 503
