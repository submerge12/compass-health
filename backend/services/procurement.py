"""
Weekly procurement aggregator (spec-v1).

Reads the user's persisted plan — `UserFixedMeal` + `MealPlanEntry` + `DietLog`
— and projects it through `planning_context.project_week`, which applies the
priority chain (recorded > fixed > recipe > generated) per (date, meal_type).
Each surviving slot is then expanded into per-slug grams via
`Recipe.ingredients_json` scaled by `portion_g / serving_g`.

Slots that can't be expanded (recorded meals or custom-named meals with no
recipe link) contribute nothing to the shopping list and are surfaced in
`warnings` instead. Generated arrangements are expanded when they already
persisted a structured Recipe row.

Each output row carries:
  * slug + display names
  * planned total weekly grams (sum of every scaled portion)
  * recommended purchase grams (planned + safety buffer, rounded up)
  * whether it's a "key food" (sole carrier of a bucket / nutrient)
  * whether it has substitutes in the user's library
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from services import food_library as FL
from services import nutrition_audit
from services import planning_context as pc


SAFETY_BUFFER = 0.15  # 15 %
ROUND_TO = 10         # nearest 10 g for shopping convenience


def _round_up(x: float, step: int) -> int:
    return int((x + step - 1) // step * step)


def _parse_ingredients_json(raw: Optional[str]) -> list[dict]:
    """Return the recipe's structured ingredient list, [] if absent/malformed.

    Duplicated from `recipe_matcher` rather than imported — procurement needs
    the full row (slug + grams), while recipe_matcher only needs the slug
    plus the `required` flag. Keeping the two helpers independent lets each
    module filter/shape as it likes.
    """
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("slug")]


def _expand_recipe(
    recipe,
    portion_g: Optional[float],
    gram_totals: dict[str, float],
    meal_counts: dict[str, int],
    warnings: list[str],
    slot_label: str,
) -> None:
    """Add a recipe's ingredients into the running totals, scaled to portion.

    `recipe` is a Recipe row. `portion_g` is the slot's actual portion; when
    both `portion_g` and `recipe.serving_g` are present we scale linearly,
    otherwise we take ingredient grams as-stored.

    An ingredient with `grams: null` is skipped with a warning — the spec-v1
    backfill initialised legacy recipes this way, and we don't want to
    silently underbuy (or silently overbuy via a fabricated fallback).
    """
    ings = _parse_ingredients_json(getattr(recipe, "ingredients_json", None))
    if not ings:
        warnings.append(
            f"{slot_label}: recipe '{recipe.name}' has no structured ingredients — skipped."
        )
        return

    serving = getattr(recipe, "serving_g", None)
    multiplier = (portion_g / serving) if (portion_g and serving) else 1.0

    for ing in ings:
        slug = ing.get("slug")
        grams = ing.get("grams")
        if not slug:
            continue
        if grams is None:
            warnings.append(
                f"{slot_label}: recipe '{recipe.name}' ingredient '{slug}' "
                f"has no grams — skipped."
            )
            continue
        gram_totals[slug] += float(grams) * multiplier
        meal_counts[slug] += 1


def aggregate_for_week(
    db: Session,
    user,                           # models.User (avoid circular import)
    start_date: str,                # "YYYY-MM-DD"
    non_substitutable_slugs: Iterable[str] = (),
    length_days: int = 7,
) -> dict:
    """Build the shopping list for a 7-day window from persisted state.

    Output shape:
      {
        "groups":           [{bucket, label_zh, label_en, rows: [...]}, ...],
        "total_slugs":      int,
        "total_planned_g":  float,
        "warnings":         [str, ...],
      }

    Each `row` inside `groups` is the same shape as the legacy `aggregate()`
    produced, so the frontend renders without changes.
    """
    from models import Recipe, MealPlanEntry, UserFixedMeal  # lazy, avoid circular

    contexts = pc.project_week(db, user, start_date, length_days)
    key_set = set(non_substitutable_slugs)
    library_slugs = nutrition_audit.load_user_library(db, user.id)

    gram_totals: dict[str, float] = defaultdict(float)
    meal_counts: dict[str, int] = defaultdict(int)
    warnings:   list[str]         = []

    # Cache recipe lookups — a week of plans typically references a handful
    # of recipes, not hundreds.
    recipe_cache: dict[int, Optional[Recipe]] = {}

    def _recipe(rid: Optional[int]):
        if rid is None:
            return None
        if rid not in recipe_cache:
            recipe_cache[rid] = db.query(Recipe).filter_by(id=rid).first()
        return recipe_cache[rid]

    for ctx in contexts:
        date = ctx.date

        for slot in ctx.fixed_meals:
            label = f"{date}/{slot.meal_type} (fixed)"
            src = db.query(UserFixedMeal).filter_by(id=slot.source_id).first()
            if src is None:
                continue
            if src.recipe_id is None:
                warnings.append(
                    f"{label}: '{src.custom_name or 'custom meal'}' has no recipe — "
                    f"cannot add to shopping list."
                )
                continue
            recipe = _recipe(src.recipe_id)
            if recipe is None:
                warnings.append(f"{label}: linked recipe missing.")
                continue
            _expand_recipe(recipe, src.portion_g, gram_totals, meal_counts, warnings, label)

        for slot in ctx.planned_meals:
            label = f"{date}/{slot.meal_type} ({slot.status})"
            src = db.query(MealPlanEntry).filter_by(id=slot.source_id).first()
            if slot.status not in (pc.SLOT_STATUS_RECIPE, pc.SLOT_STATUS_GENERATED):
                warnings.append(
                    f"{label}: unsupported planned slot status — skipped."
                )
                continue
            if src is None or src.recipe_id is None:
                warnings.append(
                    f"{label}: plan entry is missing its recipe link — cannot add to shopping list."
                )
                continue
            recipe = _recipe(src.recipe_id)
            if recipe is None:
                warnings.append(f"{label}: linked recipe missing.")
                continue
            _expand_recipe(recipe, src.portion_g, gram_totals, meal_counts, warnings, label)

        # Recorded (DietLog) slots are intentionally skipped — DietLog stores
        # `food_name` + raw text `ingredients`, not structured slug/grams,
        # and the meal is already consumed either way.

    # ── Group by execution bucket ────────────────────────────────────────
    grouped: dict[str, list[dict]] = defaultdict(list)
    for slug, grams in gram_totals.items():
        entry = FL.FOOD_LIBRARY.get(slug)
        if not entry:
            continue
        recommended = _round_up(grams * (1 + SAFETY_BUFFER), ROUND_TO)
        row = {
            "slug":                slug,
            "name_zh":             entry["zh"],
            "name_en":             entry["en"],
            "planned_g":           round(grams, 1),
            "recommended_g":       recommended,
            "meal_count":          meal_counts[slug],
            "is_key_food":         slug in key_set,
            "replaceable":         _has_substitute_in_library(slug, entry, library_slugs),
            "primary_macro":       entry["primary_macro"],
            "micronutrient_roles": list(entry["micronutrient_roles"]),
            "notes":               entry.get("notes"),
        }
        buckets = entry["execution_buckets"] or ("other",)
        grouped[buckets[0]].append(row)

    bucket_order = list(FL.EXECUTION_BUCKETS) + ["other"]
    groups: list[dict] = []
    for bucket in bucket_order:
        rows = grouped.get(bucket, [])
        if not rows:
            continue
        rows.sort(key=lambda r: (-r["recommended_g"], r["slug"]))
        groups.append({
            "bucket":   bucket,
            "label_zh": FL.EXECUTION_BUCKET_LABELS.get(bucket, {}).get("zh", bucket),
            "label_en": FL.EXECUTION_BUCKET_LABELS.get(bucket, {}).get("en", bucket),
            "rows":     rows,
        })

    return {
        "groups":          groups,
        "total_slugs":     len(gram_totals),
        "total_planned_g": round(sum(gram_totals.values()), 1),
        "warnings":        warnings,
    }


def _has_substitute_in_library(
    slug: str, entry: dict, library_slugs: Iterable[str]
) -> bool:
    """True when another slug sharing the primary execution bucket is also
    in the user's library. Used to render the "replaceable" badge next to each row."""
    buckets = entry["execution_buckets"]
    if not buckets:
        return False
    main_bucket = buckets[0]
    for other_slug in library_slugs:
        if other_slug == slug:
            continue
        other = FL.FOOD_LIBRARY.get(other_slug)
        if other and main_bucket in other["execution_buckets"]:
            return True
    return False
