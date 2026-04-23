from datetime import datetime, timezone
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

import models
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/api/water", tags=["water"])
log = logging.getLogger("compass.app")


class WaterLogRequest(BaseModel):
    amount_ml: int
    date: Optional[str] = None


@router.post("/log")
def log_water(
    body: WaterLogRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.amount_ml <= 0:
        raise HTTPException(status_code=422, detail="amount_ml must be positive")
    date = body.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    entry = models.WaterLog(user_id=current_user.id, date=date, amount_ml=body.amount_ml)
    db.add(entry)
    db.commit()
    db.refresh(entry)

    total = (
        db.query(func.sum(models.WaterLog.amount_ml))
        .filter(models.WaterLog.user_id == current_user.id, models.WaterLog.date == date)
        .scalar()
        or 0
    )
    goal = (current_user.settings.daily_water_goal_ml if current_user.settings else 2000)
    log.info(
        "water logged",
        extra={
            "event": "water_logged",
            "domain": "water",
            "log_id": entry.id,
            "date": date,
            "amount_ml": body.amount_ml,
            "total_ml": total,
            "goal_ml": goal,
            "goal_reached": total >= goal,
        },
    )
    return {"id": entry.id, "total_ml": total, "goal_ml": goal}


@router.delete("/log/{log_id}")
def delete_water_log(
    log_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = db.query(models.WaterLog).filter(
        models.WaterLog.id == log_id, models.WaterLog.user_id == current_user.id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Log not found")
    log.info(
        "water log deleted",
        extra={
            "event": "water_log_deleted",
            "domain": "water",
            "log_id": entry.id,
            "date": entry.date,
            "amount_ml": entry.amount_ml,
        },
    )
    db.delete(entry)
    db.commit()
    return {"message": "Deleted"}


@router.get("/today")
def get_water_today(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logs = (
        db.query(models.WaterLog)
        .filter(models.WaterLog.user_id == current_user.id, models.WaterLog.date == today)
        .order_by(models.WaterLog.logged_at)
        .all()
    )
    total = sum(l.amount_ml for l in logs)
    goal = (current_user.settings.daily_water_goal_ml if current_user.settings else 2000)
    pct = round(total / goal * 100, 1) if goal else 0
    return {
        "logs": [{"id": l.id, "amount_ml": l.amount_ml, "logged_at": l.logged_at.isoformat()} for l in logs],
        "total_ml": total,
        "goal_ml": goal,
        "percentage": pct,
    }


@router.get("/history")
def get_water_history(
    days: int = 7,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from datetime import timedelta
    today = datetime.now(timezone.utc)
    result = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        total = (
            db.query(func.sum(models.WaterLog.amount_ml))
            .filter(models.WaterLog.user_id == current_user.id, models.WaterLog.date == d)
            .scalar()
            or 0
        )
        result.append({"date": d, "total_ml": total})
    return result
