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
DIET_ESTIMATE = "diet_estimate"
PREFERENCE_CLASSIFY = "preference_classify"
ASSISTANT_CHAT = "assistant_chat"


@dataclass(frozen=True)
class QuotaRule:
    limit: int
    window_days: int


QUOTAS: dict[str, QuotaRule] = {
    RECIPE_SUGGEST: QuotaRule(limit=3, window_days=7),
    POOL_NAME:      QuotaRule(limit=3, window_days=7),
    DIET_ESTIMATE:  QuotaRule(limit=20, window_days=7),
    PREFERENCE_CLASSIFY: QuotaRule(limit=10, window_days=7),
    ASSISTANT_CHAT: QuotaRule(limit=100, window_days=7),
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


def consume(db: Session, user_id: int, kind: str, *, now: datetime | None = None) -> int:
    """Record an LLM call and return its row id.

    Caller is responsible for committing the session.
    """
    _rule(kind)  # validate kind
    row = models.LLMCallLog(user_id=user_id, kind=kind)
    if now is not None:
        row.called_at = now
    db.add(row)
    db.flush()
    return int(row.id)


def check_and_consume(db: Session, user_id: int, kind: str) -> dict:
    """Raise if quota exceeded, else log the call and return fresh usage.

    The returned dict includes `call_log_id`, which callers should keep if
    they need to refund this exact charge later.
    """
    rule = _rule(kind)
    now = datetime.now(timezone.utc)

    # On databases that support row locks, this serializes quota changes for a
    # user. SQLite ignores FOR UPDATE, but the insert below still holds a write
    # lock for the duration of the transaction.
    db.query(models.User.id).filter(models.User.id == user_id).with_for_update().first()

    call_log_id = consume(db, user_id, kind, now=now)
    current = usage(db, user_id, kind, now=now)
    if current["used"] > rule.limit:
        refund_call(db, call_log_id, user_id=user_id, kind=kind)
        refreshed = usage(db, user_id, kind, now=now)
        next_refresh = (
            datetime.fromisoformat(refreshed["next_refresh_at"])
            if refreshed["next_refresh_at"]
            else now
        )
        raise LLMQuotaExceeded(kind, rule.limit, refreshed["used"], next_refresh)
    current["call_log_id"] = call_log_id
    return current


def refund_call(
    db: Session,
    call_log_id: int | None,
    *,
    user_id: int | None = None,
    kind: str | None = None,
) -> bool:
    """Delete one specific quota charge.

    Returns True when a matching row was removed. Optional user/kind guards
    prevent refunding the wrong row if stale ids are ever passed around.
    """
    if call_log_id is None:
        return False
    query = db.query(models.LLMCallLog).filter(models.LLMCallLog.id == call_log_id)
    if user_id is not None:
        query = query.filter(models.LLMCallLog.user_id == user_id)
    if kind is not None:
        _rule(kind)
        query = query.filter(models.LLMCallLog.kind == kind)
    row = query.first()
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True


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
