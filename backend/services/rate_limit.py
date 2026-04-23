"""
In-memory sliding-window rate limiter.

Used as a FastAPI dependency so a single endpoint can stack multiple
windows (e.g. 5/min AND 20/hour). Single-process only — if this app ever
scales to multiple workers, swap the backing store for Redis or similar.

Keys are `(bucket_name, client_ip)`. We honour `X-Forwarded-For` only when
`TRUST_PROXY=1` is set, because spoofing that header would otherwise let a
single attacker evade the limit trivially.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import HTTPException, Request, status

log = logging.getLogger("compass.auth")

_store: dict[tuple[str, str], Deque[float]] = defaultdict(deque)
_lock = threading.Lock()

_TRUST_PROXY = os.getenv("TRUST_PROXY", "0") == "1"


def _client_ip(request: Request) -> str:
    if _TRUST_PROXY:
        fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if fwd:
            return fwd
    return request.client.host if request.client else "unknown"


class RateLimit:
    """Sliding-window limiter. Raises 429 with Retry-After when tripped.

    Use `instance.check` as the FastAPI dependency — `check` is a plain
    bound method, which FastAPI introspects cleanly. Using the instance
    itself via `__call__` confuses FastAPI's param resolver (it treats
    the `request` arg as a query parameter)."""

    def __init__(self, rate: int, per_seconds: int, bucket: str):
        self.rate = rate
        self.per = per_seconds
        self.bucket = bucket

    def check(self, request: Request) -> None:
        ip = _client_ip(request)
        key = (self.bucket, ip)
        now = time.monotonic()
        cutoff = now - self.per

        with _lock:
            dq = _store[key]
            # Drop entries that have aged out of the window.
            while dq and dq[0] < cutoff:
                dq.popleft()

            if len(dq) >= self.rate:
                retry_after = max(1, int(self.per - (now - dq[0])) + 1)
                log.warning(
                    "rate limit hit",
                    extra={
                        "event": "rate_limit_hit",
                        "bucket": self.bucket,
                        "client_ip": ip,
                        "rate": self.rate,
                        "per_seconds": self.per,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many requests — try again in {retry_after}s",
                    headers={"Retry-After": str(retry_after)},
                )

            dq.append(now)
            # Keep the store from growing unboundedly when an IP goes quiet.
            if not dq:
                _store.pop(key, None)


def reset() -> None:
    """Test helper — clears all counters."""
    with _lock:
        _store.clear()
