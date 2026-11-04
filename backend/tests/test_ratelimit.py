"""Rate-limit middleware: the limit, the exemptions, and bucket pruning."""
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.ratelimit import RateLimitMiddleware


def _app(*, limit: int = 3, exempt_paths=frozenset({"/api/auth/me"})) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        limit=limit,
        window_seconds=60,
        exempt_paths=exempt_paths,
    )

    @app.post("/api/auth/sync")
    def sync() -> dict:
        return {"ok": True}

    @app.get("/api/auth/me")
    def me() -> dict:
        return {"ok": True}

    @app.get("/api/patents")
    def patents() -> dict:
        return {"ok": True}

    return app


def test_limit_trips_with_retry_after() -> None:
    client = TestClient(_app(limit=3))
    for _ in range(3):
        assert client.post("/api/auth/sync").status_code == 200
    blocked = client.post("/api/auth/sync")
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Too many requests. Try again later."
    assert int(blocked.headers["Retry-After"]) >= 1


def test_session_endpoints_are_exempt() -> None:
    client = TestClient(_app(limit=1))
    # A page load calls /me; limiting it would sign the user out for no reason.
    for _ in range(5):
        assert client.get("/api/auth/me").status_code == 200


def test_non_auth_paths_are_not_limited() -> None:
    client = TestClient(_app(limit=1))
    for _ in range(5):
        assert client.get("/api/patents").status_code == 200


def test_zero_disables_the_limiter() -> None:
    client = TestClient(_app(limit=0))
    for _ in range(10):
        assert client.post("/api/auth/sync").status_code == 200


def test_idle_buckets_are_swept() -> None:
    middleware = RateLimitMiddleware(lambda *args: None, limit=1, window_seconds=1)
    now = time.monotonic()
    middleware._buckets["stale"].append(now - 10)  # noqa: SLF001 - pruning is the behaviour under test
    middleware._buckets["active"].append(now)  # noqa: SLF001

    middleware._sweep(now)  # noqa: SLF001

    assert "stale" not in middleware._buckets  # noqa: SLF001
    assert "active" in middleware._buckets  # noqa: SLF001


def test_invalid_limit_is_rejected() -> None:
    with pytest.raises(ValueError):
        RateLimitMiddleware(lambda *args: None, limit=-1)
    with pytest.raises(ValueError):
        RateLimitMiddleware(lambda *args: None, window_seconds=0)


def _expensive_app(*, limit: int = 2) -> FastAPI:
    """Limiter covering two expensive prefixes with one per-IP budget."""
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        limit=limit,
        window_seconds=60,
        prefixes=("/api/patents", "/api/reports"),
        exempt_paths=frozenset({"/health"}),
    )

    @app.post("/api/patents/p1/draft/generate")
    def generate() -> dict:
        return {"ok": True}

    @app.get("/api/reports/dashboard")
    def dashboard() -> dict:
        return {"ok": True}

    @app.get("/api/teams")
    def teams() -> dict:
        return {"ok": True}

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    return app


def test_multiple_prefixes_share_one_per_ip_budget() -> None:
    client = TestClient(_expensive_app(limit=2))
    assert client.post("/api/patents/p1/draft/generate").status_code == 200
    assert client.post("/api/patents/p1/draft/generate").status_code == 200
    # The third expensive call trips the shared budget, even on the other prefix.
    blocked = client.get("/api/reports/dashboard")
    assert blocked.status_code == 429
    # Outside the covered prefixes nothing is limited.
    for _ in range(3):
        assert client.get("/api/teams").status_code == 200


def test_exempt_paths_bypass_the_multi_prefix_limiter() -> None:
    client = TestClient(_expensive_app(limit=1))
    assert client.post("/api/patents/p1/draft/generate").status_code == 200
    for _ in range(3):
        assert client.get("/health").status_code == 200
