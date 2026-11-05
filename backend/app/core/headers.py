"""Security headers for every API response.

These mirror the headers nginx sets for the static frontend
(`frontend/nginx.conf`). HSTS is sent only in production: in local
development the API runs over plain HTTP, where the header is ignored.

The middleware is pure ASGI and sets headers on the response message itself,
so it works for responses FastAPI never sees: CORS preflights, the body
guard's 413, and `TrustedHostMiddleware`'s 400.

CSP is deliberately strict (`default-src 'none'`) because every API route
returns JSON or a file download. Swagger UI and ReDoc load their own assets
from a CDN, so those two documentation paths are exempted instead of
loosening the policy for the API.
"""
from app.core.config import settings

DEFAULT_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("Permissions-Policy", "geolocation=(), microphone=(), camera=()"),
)

# A JSON/download API should never be a document that executes script.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"

HSTS = "max-age=31536000; includeSubDomains"

DOCS_PREFIXES = ("/docs", "/redoc", "/openapi.json")


def _headers_for(path: str) -> tuple[tuple[str, str], ...]:
    headers = list(DEFAULT_HEADERS)
    if not path.startswith(DOCS_PREFIXES):
        headers.append(("Content-Security-Policy", API_CSP))
    if settings.environment == "production":
        headers.append(("Strict-Transport-Security", HSTS))
    return tuple(headers)


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers_for_path = _headers_for(scope.get("path", ""))

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                existing = {name.lower() for name, _ in message.get("headers", [])}
                headers = list(message.get("headers", []))
                for name, value in headers_for_path:
                    encoded_name = name.lower().encode("latin-1")
                    if encoded_name not in existing:
                        headers.append((encoded_name, value.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
