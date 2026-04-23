"""
Per-user LLM call-quota enforcement.

Each LLM use-case has its own `kind` string and its own rolling-window cap.
Consumers call `check_and_consume(db, user_id, kind)` before invoking the
LLM; if the user is over their limit the function raises `LLMQuotaExceeded`
carrying the next-refresh timestamp so the caller can build a friendly
response.

Quotas are expressed as a number of calls allowed in a rolling window of N
days. The default for `RECIPE_SUGGEST` is 3 per rolling 7 days — consistent
with the product rule "at most three times per week."
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

import models


RECIPE_SUGGEST = "recipe_suggest"
POOL_NAME = "pool_name"


@dataclass(frozen=True)
class QuotaRule:
    limit: int
    window_days: int


QUOTAS: dict[str, QuotaRule] = {
    RECIPE_SUGGEST: QuotaRule(limit=3, window_days=7),
    POOL_NAME:      QuotaRule(limit=3, window_days=7),
}


class LLMQuotaExceeded(Exception):
    """User has exhausted their rolling-window budget for this LLM kind."""

    def __init__(self, kind: str, limit: int, used: int, next_refresh_at: datetime):
        self.kind = kind
        self.limit = limit
        self.used = used
        self.next_refresh_at = next_refresh_at
        super().__init__(
            f"quota exceeded for {kind}: used {used}/{limit}, next refresh at {next_refresh_at.isoformat()}"
        )


def _rule(kind: str) -> QuotaRule:
    rule = QUOTAS.get(kind)
    if rule is None:
        raise ValueError(f"unknown LLM quota kind: {kind}")
    return rule


def _window_start(rule: QuotaRule, now: datetime) -> datetime:
    return now - timedelta(days=rule.window_days)


def usage(db: Session, user_id: int, kind: str, *, now: datetime | None = None) -> dict:
    """Return {limit, used, remaining, next_refresh_at} for the user+kind.

    `next_refresh_at` is when the oldest in-window call ages out (i.e. when
    a new slot frees up). If used == 0 the field is None.
    """
    rule = _rule(kind)
    now = now or datetime.now(timezone.utc)
    start = _window_start(rule, now)

    rows = (
        db.query(models.LLMCallLog.called_at)
        .filter(
            models.LLMCallLog.user_id == user_id,
            models.LLMCallLog.kind == kind,
            models.LLMCallLog.called_at >= start,
        )
        .order_by(models.LLMCallLog.called_at.asc())
        .all()
    )
    used = len(rows)
    remaining = max(0, rule.limit - used)
    next_refresh: datetime | None = None
    if used > 0:
        oldest = rows[0][0]
        # Make naive datetimes tz-aware (SQLite round-trips strip tzinfo).
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        next_refresh = oldest + timedelta(days=rule.window_days)
    return {
        "limit": rule.limit,
        "used": used,
        "remaining": remaining,
        "window_days": rule.window_days,
        "next_refresh_at": next_refresh.isoformat() if next_refresh else None,
    }


def check(db: Session, user_id: int, kind: str) -> dict:
    """Return usage; raise LLMQuotaExceeded if already at cap."""
    u = usage(db, user_id, kind)
    if u["remaining"] <= 0:
        next_refresh = datetime.fromisoformat(u["next_refresh_at"]) if u["next_refresh_at"] else datetime.now(timezone.utc)
        raise LLMQuotaExceeded(kind, u["limit"], u["used"], next_refresh)
    return u


def consume(db: Session, user_id: int, kind: str) -> None:
    """Record an LLM call. Caller is responsible for committing the session."""
    _rule(kind)  # validate kind
    db.add(models.LLMCallLog(user_id=user_id, kind=kind))
    db.flush()


def check_and_consume(db: Session, user_id: int, kind: str) -> dict:
    """Raise if quota exceeded, else log the call and return fresh usage."""
    check(db, user_id, kind)
    consume(db, user_id, kind)
    return usage(db, user_id, kind)


def refund_latest(db: Session, user_id: int, kind: str) -> bool:
    """Delete the most recent in-window call for this user+kind.

    Intended for "charge at start, refund if the LLM returned nothing usable"
    semantics — callers MUST still commit the session. Returns True when a
    row was removed, False if there was nothing to refund.
    """
    _rule(kind)
    row = (
        db.query(models.LLMCallLog)
        .filter(
            models.LLMCallLog.user_id == user_id,
            models.LLMCallLog.kind == kind,
        )
        .order_by(models.LLMCallLog.called_at.desc())
        .first()
    )
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True
