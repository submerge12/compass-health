"""M01: authenticated BFF routes proxying the Health Domain API.

The browser must not talk to the domain Display API (:8788) directly — that
path bypassed user isolation and cross-service tracing (plan §1.1, §7.1).
Every route here:

1. requires a valid FastAPI JWT (``get_current_user``);
2. derives ``X-External-User-ID`` from the *verified* user id — a client
   supplied ``X-External-User-ID`` header is ignored entirely;
3. propagates ``X-Request-ID`` / ``X-Journey-ID`` to the domain service;
4. returns ``503 domain_unavailable`` (with the request id) instead of ever
   falling back to writing SQLite.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from auth import get_current_user
from models import User
from services.domain_identity import external_id_for_user
from services.health_domain_client import (
    DomainUnavailableError,
    HealthDomainClient,
    domain_mode,
)

logger = logging.getLogger("compass.app")

router = APIRouter(prefix="/api/domain", tags=["health-domain-bff"])


def _client() -> HealthDomainClient:
    return HealthDomainClient()


@router.post("/{path:path}")
@router.get("/{path:path}")
async def proxy_domain(
    request: Request,
    path: str = "",
    user: User = Depends(get_current_user),
    client: HealthDomainClient = Depends(_client),
) -> Response:
    if domain_mode() != "postgres":
        return JSONResponse(
            status_code=503,
            content={
                "error": "domain_unavailable",
                "detail": "HEALTH_DOMAIN_MODE is not 'postgres'; start the domain API and enable the BFF.",
            },
        )

    body: Any = None
    if request.method == "POST":
        body = await request.json()

    try:
        downstream = await client.request(
            request.method,
            f"/api/{path}",
            external_user_id=external_id_for_user(user.id),
            params=dict(request.query_params),
            json_body=body,
        )
    except DomainUnavailableError:
        logger.warning("health domain unavailable for %s /api/%s", request.method, path)
        from logging_config import request_id_var

        return JSONResponse(
            status_code=503,
            content={
                "error": "domain_unavailable",
                "detail": "Health Domain API is not reachable; no fallback write is performed.",
                "request_id": request_id_var.get() or "",
            },
        )

    try:
        payload = downstream.json()
    except ValueError:
        payload = {"error": "invalid domain response"}
    return JSONResponse(status_code=downstream.status_code, content=payload)
