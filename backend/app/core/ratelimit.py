"""In-memory rate limiter for the auth endpoints that create or mutate users.

Single-instance deployment (ADR-003), so an in-memory sliding window is
acceptable. This is a capacity guard, not a security boundary: Firebase
verifies every token, so the goal is to stop one caller from hammering
Firestore, not to protect a password.

`scope["client"]` is the proxy address unless uvicorn is told which proxies to
trust. Behind Cloud Run or a load balancer, set `FORWARDED_ALLOW_IPS` so the
real client is used; otherwise every user shares one bucket. Session
endpoints (`/api/auth/me`, `/api/auth/logout`) are exempt because they run on
every page load, and a 429 there would sign an innocent user out. Multi-replica
deployments need a shared store (Redis) instead.
"""
import threading
import time
from collections import defaultdict, deque

from starlette.responses import JSONResponse

# Touched on every page load or sign-out; not a mutation surface.
DEFAULT_EXEMPT_PATHS = frozenset({"/api/auth/me", "/api/auth/logout"})

# Drop idle keys every N requests so a long-lived process cannot accumulate one
# deque per client address.
_SWEEP_EVERY = 1024


class RateLimitMiddleware:
    def __init__(
        self,
        app,
        *,
        limit: int = 60,
        window_seconds: int = 60,
        prefix: str = "/api/auth",
        exempt_paths: frozenset[str] = DEFAULT_EXEMPT_PATHS,
    ):
        if limit < 0:
            raise ValueError("limit must be >= 0")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.app = app
        self.limit = limit
        self.window = window_seconds
        self.prefix = prefix
        self.exempt_paths = exempt_paths
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._requests = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.limit <= 0:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith(self.prefix) or path in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        client = (scope.get("client") or ("unknown", 0))[0]
        now = time.monotonic()
        with self._lock:
            self._requests += 1
            if self._requests % _SWEEP_EVERY == 0:
                self._sweep(now)
            bucket = self._buckets[client]
            while bucket and bucket[0] <= now - self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry_after = int(self.window - (now - bucket[0])) + 1
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Try again later."},
                    headers={"Retry-After": str(retry_after)},
                )
                await response(scope, receive, send)
                return
            bucket.append(now)

        await self.app(scope, receive, send)

    def _sweep(self, now: float) -> None:
        """Forget clients whose window has expired. Caller holds the lock."""
        idle = [
            key
            for key, bucket in self._buckets.items()
            if not bucket or bucket[-1] <= now - self.window
        ]
        for key in idle:
            del self._buckets[key]
