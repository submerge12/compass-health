from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from services import calorie, local_dates

router = APIRouter(prefix="/api/daily-activity", tags=["daily-activity"])


class ActivityUpsertRequest(BaseModel):
    activity_level: str = Field(..., min_length=1, max_length=50)
    # Optional — when omitted, the server picks the currently editable target
    # date (tomorrow if hour >= 19, today if hour < 8, else 422).
    date: Optional[str] = Field(default=None, min_length=10, max_length=10)


def _resolve_target_date(requested: Optional[str]) -> str:
    target = calorie.editable_target_date()
    if requested is None:
        if target is None:
            raise HTTPException(
                status_code=422,
                detail="Outside the activity edit window (7 PM prev day → 8 AM today).",
            )
        return target

    # A specific date was requested — enforce the window.
    if not calorie.is_in_edit_window(requested):
        raise HTTPException(
            status_code=422,
            detail=f"Date {requested} is outside the edit window (7 PM prev day → 8 AM today).",
        )
    return requested


@router.get("/today")
def get_today(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = calorie.today_utc_date()
    logged = calorie.get_activity_for_date(db, current_user.id, today)
    default = calorie.default_activity_for_user(db, current_user.id)
    return {
        "date": today,
        "activity_level": logged or default,
        "is_logged": logged is not None,
        "default_activity": default,
        "editable_target_date": calorie.editable_target_date(),
    }


@router.get("/default")
def get_default(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "activity_level": calorie.default_activity_for_user(db, current_user.id),
    }


@router.post("/today")
def upsert_today(
    body: ActivityUpsertRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.activity_level not in calorie.ACTIVITY_MULTIPLIERS:
        raise HTTPException(status_code=422, detail="Invalid activity_level")

    target_date = _resolve_target_date(body.date)

    rec = (
        db.query(models.DailyActivityPlan)
        .filter(
            models.DailyActivityPlan.user_id == current_user.id,
            models.DailyActivityPlan.date == target_date,
        )
        .first()
    )
    if rec:
        rec.activity_level = body.activity_level
        rec.logged_at = datetime.now(timezone.utc)
    else:
        rec = models.DailyActivityPlan(
            user_id=current_user.id,
            date=target_date,
            activity_level=body.activity_level,
        )
        db.add(rec)

    db.commit()
    return {"date": target_date, "activity_level": body.activity_level, "is_logged": True}


@router.get("/history")
def get_history(
    days: int = Query(7, ge=1, le=90),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cutoff = local_dates.date_range_ending_today(days + 1)[0]
    rows = (
        db.query(models.DailyActivityPlan)
        .filter(
            models.DailyActivityPlan.user_id == current_user.id,
            models.DailyActivityPlan.date >= cutoff,
        )
        .order_by(models.DailyActivityPlan.date.asc())
        .all()
    )
    return [
        {"date": r.date, "activity_level": r.activity_level, "logged_at": r.logged_at.isoformat() if r.logged_at else None}
        for r in rows
    ]
