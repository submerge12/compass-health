"""
Request-context middleware.

Responsibilities, in order:
  1. Assign a request id, journey id, and UI action label (honouring
     inbound `X-Request-ID`, `X-Journey-ID`, and `X-UI-Action` if present).
  2. Best-effort extract the caller's user id from the JWT so every log
     line inside this request is correlated to a user, without duplicating
     the auth dependency.
  3. Time the request, emit a single structured access-log entry, and
     surface `X-Request-ID` to the caller so a user-reported issue maps
     straight to a log line.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from auth import decode_access_token
from logging_config import journey_id_var, request_id_var, ui_action_var, user_id_var

_access_logger = logging.getLogger("compass.access")


def _extract_user_id(request: Request) -> Optional[int]:
    """Pull user id from the bearer token without raising. Returns None for
    unauthenticated requests, expired tokens, or malformed headers — the
    goal is correlation, not authorization."""
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(None, 1)[1].strip()
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    sub = payload.get("sub")
    if sub is None:
        return None
    try:
        return int(sub)
    except (TypeError, ValueError):
        return None


def _sanitize_header(raw: Optional[str], *, max_len: int) -> Optional[str]:
    if not raw:
        return None
    value = " ".join(raw.split())
    if not value or len(value) > max_len:
        return None
    return value


class RequestContextMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        # Honour an inbound request id so log correlation works across hops
        # (reverse proxy, client-supplied id, etc.). Otherwise mint one.
        request_id = _sanitize_header(
            request.headers.get("x-request-id"),
            max_len=64,
        ) or uuid.uuid4().hex
        journey_id = _sanitize_header(
            request.headers.get("x-journey-id"),
            max_len=64,
        ) or request_id
        ui_action = _sanitize_header(
            request.headers.get("x-ui-action"),
            max_len=96,
        )

        rid_token = request_id_var.set(request_id)
        jid_token = journey_id_var.set(journey_id)
        action_token = ui_action_var.set(ui_action)
        uid_token = user_id_var.set(_extract_user_id(request))

        start = time.perf_counter()
        status_code = 500
        response: Optional[Response] = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            # Let FastAPI's exception handlers still run; just make sure
            # the access log captures the failure with a traceback.
            _access_logger.exception(
                "unhandled exception in request",
                extra={"path": request.url.path, "method": request.method},
            )
            raise
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)

            # Skip health-check noise — they run every few seconds from probes.
            path = request.url.path
            if path not in ("/", "/healthz", "/readyz"):
                level = logging.WARNING if status_code >= 500 else logging.INFO
                _access_logger.log(
                    level,
                    "%s %s %s %sms",
                    request.method,
                    path,
                    status_code,
                    duration_ms,
                    extra={
                        "method": request.method,
                        "path": path,
                        "status": status_code,
                        "duration_ms": duration_ms,
                        "client": request.client.host if request.client else "-",
                    },
                )

            if response is not None:
                response.headers["X-Request-ID"] = request_id
                response.headers["X-Journey-ID"] = journey_id

            request_id_var.reset(rid_token)
            journey_id_var.reset(jid_token)
            ui_action_var.reset(action_token)
            user_id_var.reset(uid_token)
