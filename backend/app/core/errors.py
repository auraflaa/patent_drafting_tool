"""Turn an unhandled exception into a normal API error response.

Starlette handles the `Exception` exception handler inside `ServerErrorMiddleware`,
which wraps *every* user middleware. A 500 produced there would carry neither
the CORS headers nor the security headers added further in, so the browser sees
an opaque CORS/network failure instead of the API's message.

This middleware sits inside CORS and converts the exception itself, keeping the
response shape the same as the one the old `@app.exception_handler(Exception)`
produced. The traceback still reaches the log, which is where it belongs.
"""
import logging

from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class UnhandledErrorMiddleware:
    def __init__(self, app, *, production: bool):
        self.app = app
        self.production = production

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            # Catch-all: turn any escaped error into a readable JSON 500.
            logger.exception(
                "Unhandled error on %s %s", scope.get("method"), scope.get("path")
            )
            if response_started:
                # Too late to replace a body that is already streaming.
                raise
            detail = (
                "Internal server error"
                if self.production
                else f"{type(exc).__name__}: {exc}"
            )
            response = JSONResponse(status_code=500, content={"detail": detail})
            await response(scope, receive, send)
