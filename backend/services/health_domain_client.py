"""M01: HTTP client for the private Health Domain API (Display API :8788).

Only the FastAPI BFF talks to this service; the browser never does. The client
attaches the service token plus the per-request identity and trace headers:

- ``Authorization: Bearer <HEALTH_DOMAIN_TOKEN>``  — service auth
- ``X-External-User-ID``                          — derived from the JWT user,
  never accepted from the browser
- ``X-Request-ID`` / ``X-Journey-ID``             — propagated from the inbound
  request so one journey stays traceable across BFF → domain → PostgreSQL.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import httpx

from logging_config import journey_id_var, request_id_var

DEFAULT_DOMAIN_URL = "http://127.0.0.1:8788"


class DomainUnavailableError(Exception):
    """The Health Domain API could not be reached in time."""


def domain_mode() -> str:
    """``postgres`` proxies through the domain API; ``off`` disables the BFF."""
    return os.environ.get("HEALTH_DOMAIN_MODE", "postgres").strip().lower()


class HealthDomainClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout_seconds: float = 10.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._base_url = (base_url or os.environ.get("HEALTH_DOMAIN_URL") or DEFAULT_DOMAIN_URL).rstrip("/")
        self._token = token if token is not None else os.environ.get("HEALTH_DOMAIN_TOKEN", "")
        self._timeout = timeout_seconds
        self._transport = transport

    @property
    def base_url(self) -> str:
        return self._base_url

    async def request(
        self,
        method: str,
        path: str,
        *,
        external_user_id: str,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[Any] = None,
        actor: str = "web",
    ) -> httpx.Response:
        headers = {
            "X-External-User-ID": external_user_id,
            "X-Request-ID": request_id_var.get() or "",
            "X-Journey-ID": journey_id_var.get() or "",
            # WO-HS-02: caller class for receipts; derived from the route, not
            # the browser.
            "X-Actor": actor,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        async with httpx.AsyncClient(
            base_url=self._base_url,
            transport=self._transport,
            timeout=self._timeout,
            headers=headers,
            # The domain API is a private local service; a system proxy must
            # never sit in the middle (breaks 127.0.0.1 calls on proxied hosts).
            trust_env=False,
        ) as client:
            try:
                return await client.request(
                    method,
                    path,
                    params={k: v for k, v in (params or {}).items() if v is not None},
                    content=None if json_body is None else json.dumps(json_body).encode("utf-8"),
                )
            except httpx.HTTPError as exc:
                raise DomainUnavailableError(str(exc)) from exc
