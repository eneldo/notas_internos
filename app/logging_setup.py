from __future__ import annotations

import logging
import os
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get("-")
        return True

def setup_json_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    root = logging.getLogger()
    root.setLevel(level)

    # clear handlers to avoid duplicates
    for h in list(root.handlers):
        root.removeHandler(h)

    try:
        from pythonjsonlogger import jsonlogger  # type: ignore
        handler = logging.StreamHandler(sys.stdout)
        fmt = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
            rename_fields={"levelname":"level","asctime":"ts","message":"msg"},
        )
        handler.setFormatter(fmt)
    except Exception:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s")
        handler.setFormatter(formatter)

    handler.addFilter(RequestIdFilter())
    root.addHandler(handler)

class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_ctx.set(rid)
        start = time.time()
        try:
            response = await call_next(request)
        finally:
            duration_ms = int((time.time() - start) * 1000)
            logger = logging.getLogger("app.access")
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": getattr(response, "status_code", 0),
                    "duration_ms": duration_ms,
                    "client": request.client.host if request.client else "",
                },
            )
            request_id_ctx.reset(token)
        response.headers["X-Request-ID"] = rid
        return response
