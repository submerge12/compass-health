from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

import models
from services import calorie, local_dates


def today_key() -> str:
    return local_dates.today_key()


def upsert_condition_weight(
    db: Session,
    user_id: int,
    weight_kg: float,
    *,
    date: str | None = None,
) -> models.PhysicalCondition:
    target_date = date or today_key()
    now = datetime.now(timezone.utc)
    entry = (
        db.query(models.PhysicalCondition)
        .filter(
            models.PhysicalCondition.user_id == user_id,
            models.PhysicalCondition.date == target_date,
        )
        .first()
    )
    if entry:
        entry.weight_kg = weight_kg
        entry.logged_at = now
        return entry

    entry = models.PhysicalCondition(
        user_id=user_id,
        date=target_date,
        weight_kg=weight_kg,
        logged_at=now,
    )
    db.add(entry)
    return entry


def sync_profile_weight(db: Session, user: models.User, weight_kg: float) -> models.BMRProfile | None:
    profile = user.bmr_profile
    if not profile:
        return None

    profile.weight_kg = weight_kg
    profile.bmr_value = round(
        calorie.compute_bmr(profile.age, profile.gender, profile.height_cm, weight_kg),
        1,
    )
    profile.updated_at = datetime.now(timezone.utc)
    return profile


def latest_weight_snapshot(db: Session, user: models.User) -> dict[str, Any] | None:
    snapshots: list[dict[str, Any]] = []
    condition = (
        db.query(models.PhysicalCondition)
        .filter(
            models.PhysicalCondition.user_id == user.id,
            models.PhysicalCondition.weight_kg.isnot(None),
        )
        .order_by(
            models.PhysicalCondition.date.desc(),
            models.PhysicalCondition.logged_at.desc(),
            models.PhysicalCondition.id.desc(),
        )
        .first()
    )
    if condition:
        snapshots.append(
            {
                "weight_kg": condition.weight_kg,
                "date": condition.date,
                "logged_at": condition.logged_at.isoformat() if condition.logged_at else None,
                "source": "condition",
            }
        )

    profile = user.bmr_profile
    if profile and profile.weight_kg is not None:
        profile_date = local_dates.app_now(profile.updated_at).strftime("%Y-%m-%d") if profile.updated_at else None
        snapshots.append(
            {
                "weight_kg": profile.weight_kg,
                "date": profile_date,
                "logged_at": profile.updated_at.isoformat() if profile.updated_at else None,
                "source": "profile",
            }
        )

    if not snapshots:
        return None

    return max(
        snapshots,
        key=lambda item: (
            item.get("date") or "",
            item.get("logged_at") or "",
            1 if item.get("source") == "profile" else 0,
        ),
    )
