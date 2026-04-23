from datetime import datetime, timedelta, timezone
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

import models
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/api/condition", tags=["condition"])
log = logging.getLogger("compass.app")


class ConditionLogRequest(BaseModel):
    date: Optional[str] = None
    weight_kg: Optional[float] = None
    bp_systolic: Optional[int] = None
    bp_diastolic: Optional[int] = None
    heart_rate: Optional[int] = None
    sleep_hours: Optional[float] = None
    mood: Optional[int] = None     # 1-5
    notes: Optional[str] = None


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


@router.post("/log")
def log_condition(
    body: ConditionLogRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    date = body.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry = (
        db.query(models.PhysicalCondition)
        .filter(
            models.PhysicalCondition.user_id == current_user.id,
            models.PhysicalCondition.date == today,
        )
        .first()
    )
    return _serialize(entry) if entry else None


@router.get("/history")
def get_condition_history(
    days: int = 30,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = datetime.now(timezone.utc)
    start_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")
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
