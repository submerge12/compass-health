from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

from fastapi import HTTPException


INVALID_DATE_DETAIL = "date must be YYYY-MM-DD"


def _configured_timezone() -> timezone:
    raw = os.getenv("APP_TIMEZONE_OFFSET_HOURS", "8").strip()
    try:
        hours = float(raw)
    except ValueError:
        hours = 8.0
    return timezone(timedelta(hours=hours), name="APP_LOCAL")


APP_TZ = _configured_timezone()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def app_now(now: datetime | None = None) -> datetime:
    base = now or utc_now()
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base.astimezone(APP_TZ)


def today_key(now: datetime | None = None) -> str:
    return app_now(now).strftime("%Y-%m-%d")


def validate_date_key(raw: str) -> str:
    value = (raw or "").strip()
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(INVALID_DATE_DETAIL) from exc
    if parsed.strftime("%Y-%m-%d") != value:
        raise ValueError(INVALID_DATE_DETAIL)
    return value


def date_key_or_today(raw: str | None, now: datetime | None = None) -> str:
    if raw is None or str(raw).strip() == "":
        return today_key(now)
    return validate_date_key(str(raw))


def date_or_422(raw: str | None) -> str:
    try:
        return date_key_or_today(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def date_range_starting_today(days: int, now: datetime | None = None) -> list[str]:
    start = app_now(now)
    return [(start + timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(days)]


def date_range_ending_today(days: int, now: datetime | None = None) -> list[str]:
    end = app_now(now)
    return [(end - timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(days - 1, -1, -1)]
