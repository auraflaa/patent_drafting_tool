"""Structured application logs with a per-request correlation ID.

The app logger emits one JSON object per line so deployments can filter by
`event` and join every line from one request with `request_id`. Uvicorn's
access logger is left alone; this handler covers `app.*` only.

Metrics and distributed tracing need a collector/exporter that this
single-container deployment does not run, so the HTTP completion event
carries the rate/error/duration fields an operator needs until one is added.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone

from starlette.datastructures import Headers

REQUEST_ID_HEADER = "x-request-id"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

logger = logging.getLogger("app.http")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
            "request_id": getattr(record, "request_id", request_id_var.get()),
        }
        fields = getattr(record, "fields", None)
        if fields:
            payload.update(fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Attach the JSON handler once, without disturbing other loggers."""
    app_logger = logging.getLogger("app")
    if any(isinstance(handler.formatter, JsonFormatter) for handler in app_logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)
    app_logger.propagate = False


def log_event(
    target: logging.Logger,
    level: int,
    event: str,
    *,
    exc_info: bool = False,
    **fields,
) -> None:
    target.log(
        level,
        event,
        extra={"event": event, "fields": fields},
        exc_info=exc_info,
    )


class RequestIDMiddleware:
    """Accept a safe inbound request ID or mint one, then echo it back."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER)
        request_id = (
            incoming
            if incoming and _SAFE_REQUEST_ID.fullmatch(incoming)
            else uuid.uuid4().hex
        )
        token = request_id_var.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status_code = 500

        async def send_with_id(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                if not any(name.lower() == b"x-request-id" for name, _ in headers):
                    headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            log_event(
                logger,
                logging.INFO,
                "http_request",
                method=scope.get("method", ""),
                path=scope.get("path", ""),
                status=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            request_id_var.reset(token)
