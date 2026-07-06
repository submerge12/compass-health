from datetime import datetime, timedelta, timezone
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from services import calorie, engagement, local_dates, weight_tracking

router = APIRouter(prefix="/api/users", tags=["users"])
log = logging.getLogger("compass.app")


# ── Schemas ───────────────────────────────────────────────────────────────────

class BMRRequest(BaseModel):
    age: int = Field(..., ge=13, le=120)
    gender: str = Field(..., min_length=1, max_length=20)            # "male" / "female"
    height_cm: float = Field(..., ge=80, le=250)
    weight_kg: float = Field(..., ge=30, le=300)
    goal: str = Field(..., min_length=1, max_length=40)              # see services.calorie.GOALS


class TargetWeightRequest(BaseModel):
    target_weight_kg: Optional[float] = Field(default=None, ge=20, le=300)


class WeightUpdateRequest(BaseModel):
    weight_kg: float = Field(..., ge=30, le=300)


class ActivityLevelRequest(BaseModel):
    activity_level: str = Field(..., min_length=1, max_length=50)


class SettingsRequest(BaseModel):
    daily_water_goal_ml: Optional[int] = Field(default=None, ge=250, le=10000)
    water_reminder_min: Optional[int] = Field(default=None, ge=0, le=1440)
    language: Optional[str] = Field(default=None, min_length=2, max_length=10)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/me")
def get_me(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    streak = engagement.calc_checkin_streak(db, current_user.id)
    mem_level = current_user.membership.level if current_user.membership else "free"
    today = local_dates.today_key()
    checked_in_today = (
        db.query(models.CheckIn)
        .filter(models.CheckIn.user_id == current_user.id, models.CheckIn.date == today)
        .first()
    ) is not None
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "language": current_user.language,
        "membership_level": mem_level,
        "checkin_streak": streak,
        "checked_in_today": checked_in_today,
        "is_admin": bool(current_user.is_admin),
        "target_weight_kg": current_user.target_weight_kg,
        "has_bmr_profile": current_user.bmr_profile is not None,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }


@router.get("/bmr")
def get_bmr(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.bmr_profile:
        raise HTTPException(status_code=404, detail="BMR profile not found")
    p = current_user.bmr_profile
    targets = calorie.build_daily_targets(db, current_user)
    return {
        "age": p.age,
        "gender": p.gender,
        "height_cm": p.height_cm,
        "weight_kg": p.weight_kg,
        "goal": calorie.normalize_goal(p.goal),
        "bmr_value": round(targets["bmr"], 1) if targets.get("bmr") else p.bmr_value,
        "tdee_value": round(targets["tdee"], 1) if targets.get("tdee") else None,
        "activity_level": targets.get("activity_level"),
        "profile_activity_level": p.activity_level or calorie.DEFAULT_ACTIVITY,
        "activity_is_default": targets.get("activity_is_default"),
        "daily_targets": targets,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.post("/bmr", status_code=status.HTTP_200_OK)
def save_bmr(
    body: BMRRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    goal = calorie.normalize_goal(body.goal)
    if goal not in calorie.GOALS:
        raise HTTPException(status_code=422, detail="Invalid goal")
    if body.gender not in ("male", "female"):
        raise HTTPException(status_code=422, detail="Gender must be 'male' or 'female'")

    bmr_val = round(calorie.compute_bmr(body.age, body.gender, body.height_cm, body.weight_kg), 1)

    profile = current_user.bmr_profile
    created_profile = profile is None
    if profile:
        profile.age = body.age
        profile.gender = body.gender
        profile.height_cm = body.height_cm
        profile.weight_kg = body.weight_kg
        profile.goal = goal
        profile.bmr_value = bmr_val
        profile.tdee_value = 0.0  # legacy column — TDEE is computed dynamically
        profile.updated_at = datetime.now(timezone.utc)
    else:
        profile = models.BMRProfile(
            user_id=current_user.id,
            age=body.age,
            gender=body.gender,
            height_cm=body.height_cm,
            weight_kg=body.weight_kg,
            # activity_level is legacy; placeholder keeps NOT NULL on old DBs happy.
            activity_level=calorie.DEFAULT_ACTIVITY,
            goal=goal,
            bmr_value=bmr_val,
            tdee_value=0.0,
        )
        db.add(profile)

    weight_tracking.upsert_condition_weight(db, current_user.id, body.weight_kg)
    db.commit()
    db.refresh(current_user)

    # Seed tomorrow's activity with the default if it's within the edit window,
    # so TDEE has a value to work with immediately after onboarding.
    target_date = calorie.editable_target_date()
    seeded_default_activity = False
    if target_date and not calorie.get_activity_for_date(db, current_user.id, target_date):
        db.add(models.DailyActivityPlan(
            user_id=current_user.id,
            date=target_date,
            activity_level=calorie.DEFAULT_ACTIVITY,
        ))
        db.commit()
        seeded_default_activity = True

    targets = calorie.build_daily_targets(db, current_user)
    log.info(
        "bmr profile saved",
        extra={
            "event": "bmr_saved",
            "domain": "users",
            "goal": goal,
            "created_profile": created_profile,
            "seeded_default_activity": seeded_default_activity,
            "has_bmr_profile": True,
        },
    )
    return {
        "bmr_value": bmr_val,
        "tdee_value": targets.get("tdee"),
        "calorie_target": targets.get("calorie_target"),
        "daily_targets": targets,
        "message": "BMR profile saved",
    }


@router.patch("/me/weight")
def update_weight(
    body: WeightUpdateRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.weight_kg < 30 or body.weight_kg > 300:
        raise HTTPException(status_code=422, detail="weight_kg must be between 30 and 300")
    profile = current_user.bmr_profile
    if not profile:
        raise HTTPException(status_code=404, detail="BMR profile not found")

    profile.weight_kg = body.weight_kg
    profile.bmr_value = round(
        calorie.compute_bmr(profile.age, profile.gender, profile.height_cm, body.weight_kg),
        1,
    )
    profile.updated_at = datetime.now(timezone.utc)
    weight_tracking.upsert_condition_weight(db, current_user.id, body.weight_kg)
    db.commit()
    db.refresh(current_user)

    targets = calorie.build_daily_targets(db, current_user)
    log.info(
        "weight updated",
        extra={
            "event": "weight_updated",
            "domain": "users",
            "has_bmr_profile": True,
        },
    )
    return {
        "weight_kg": profile.weight_kg,
        "bmr_value": profile.bmr_value,
        "tdee_value": targets.get("tdee"),
        "calorie_target": targets.get("calorie_target"),
    }


@router.patch("/me/activity-level")
def update_activity_level(
    body: ActivityLevelRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.activity_level not in calorie.ACTIVITY_MULTIPLIERS:
        raise HTTPException(status_code=422, detail="Invalid activity_level")
    profile = current_user.bmr_profile
    if not profile:
        raise HTTPException(status_code=404, detail="BMR profile not found")

    profile.activity_level = body.activity_level
    profile.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(current_user)

    targets = calorie.build_daily_targets(db, current_user)
    log.info(
        "default activity level updated",
        extra={
            "event": "activity_level_updated",
            "domain": "users",
            "activity_level": body.activity_level,
            "has_bmr_profile": True,
        },
    )
    return {
        "activity_level": profile.activity_level,
        "tdee_value": targets.get("tdee"),
        "calorie_target": targets.get("calorie_target"),
        "daily_targets": targets,
    }


@router.patch("/me/target-weight")
def update_target_weight(
    body: TargetWeightRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.target_weight_kg is not None:
        if body.target_weight_kg < 20 or body.target_weight_kg > 300:
            raise HTTPException(status_code=422, detail="target_weight_kg must be between 20 and 300")
    current_user.target_weight_kg = body.target_weight_kg
    db.commit()
    log.info(
        "target weight updated",
        extra={
            "event": "target_weight_updated",
            "domain": "users",
            "cleared": body.target_weight_kg is None,
        },
    )
    return {"target_weight_kg": current_user.target_weight_kg}


@router.post("/checkin")
def check_in(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = local_dates.today_key()
    existing = (
        db.query(models.CheckIn)
        .filter(models.CheckIn.user_id == current_user.id, models.CheckIn.date == today)
        .first()
    )
    if existing:
        streak = engagement.calc_checkin_streak(db, current_user.id)
        mem_level = current_user.membership.level if current_user.membership else "free"
        log.info(
            "check-in ignored because it already exists",
            extra={
                "event": "checkin_duplicate",
                "domain": "users",
                "date": today,
                "streak": streak,
                "membership_level": mem_level,
            },
        )
        return {"streak": streak, "membership_level": mem_level, "already_checked_in": True}

    db.add(models.CheckIn(user_id=current_user.id, date=today))
    db.commit()
    db.refresh(current_user)

    streak = engagement.calc_checkin_streak(db, current_user.id)

    # Upgrade free → normal after 7 consecutive days
    mem = current_user.membership
    upgraded_membership = False
    if mem and mem.level == "free" and streak >= 7:
        mem.level = "normal"
        mem.start_date = datetime.now(timezone.utc)
        db.commit()
        upgraded_membership = True

    mem_level = current_user.membership.level if current_user.membership else "free"
    log.info(
        "check-in completed",
        extra={
            "event": "checkin_logged",
            "domain": "users",
            "date": today,
            "streak": streak,
            "membership_level": mem_level,
            "membership_upgraded": upgraded_membership,
        },
    )
    return {"streak": streak, "membership_level": mem_level, "already_checked_in": False}


@router.get("/checkin/streak")
def get_streak(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    streak = engagement.calc_checkin_streak(db, current_user.id)
    today = local_dates.app_now()
    checkins = {
        c.date
        for c in db.query(models.CheckIn).filter(
            models.CheckIn.user_id == current_user.id
        ).all()
    }
    last_7 = []
    for i in range(6, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        last_7.append({"date": d, "checked_in": d in checkins})
    return {"streak": streak, "last_7_days": last_7}


@router.get("/settings")
def get_settings(
    current_user: models.User = Depends(get_current_user),
):
    s = current_user.settings
    if not s:
        return {"daily_water_goal_ml": 2000, "water_reminder_min": 60, "language": "zh"}
    return {
        "daily_water_goal_ml": s.daily_water_goal_ml,
        "water_reminder_min": s.water_reminder_min,
        "language": s.language,
    }


@router.put("/settings")
def update_settings(
    body: SettingsRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = current_user.settings
    changed_keys = []
    if not s:
        s = models.UserSettings(user_id=current_user.id)
        db.add(s)

    if body.daily_water_goal_ml is not None:
        s.daily_water_goal_ml = body.daily_water_goal_ml
        changed_keys.append("daily_water_goal_ml")
    if body.water_reminder_min is not None:
        s.water_reminder_min = body.water_reminder_min
        changed_keys.append("water_reminder_min")
    if body.language is not None:
        if body.language not in {"zh", "en"}:
            raise HTTPException(status_code=422, detail="Invalid language")
        s.language = body.language
        current_user.language = body.language
        changed_keys.append("language")

    s.updated_at = datetime.now(timezone.utc)
    db.commit()
    log.info(
        "settings updated",
        extra={
            "event": "settings_updated",
            "domain": "users",
            "changed_keys": changed_keys,
        },
    )
    return {"message": "Settings updated"}
