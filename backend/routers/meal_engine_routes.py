"""
Meal-engine HTTP surface.

This router serves the deterministic, LLM-free layer of the meal-planning
pipeline — the "Daily Nutrition Requirements" view and everything that
feeds it. Recipe generation and dish selection live under
`/api/meal-plan/*`.

Endpoints:

  GET  /api/meal-engine/audit                    Nutrition audit of the user's closed library
  GET  /api/meal-engine/exchange                 Exchange matrix restricted to the user's library
  GET  /api/meal-engine/targets                  Today's calorie / macro / day-type targets
  POST /api/meal-engine/procurement              Shopping list aggregated from the user's persisted plan
  GET  /api/meal-engine/daily                    Today's achievement report
  GET  /api/meal-engine/weekly                   Weekly review + adjustment suggestions
  GET  /api/meal-engine/library                  Static food library + bucket metadata
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from services import (
    calorie as calorie_svc,
    food_library as FL,
    nutrition_audit,
    procurement,
    feedback_loop,
)


router = APIRouter(prefix="/api/meal-engine", tags=["meal-engine"])
log = logging.getLogger("compass.app")


# ── Library + bucket metadata (static) ───────────────────────────────────────

@router.get("/library")
def library_metadata():
    """Everything the frontend needs to render buckets and exchange matrix
    without having to hard-code slug → category mappings."""
    foods = {
        slug: {
            "zh": entry["zh"],
            "en": entry["en"],
            "primary_macro": entry["primary_macro"],
            "kcal_per_100g": entry["kcal_per_100g"],
            "protein_per_100g": entry["protein_per_100g"],
            "carbs_per_100g": entry["carbs_per_100g"],
            "fat_per_100g": entry["fat_per_100g"],
            "exchange_g": entry["exchange_g"],
            "validation_buckets": list(entry["validation_buckets"]),
            "execution_buckets": list(entry["execution_buckets"]),
            "micronutrient_roles": list(entry["micronutrient_roles"]),
            "weekly_floor": entry.get("weekly_floor", 0),
            "notes": entry.get("notes"),
        }
        for slug, entry in FL.FOOD_LIBRARY.items()
    }
    return {
        "validation_buckets": [
            {"key": b, **FL.VALIDATION_BUCKET_LABELS[b]} for b in FL.VALIDATION_BUCKETS
        ],
        "execution_buckets": [
            {"key": b, **FL.EXECUTION_BUCKET_LABELS[b]} for b in FL.EXECUTION_BUCKETS
        ],
        "micronutrients": [
            {"key": k, **v} for k, v in FL.MICRONUTRIENT_ROLES.items()
        ],
        "foods": foods,
        "exchange_unit": {
            "carb_g": FL.CARB_EXCHANGE_G,
            "protein_g": FL.PROTEIN_EXCHANGE_G,
            "fat_g": FL.FAT_EXCHANGE_G,
        },
    }


# ── Audit ────────────────────────────────────────────────────────────────────

@router.get("/audit")
def get_audit(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    audit = nutrition_audit.run_audit(db, current_user)
    validation = audit.get("validation", {})
    log.info(
        "meal-engine audit viewed",
        extra={
            "event": "meal_engine_audit_viewed",
            "domain": "meal_engine",
            "slug_count": audit.get("slug_count", 0),
            "feasibility": validation.get("overall"),
            "missing_blocking_buckets_count": len(validation.get("missing_blocking_buckets", [])),
            "missing_soft_buckets_count": len(validation.get("missing_soft_buckets", [])),
            "missing_nutrients_count": len(validation.get("missing_nutrients", [])),
            "non_substitutable_count": len(audit.get("non_substitutable", [])),
            "suggestion_count": len(audit.get("suggestions", [])),
        },
    )
    return audit


@router.get("/exchange")
def get_exchange_matrix(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    slugs = nutrition_audit.load_user_library(db, current_user.id)
    log.info(
        "meal-engine exchange matrix viewed",
        extra={
            "event": "meal_engine_exchange_viewed",
            "domain": "meal_engine",
            "library_count": len(slugs),
        },
    )
    return {
        "library": slugs,
        "matrix": nutrition_audit.exchange_matrix(slugs),
        "exchange_unit": {
            "carb_g": FL.CARB_EXCHANGE_G,
            "protein_g": FL.PROTEIN_EXCHANGE_G,
            "fat_g": FL.FAT_EXCHANGE_G,
        },
    }


# ── Targets ──────────────────────────────────────────────────────────────────

@router.get("/targets")
def get_targets(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    targets = calorie_svc.build_daily_targets(db, current_user)
    if not targets.get("has_bmr_profile"):
        log.info(
            "meal-engine targets requested without bmr profile",
            extra={
                "event": "meal_engine_targets_missing_bmr",
                "domain": "meal_engine",
                "has_bmr_profile": False,
            },
        )
        raise HTTPException(status_code=400, detail="BMR profile required")
    log.info(
        "meal-engine targets viewed",
        extra={
            "event": "meal_engine_targets_viewed",
            "domain": "meal_engine",
            "has_bmr_profile": True,
            "activity_level": targets.get("activity_level"),
            "activity_is_default": targets.get("activity_is_default"),
        },
    )
    return targets


# ── Procurement aggregation ──────────────────────────────────────────────────

class _ProcurementRequest(BaseModel):
    start_date: Optional[str] = None    # "YYYY-MM-DD"; defaults to today (UTC)


@router.post("/procurement")
def post_procurement(
    body: Optional[_ProcurementRequest] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Shopping list aggregated from the user's persisted plan.

    Reads `UserFixedMeal` + `MealPlanEntry` + `DietLog` for the 7-day window
    starting at `start_date` (today UTC if omitted). The priority chain
    (recorded > fixed > recipe > generated) is applied per slot inside
    `procurement.aggregate_for_week`; recorded (DietLog) slots contribute
    nothing, recipe-backed slots expand via `Recipe.ingredients_json`, and
    generated slots surface in `warnings` so the user can commit a recipe.
    """
    from datetime import datetime, timezone

    audit = nutrition_audit.run_audit(db, current_user)
    feasibility = audit.get("validation", {}).get("overall")
    if feasibility == "not_closed_loop":
        log.warning(
            "meal-engine procurement blocked by infeasible library",
            extra={
                "event": "meal_engine_procurement_blocked",
                "domain": "meal_engine",
                "feasibility": feasibility,
            },
        )
        return {
            "feasibility": "not_closed_loop",
            "message_zh": "闭环不完整，无法生成采购清单。",
            "message_en": "Library is not closed-loop feasible — no shopping list.",
        }

    start_date = (body.start_date if body else None) or \
        datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key_slugs = {row["slug"] for row in audit.get("non_substitutable", [])}
    result = procurement.aggregate_for_week(db, current_user, start_date, key_slugs)
    log.info(
        "meal-engine procurement viewed",
        extra={
            "event": "meal_engine_procurement_viewed",
            "domain": "meal_engine",
            "start_date": start_date,
            "feasibility": feasibility,
            "group_count": len(result.get("groups", [])),
            "total_slugs": result.get("total_slugs", 0),
            "warnings_count": len(result.get("warnings", [])),
        },
    )

    return {
        "start_date":  start_date,
        "feasibility": feasibility,
        **result,
    }


# ── Execution feedback ───────────────────────────────────────────────────────

@router.get("/daily")
def get_daily(
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    report = feedback_loop.daily_report(db, current_user, date)
    log.info(
        "meal-engine daily feedback viewed",
        extra={
            "event": "meal_engine_daily_feedback_viewed",
            "domain": "meal_engine",
            "date": report.get("date", date),
            "has_bmr_profile": report.get("has_bmr_profile", False),
            "diet_entries": report.get("actual", {}).get("entries", 0),
            "missing_planned_slots_count": len(report.get("planned_slots", {}).get("missing", [])),
        },
    )
    return report


@router.get("/weekly")
def get_weekly(
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    review = feedback_loop.weekly_review(db, current_user, end_date)
    logged_days = len([
        day for day in review.get("dailies", [])
        if day.get("actual", {}).get("entries", 0) > 0
    ])
    log.info(
        "meal-engine weekly feedback viewed",
        extra={
            "event": "meal_engine_weekly_feedback_viewed",
            "domain": "meal_engine",
            "has_bmr_profile": review.get("has_bmr_profile", False),
            "logged_days": logged_days,
            "adjustment_count": len(review.get("adjustments", [])),
            "skipped_key_foods_count": len(review.get("skipped_key_foods", [])),
        },
    )
    return review
