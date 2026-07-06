from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

import models
from auth import get_current_user
from database import get_db
from services import engagement, local_dates

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/summary")
def get_stats_summary(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    uid = current_user.id

    # 7-day water average
    water_totals = []
    for d in reversed(local_dates.date_range_ending_today(7)):
        total = (
            db.query(func.sum(models.WaterLog.amount_ml))
            .filter(models.WaterLog.user_id == uid, models.WaterLog.date == d)
            .scalar()
            or 0
        )
        water_totals.append(total)
    water_avg = round(sum(water_totals) / 7)

    # 7-day exercise average calories
    ex_totals = []
    for d in reversed(local_dates.date_range_ending_today(7)):
        total = (
            db.query(func.sum(models.ExerciseLog.calories_burned))
            .filter(models.ExerciseLog.user_id == uid, models.ExerciseLog.date == d)
            .scalar()
            or 0
        )
        ex_totals.append(total)
    ex_avg = round(sum(ex_totals) / 7)

    # 7-day diet average calories
    diet_totals = []
    for d in reversed(local_dates.date_range_ending_today(7)):
        total = (
            db.query(func.sum(models.DietLog.calories))
            .filter(models.DietLog.user_id == uid, models.DietLog.date == d)
            .scalar()
            or 0
        )
        diet_totals.append(total)
    diet_avg = round(sum(diet_totals) / 7)

    # Weight trend (last 14 days with data)
    weight_records = (
        db.query(models.PhysicalCondition)
        .filter(
            models.PhysicalCondition.user_id == uid,
            models.PhysicalCondition.weight_kg.isnot(None),
        )
        .order_by(models.PhysicalCondition.date.desc())
        .limit(14)
        .all()
    )
    weight_trend = [
        {"date": r.date, "weight_kg": r.weight_kg}
        for r in reversed(weight_records)
    ]

    streak = engagement.calc_checkin_streak(db, uid)

    return {
        "water_7d_avg_ml": water_avg,
        "exercise_7d_avg_calories": ex_avg,
        "diet_7d_avg_calories": diet_avg,
        "weight_trend": weight_trend,
        "checkin_streak": streak,
    }


@router.get("/weekly")
def get_weekly_stats(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    uid = current_user.id
    result = []
    for d in local_dates.date_range_ending_today(7):

        water = (
            db.query(func.sum(models.WaterLog.amount_ml))
            .filter(models.WaterLog.user_id == uid, models.WaterLog.date == d)
            .scalar()
            or 0
        )
        ex_cal = (
            db.query(func.sum(models.ExerciseLog.calories_burned))
            .filter(models.ExerciseLog.user_id == uid, models.ExerciseLog.date == d)
            .scalar()
            or 0
        )
        diet_cal = (
            db.query(func.sum(models.DietLog.calories))
            .filter(models.DietLog.user_id == uid, models.DietLog.date == d)
            .scalar()
            or 0
        )
        result.append({
            "date": d,
            "water_ml": water,
            "exercise_calories": ex_cal,
            "diet_calories": diet_cal,
        })
    return result
