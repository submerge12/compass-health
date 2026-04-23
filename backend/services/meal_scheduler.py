"""
Meal-plan slot scheduling validator.

When a user places a dish into a calendar slot, this module checks two things
and returns soft warnings (never blocks the save):

  1. Ingredient overuse — any food slug from the new dish already appears in
     ≥ WEEKLY_INGREDIENT_CAP other dishes scheduled this week.

  2. Day-type mismatch — the day is "locked" (red-meat day / deep-sea fish day)
     but the proposed dish contains no ingredients from the required bucket.

Both warnings are informational.  The calling endpoint must still commit the
entry regardless — these are guides, not hard constraints.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

import models
from services import food_library as FL

WEEKLY_INGREDIENT_CAP = 3   # warn when a slug would reach this many appearances


# ── Helpers ───────────────────────────────────────────────────────────────────

def _week_bounds(date_str: str) -> tuple[str, str]:
    """Return (ISO-week Monday, Sunday) as 'YYYY-MM-DD' strings."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    monday = d - timedelta(days=d.weekday())
    sunday  = monday + timedelta(days=6)
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")


def slugs_from_recipe(recipe: models.Recipe) -> list[str]:
    """Extract food-library slugs stored on the recipe.

    Only pool-derived dishes carry this field (JSON array).  All others return
    an empty list so validation gracefully skips them.
    """
    if not recipe or not recipe.ingredient_slugs:
        return []
    try:
        result = json.loads(recipe.ingredient_slugs)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


# ── Public validator ──────────────────────────────────────────────────────────

def validate_slot(
    db: Session,
    user_id: int,
    date: str,
    meal_type: str,
    recipe: models.Recipe,
    week_skeleton: list[dict] | None = None,
) -> list[dict]:
    """Return a (possibly empty) list of warning dicts.

    Each warning:
      {"code": str, "message_zh": str, "message_en": str, ...extra keys}

    Possible codes:
      "ingredient_overuse"  — slug appears ≥ WEEKLY_INGREDIENT_CAP times already
      "day_type_mismatch"   — locked day but dish has no required ingredient
    """
    warnings: list[dict] = []
    monday, sunday = _week_bounds(date)

    # Load all OTHER entries in this week (exclude the slot being set, so an
    # update to an existing entry doesn't double-count itself).
    existing = (
        db.query(models.MealPlanEntry)
        .join(models.Recipe, models.MealPlanEntry.recipe_id == models.Recipe.id,
              isouter=True)
        .filter(
            models.MealPlanEntry.user_id == user_id,
            models.MealPlanEntry.date >= monday,
            models.MealPlanEntry.date <= sunday,
        )
        .all()
    )
    # Exclude the slot we're placing into so upserts don't see the old value.
    existing = [
        e for e in existing
        if not (e.date == date and e.meal_type == meal_type)
    ]

    # Count how many scheduled dishes already contain each ingredient slug.
    slug_counts: Counter = Counter()
    for entry in existing:
        if entry.recipe:
            for slug in slugs_from_recipe(entry.recipe):
                slug_counts[slug] += 1

    # Check the incoming recipe's slugs against the cap.
    new_slugs = slugs_from_recipe(recipe)
    for slug in set(new_slugs):  # set: de-dup within same dish
        existing_count = slug_counts[slug]
        if existing_count >= WEEKLY_INGREDIENT_CAP:
            entry_fl = FL.FOOD_LIBRARY.get(slug)
            # Suggest alternatives from the same execution bucket.
            alts: list[str] = []
            if entry_fl:
                for bucket in entry_fl["execution_buckets"]:
                    alts.extend(FL.slugs_by_execution_bucket(bucket))
                alts = [a for a in alts if a != slug][:3]
            name_zh = FL.display_name(slug, "zh")
            name_en = FL.display_name(slug, "en")
            alt_zh  = "、".join(FL.display_name(a, "zh") for a in alts)
            alt_en  = ", ".join(FL.display_name(a, "en") for a in alts)
            warnings.append({
                "code": "ingredient_overuse",
                "slug": slug,
                "weekly_count": existing_count,
                "cap": WEEKLY_INGREDIENT_CAP,
                "message_zh": (
                    f"「{name_zh}」本周已安排 {existing_count} 次，建议增加食材多样性。"
                    + (f"可替换为：{alt_zh}。" if alt_zh else "")
                ),
                "message_en": (
                    f"'{name_en}' appears {existing_count} time(s) this week — "
                    "consider more variety."
                    + (f" Alternatives: {alt_en}." if alt_en else "")
                ),
            })

    # Day-type mismatch check.
    if week_skeleton and new_slugs:
        day_info = next((d for d in week_skeleton if d.get("date") == date), None)
        if day_info and day_info.get("is_locked"):
            day_type = day_info["day_type"]
            required_buckets: set[str] = {
                "red_meat_day":      {"red_meat"},
                "deep_sea_fish_day": {"deep_sea_fish"},
            }.get(day_type, set())

            if required_buckets:
                has_required = any(
                    set(FL.FOOD_LIBRARY.get(s, {}).get("execution_buckets", [])) & required_buckets
                    for s in new_slugs
                )
                if not has_required:
                    warnings.append({
                        "code": "day_type_mismatch",
                        "day_type": day_type,
                        "message_zh": (
                            f"今日为「{day_info.get('day_type_label_zh', day_type)}」，"
                            "建议此餐含有对应食材以满足当日营养计划。"
                        ),
                        "message_en": (
                            f"Today is a '{day_info.get('day_type_label_en', day_type)}' — "
                            "consider including the required ingredient type for this day's plan."
                        ),
                    })

    return warnings
