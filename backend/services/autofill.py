"""
Midnight auto-fill worker.

Runs at 00:00 UTC and, for any user whose previous-day meal plan was not
confirmed, copies each breakfast/lunch/dinner entry into DietLog — but only
for slots that the user did not already fill manually.

Snacks are never auto-filled.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

import models
from database import SessionLocal

MEAL_TYPES = ("breakfast", "lunch", "dinner")


def _yesterday_utc_str() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def build_diet_log_from_entry(entry: models.MealPlanEntry) -> models.DietLog:
    """Translate a planned meal into an unsaved DietLog row.

    Caller is responsible for `db.add()` and committing. Shared between the
    midnight auto-fill worker and the user-initiated confirm-to-log flow so
    the two paths cannot drift.
    """
    recipe = entry.recipe
    food_name = recipe.name if recipe else (entry.custom_name or entry.meal_type)
    return models.DietLog(
        user_id=entry.user_id,
        date=entry.date,
        meal_type=entry.meal_type,
        food_name=food_name,
        ingredients=(recipe.ingredients if recipe else None),
        calories=int(entry.calories or 0),
        protein_g=float(entry.protein_g or 0.0),
        carbs_g=float(entry.carbs_g or 0.0),
        fat_g=float(entry.fat_g or 0.0),
    )


def run_autofill_for_date(db: Session, date_str: str) -> dict:
    """Fill empty breakfast/lunch/dinner slots from any unconfirmed plans."""
    confirmed_pairs = {
        (c.user_id, c.date)
        for c in db.query(models.DailyMealPlanConfirmation)
        .filter(models.DailyMealPlanConfirmation.date == date_str)
        .all()
    }

    entries = (
        db.query(models.MealPlanEntry)
        .filter(models.MealPlanEntry.date == date_str)
        .all()
    )

    filled_count = 0
    skipped_confirmed = 0
    skipped_logged = 0

    for entry in entries:
        if entry.meal_type not in MEAL_TYPES:
            continue
        if (entry.user_id, entry.date) in confirmed_pairs:
            skipped_confirmed += 1
            continue
        existing_log = (
            db.query(models.DietLog)
            .filter(
                models.DietLog.user_id == entry.user_id,
                models.DietLog.date == entry.date,
                models.DietLog.meal_type == entry.meal_type,
            )
            .first()
        )
        if existing_log:
            skipped_logged += 1
            continue
        db.add(build_diet_log_from_entry(entry))
        filled_count += 1

    db.commit()
    return {
        "date": date_str,
        "filled": filled_count,
        "skipped_confirmed": skipped_confirmed,
        "skipped_already_logged": skipped_logged,
    }


def run_midnight_autofill() -> dict:
    """Entry point used by the scheduler. Opens its own DB session."""
    db = SessionLocal()
    try:
        return run_autofill_for_date(db, _yesterday_utc_str())
    finally:
        db.close()
