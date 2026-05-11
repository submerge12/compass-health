from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from services import local_dates, weight_tracking

router = APIRouter(prefix="/api/condition", tags=["condition"])
log = logging.getLogger("compass.app")


class ConditionLogRequest(BaseModel):
    date: Optional[str] = Field(default=None, min_length=10, max_length=10)
    weight_kg: Optional[float] = Field(default=None, ge=20, le=300)
    bp_systolic: Optional[int] = Field(default=None, ge=50, le=250)
    bp_diastolic: Optional[int] = Field(default=None, ge=30, le=160)
    heart_rate: Optional[int] = Field(default=None, ge=20, le=240)
    sleep_hours: Optional[float] = Field(default=None, ge=0, le=24)
    mood: Optional[int] = Field(default=None, ge=1, le=5)
    notes: Optional[str] = Field(default=None, max_length=500)


def _date_or_422(raw: Optional[str]) -> str:
    try:
        return local_dates.date_key_or_today(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _present_fields(body: ConditionLogRequest) -> list[str]:
    fields = []
    for field in (
        "weight_kg",
        "bp_systolic",
        "bp_diastolic",
        "heart_rate",
        "sleep_hours",
        "mood",
    ):
        if getattr(body, field) is not None:
            fields.append(field)
    if body.notes is not None:
        fields.append("notes")
    return fields


def _serialize(c: models.PhysicalCondition) -> dict:
    return {
        "id": c.id,
        "date": c.date,
        "weight_kg": c.weight_kg,
        "bp_systolic": c.bp_systolic,
        "bp_diastolic": c.bp_diastolic,
        "heart_rate": c.heart_rate,
        "sleep_hours": c.sleep_hours,
        "mood": c.mood,
        "notes": c.notes,
        "logged_at": c.logged_at.isoformat() if c.logged_at else None,
    }


def _empty_today_payload(date: str) -> dict:
    return {
        "id": None,
        "date": date,
        "weight_kg": None,
        "bp_systolic": None,
        "bp_diastolic": None,
        "heart_rate": None,
        "sleep_hours": None,
        "mood": None,
        "notes": None,
        "logged_at": None,
    }


def _attach_latest_weight(payload: dict, snapshot: dict | None) -> dict:
    current_weight = payload.get("weight_kg")
    payload["latest_weight_kg"] = snapshot["weight_kg"] if snapshot else None
    payload["latest_weight_date"] = snapshot["date"] if snapshot else None
    payload["latest_weight_logged_at"] = snapshot["logged_at"] if snapshot else None
    payload["latest_weight_source"] = snapshot["source"] if snapshot else None
    payload["weight_is_latest_fallback"] = False

    profile_has_newer_weight = (
        snapshot
        and current_weight is not None
        and snapshot.get("source") == "profile"
        and snapshot.get("weight_kg") != current_weight
        and (
            snapshot.get("date") or "",
            snapshot.get("logged_at") or "",
        ) > (
            payload.get("date") or "",
            payload.get("logged_at") or "",
        )
    )

    if (current_weight is None and snapshot) or profile_has_newer_weight:
        payload["weight_kg"] = snapshot["weight_kg"]
        payload["weight_date"] = snapshot["date"]
        payload["weight_is_latest_fallback"] = True
    elif current_weight is not None:
        payload["weight_date"] = payload.get("date")

    return payload


@router.post("/log")
def log_condition(
    body: ConditionLogRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    date = _date_or_422(body.date)
    present_fields = _present_fields(body)

    # Upsert: update if exists, insert if not
    existing = (
        db.query(models.PhysicalCondition)
        .filter(
            models.PhysicalCondition.user_id == current_user.id,
            models.PhysicalCondition.date == date,
        )
        .first()
    )

    if existing:
        if body.weight_kg is not None:
            existing.weight_kg = body.weight_kg
        if body.bp_systolic is not None:
            existing.bp_systolic = body.bp_systolic
        if body.bp_diastolic is not None:
            existing.bp_diastolic = body.bp_diastolic
        if body.heart_rate is not None:
            existing.heart_rate = body.heart_rate
        if body.sleep_hours is not None:
            existing.sleep_hours = body.sleep_hours
        if body.mood is not None:
            existing.mood = body.mood
        if body.notes is not None:
            existing.notes = body.notes
        existing.logged_at = datetime.now(timezone.utc)
        if body.weight_kg is not None and date == weight_tracking.today_key():
            weight_tracking.sync_profile_weight(db, current_user, body.weight_kg)
        db.commit()
        db.refresh(existing)
        log.info(
            "condition updated",
            extra={
                "event": "condition_logged",
                "domain": "condition",
                "log_id": existing.id,
                "date": date,
                "updated_existing": True,
                "fields": present_fields,
            },
        )
        return _serialize(existing)

    entry = models.PhysicalCondition(
        user_id=current_user.id,
        date=date,
        weight_kg=body.weight_kg,
        bp_systolic=body.bp_systolic,
        bp_diastolic=body.bp_diastolic,
        heart_rate=body.heart_rate,
        sleep_hours=body.sleep_hours,
        mood=body.mood,
        notes=body.notes,
    )
    db.add(entry)
    if body.weight_kg is not None and date == weight_tracking.today_key():
        weight_tracking.sync_profile_weight(db, current_user, body.weight_kg)
    db.commit()
    db.refresh(entry)
    log.info(
        "condition logged",
        extra={
            "event": "condition_logged",
            "domain": "condition",
            "log_id": entry.id,
            "date": date,
            "updated_existing": False,
            "fields": present_fields,
        },
    )
    return _serialize(entry)


@router.get("/today")
def get_condition_today(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = weight_tracking.today_key()
    entry = (
        db.query(models.PhysicalCondition)
        .filter(
            models.PhysicalCondition.user_id == current_user.id,
            models.PhysicalCondition.date == today,
        )
        .first()
    )
    snapshot = weight_tracking.latest_weight_snapshot(db, current_user)
    if not entry and not snapshot:
        return None

    payload = _serialize(entry) if entry else _empty_today_payload(today)
    return _attach_latest_weight(payload, snapshot)


@router.get("/history")
def get_condition_history(
    days: int = Query(30, ge=1, le=90),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start_date = local_dates.date_range_ending_today(days + 1)[0]
    entries = (
        db.query(models.PhysicalCondition)
        .filter(
            models.PhysicalCondition.user_id == current_user.id,
            models.PhysicalCondition.date >= start_date,
        )
        .order_by(models.PhysicalCondition.date)
        .all()
    )
    return [_serialize(e) for e in entries]
