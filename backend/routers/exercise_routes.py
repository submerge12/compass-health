from datetime import datetime, timedelta, timezone
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

import models
from auth import get_current_user
from services.legacy_write_gate import reject_legacy_write
from database import get_db
from services import local_dates
from services.local_dates import date_or_422

router = APIRouter(prefix="/api/exercise", tags=["exercise"])
log = logging.getLogger("compass.app")


class ExerciseLogRequest(BaseModel):
    exercise_type: str = Field(..., min_length=1, max_length=64)
    duration_min: int = Field(..., gt=0, le=600)
    calories_burned: int = Field(..., ge=0, le=5000)
    notes: Optional[str] = Field(default=None, max_length=500)
    date: Optional[str] = Field(default=None, min_length=10, max_length=10)


@router.post("/log")
def log_exercise(
    body: ExerciseLogRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reject_legacy_write()
    date = date_or_422(body.date)
    entry = models.ExerciseLog(
        user_id=current_user.id,
        date=date,
        exercise_type=body.exercise_type,
        duration_min=body.duration_min,
        calories_burned=body.calories_burned,
        notes=body.notes,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    log.info(
        "exercise logged",
        extra={
            "event": "exercise_logged",
            "domain": "exercise",
            "log_id": entry.id,
            "date": date,
            "exercise_type": (body.exercise_type or "")[:64],
            "duration_min": body.duration_min,
            "calories_burned": body.calories_burned,
            "has_notes": bool(body.notes),
        },
    )
    return {"id": entry.id, "message": "Exercise logged"}


@router.delete("/log/{log_id}")
def delete_exercise_log(
    log_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reject_legacy_write()
    entry = db.query(models.ExerciseLog).filter(
        models.ExerciseLog.id == log_id, models.ExerciseLog.user_id == current_user.id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Log not found")
    log.info(
        "exercise log deleted",
        extra={
            "event": "exercise_log_deleted",
            "domain": "exercise",
            "log_id": entry.id,
            "date": entry.date,
            "exercise_type": (entry.exercise_type or "")[:64],
            "duration_min": entry.duration_min,
            "calories_burned": entry.calories_burned,
        },
    )
    db.delete(entry)
    db.commit()
    return {"message": "Deleted"}


@router.get("/today")
def get_exercise_today(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = local_dates.today_key()
    logs = (
        db.query(models.ExerciseLog)
        .filter(models.ExerciseLog.user_id == current_user.id, models.ExerciseLog.date == today)
        .order_by(models.ExerciseLog.logged_at)
        .all()
    )
    return {
        "logs": [
            {
                "id": l.id,
                "exercise_type": l.exercise_type,
                "duration_min": l.duration_min,
                "calories_burned": l.calories_burned,
                "notes": l.notes,
                "logged_at": l.logged_at.isoformat(),
            }
            for l in logs
        ],
        "total_calories": sum(l.calories_burned for l in logs),
        "total_minutes": sum(l.duration_min for l in logs),
    }


@router.get("/history")
def get_exercise_history(
    days: int = Query(7, ge=1, le=90),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = []
    for d in local_dates.date_range_ending_today(days):
        logs = (
            db.query(models.ExerciseLog)
            .filter(models.ExerciseLog.user_id == current_user.id, models.ExerciseLog.date == d)
            .all()
        )
        result.append({
            "date": d,
            "total_calories": sum(l.calories_burned for l in logs),
            "total_minutes": sum(l.duration_min for l in logs),
            "sessions": len(logs),
        })
    return result
