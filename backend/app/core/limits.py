"""Request-size enforcement shared by middleware and upload handlers.

Vercel rejects request bodies above 4.5 MB before the app sees them, so the
app has to stay below that on its own. `Settings.upload_limit_bytes` carries
the effective per-file limit; this module turns it into HTTP responses and
guards request bodies early.
"""
import json

from starlette.datastructures import Headers

from app.core.config import MIB, settings

BODY_METHODS = {"POST", "PUT", "PATCH"}


def human_size(size: int) -> str:
    if size >= MIB:
        if size % MIB == 0:
            return f"{size // MIB} MB"
        return f"{size / MIB:.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def upload_limit_detail() -> str:
    return (
        "Files are limited to "
        f"{human_size(settings.upload_limit_bytes)} on this deployment."
    )


def request_body_limit_detail() -> str:
    return (
        "Request body is too large. This deployment accepts uploads up to "
        f"{human_size(settings.upload_limit_bytes)}."
    )


async def _reject(send) -> None:
    body = json.dumps({"detail": request_body_limit_detail()}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RequestBodyLimitMiddleware:
    """Reject oversized bodies before the route buffers them.

    `Content-Length` is checked first. Bodies without a usable length are
    buffered up to the limit and replayed to the app, so a chunked request
    cannot bypass the cap. The buffer is bounded by the limit plus one ASGI
    chunk, and this app already buffers uploads in `_read_upload`.

    Per-file size is still validated there because multipart overhead is not
    part of the file limit.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in BODY_METHODS:
            await self.app(scope, receive, send)
            return

        limit = settings.request_body_limit_bytes
        declared = Headers(scope=scope).get("content-length")
        if declared:
            try:
                if int(declared) > limit:
                    await _reject(send)
                    return
            except ValueError:
                # A malformed Content-Length is not a length we can trust.
                # Fall through to the byte-counting guard below instead of
                # rejecting, so a broken header cannot deny a valid request.
                pass

        messages = []
        received = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            received += len(message.get("body", b""))
            if received > limit:
                await _reject(send)
                return
            messages.append(message)
            if not message.get("more_body", False):
                break

        index = 0

        async def replay_receive():
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return await receive()

        await self.app(scope, replay_receive, send)
