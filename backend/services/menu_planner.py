"""
Day-type meal planner — three modes:

  generate_dish_pool(db, user)
    Returns a flat pool of ~30 candidate dishes (5-6 breakfast + 24-25
    lunch/dinner combined). The pool is ingredient-diverse: no single
    ingredient appears in more than 20 % of the dishes in its type group.
    Each dish sketch carries its ingredient set and macro totals so the LLM
    recipe-suggester can name it without re-solving.

    Flow: pool → user picks → saved recipes (cap 20) → user schedules freely
    via MealPlanEntry. The scheduler does not require the saved library to be
    full before planning starts.

  fill_empty_slots(db, user, date_str)      [spec-v1]
    Single-day incremental filler. Reads a `DayPlanningContext`, and for each
    empty meal type returns a new `MealSlot` — first trying the recipe
    library (status=recipe) and falling back to the deterministic solver
    (status=generated). Never re-solves filled slots, so the planner can be
    called after any user edit without wiping prior work. Does NOT write to
    the database; the route layer persists the returned slots.

  week_plan(db, user)
    7-day auto-assign solver. Produces `nutrition_requirements` (per-slot
    targets + bucket hints) and `solved_picks` (deterministic parts +
    portions). Consumed by `/nutrition-requirements`, `/procurement`, and
    the two `/candidates` endpoints. No post-hoc mutation: reinforcement
    day-types bias picks toward `red_meat_day` / `deep_sea_fish_day`, and
    any weekly_floor shortfall surfaces as a warning.

The solver is deterministic and greedy — no LLM call inside this module.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from itertools import product
import json
from typing import Optional

from sqlalchemy.orm import Session

import models
from services import calorie as calorie_svc
from services import food_library as FL
from services import local_dates
from services import nutrition_audit
from services import planning_context as pc
from services import recipe_matcher


# ── Meal share of the day (fraction of daily kcal) ───────────────────────────
MEAL_SPLIT: dict[str, float] = {
    "breakfast": 0.25,
    "lunch":     0.40,
    "dinner":    0.35,
}


# ── Day types ────────────────────────────────────────────────────────────────
DAY_TYPES = (
    "low_activity",
    "moderate_activity",
    "high_activity",
    "red_meat_day",
    "deep_sea_fish_day",
    "pantry_clearance",
)

DAY_TYPE_LABELS: dict[str, dict[str, str]] = {
    "low_activity":      {"zh": "低活动日",         "en": "Low-activity day"},
    "moderate_activity": {"zh": "中等活动日",       "en": "Moderate-activity day"},
    "high_activity":     {"zh": "高活动日",         "en": "High-activity day"},
    "red_meat_day":      {"zh": "红肉强化日",       "en": "Red-meat reinforcement day"},
    "deep_sea_fish_day": {"zh": "深海鱼强化日",     "en": "Deep-sea fish day"},
    "pantry_clearance":  {"zh": "灵活清库日",       "en": "Pantry-clearance day"},
}

# Activity level → baseline day type.
_ACTIVITY_TO_DAY_TYPE: dict[str, str] = {
    "sedentary":         "low_activity",
    "lightly_active":    "moderate_activity",
    "moderately_active": "high_activity",
    "strength_training": "high_activity",
}


# ── Day-type calendar ────────────────────────────────────────────────────────

def _resolve_activity_for_day(
    db: Session, user_id: int, date_str: str
) -> tuple[str, bool]:
    logged = calorie_svc.get_activity_for_date(db, user_id, date_str)
    if logged:
        return logged, True
    return calorie_svc.default_activity_for_user(db, user_id), False


def _calendar_for_week(
    db: Session, user_id: int, start_date: datetime, classification: dict[str, list[str]]
) -> list[dict]:
    """Return 7 day rows with their day_type slotted in.

    Logged activity wins for day type. On top of the activity baseline we
    weave in reinforcement days so the weekly_floor on key foods (red meat,
    deep-sea fish) gets honoured."""
    days: list[dict] = []
    for offset in range(7):
        day = start_date + timedelta(days=offset)
        date_str = day.strftime("%Y-%m-%d")
        activity, is_logged = _resolve_activity_for_day(db, user_id, date_str)
        base_type = _ACTIVITY_TO_DAY_TYPE.get(activity, "moderate_activity")
        days.append({
            "date": date_str,
            "weekday": day.weekday(),   # 0 = Mon
            "activity_level": activity,
            "activity_is_logged": is_logged,
            "day_type": base_type,
        })

    # Overlay reinforcement days where the library has the right carriers and
    # they aren't already reinforced by activity. Only rewrite activity-based
    # day types — never stomp on a reinforcement day already set by an
    # earlier pass.
    _ACTIVITY_TYPES = {"low_activity", "moderate_activity", "high_activity"}

    def _bump_reinforcement(day_type: str, max_count: int, bucket_slugs: list[str]):
        if not bucket_slugs:
            return
        # Prefer low-activity days first, then moderate. Never high.
        candidates = sorted(
            (d for d in days
             if d["day_type"] in _ACTIVITY_TYPES
             and d["day_type"] != "high_activity"),
            key=lambda d: (0 if d["day_type"] == "low_activity" else 1, d["weekday"]),
        )
        replaced = 0
        for d in candidates:
            if replaced >= max_count:
                return
            d["day_type"] = day_type
            replaced += 1

    _bump_reinforcement("red_meat_day", 2, classification.get("red_meat", []))
    _bump_reinforcement("deep_sea_fish_day", 2, classification.get("deep_sea_fish", []))
    return days


# ── Solver helpers ───────────────────────────────────────────────────────────

def _pick(
    bucket_slugs: list[str],
    weekly_counts: Counter,
    preferred: Optional[str] = None,
) -> Optional[str]:
    """Greedy: honour an explicit preferred slug if available; otherwise pick
    the least-used slug in the bucket so the week stays varied."""
    if preferred and preferred in bucket_slugs:
        return preferred
    if not bucket_slugs:
        return None
    return sorted(bucket_slugs, key=lambda s: (weekly_counts[s], s))[0]


def _scale_to_macro(
    slug: str,
    target_g: float,
    macro: str,
) -> dict:
    """Scale a food's 100 g row so its primary macro hits `target_g` grams."""
    entry = FL.FOOD_LIBRARY[slug]
    per_100 = entry[f"{macro}_per_100g"]
    if per_100 <= 0:
        grams = 0.0
    else:
        grams = target_g * 100.0 / per_100
    return _portion(slug, grams)


def _scale_to_kcal(slug: str, kcal_target: float) -> dict:
    entry = FL.FOOD_LIBRARY[slug]
    per_100 = entry["kcal_per_100g"]
    if per_100 <= 0:
        return _portion(slug, 0.0)
    grams = kcal_target * 100.0 / per_100
    return _portion(slug, grams)


def _fixed_portion(slug: str, grams: float) -> dict:
    return _portion(slug, grams)


def _portion(slug: str, grams: float) -> dict:
    entry = FL.FOOD_LIBRARY[slug]
    g = max(0.0, round(grams / 5.0) * 5.0)  # round to nearest 5 g for realism
    factor = g / 100.0
    return {
        "slug": slug,
        "name_zh": entry["zh"],
        "name_en": entry["en"],
        "grams": round(g, 1),
        "kcal": round(entry["kcal_per_100g"] * factor, 1),
        "protein_g": round(entry["protein_per_100g"] * factor, 1),
        "carbs_g": round(entry["carbs_per_100g"] * factor, 1),
        "fat_g": round(entry["fat_per_100g"] * factor, 1),
        "primary_macro": entry["primary_macro"],
        "execution_buckets": list(entry["execution_buckets"]),
        "micronutrient_roles": list(entry["micronutrient_roles"]),
    }


def _sum_portion(parts: list[dict]) -> dict:
    return {
        "grams": round(sum(p["grams"] for p in parts), 1),
        "kcal": round(sum(p["kcal"] for p in parts), 1),
        "protein_g": round(sum(p["protein_g"] for p in parts), 1),
        "carbs_g": round(sum(p["carbs_g"] for p in parts), 1),
        "fat_g": round(sum(p["fat_g"] for p in parts), 1),
    }


# ── Meal composer ───────────────────────────────────────────────────────────

def _compose_meal(
    meal_type: str,
    day_type: str,
    day_targets: dict,
    classification: dict[str, list[str]],
    weekly_counts: Counter,
) -> dict:
    """Pick a staple, a protein, a veg and an optional fat / egg / dairy, and
    scale portions to hit the meal's slice of the daily macros."""
    share = MEAL_SPLIT[meal_type]
    meal_kcal = day_targets["calorie_target"] * share
    meal_protein = day_targets["protein_g"] * share
    meal_carbs = day_targets["carbs_g"] * share
    meal_fat = day_targets["fat_g"] * share

    # Bucket keys actually drawn from for each role — surfaced as "bucket_hints"
    # so the nutrition-requirements view can describe *what* should fill each
    # slot without leaking specific food slugs.
    bucket_hints: dict[str, Optional[str]] = {
        "protein": None,
        "staple": None,
        "vegetable": None,
        "second_vegetable": None,
        "fat_functional": None,
    }

    # --- protein ----------------------------------------------------
    prot_buckets_priority: list[str]
    if meal_type == "breakfast":
        prot_buckets_priority = ["egg", "dairy", "soy_product", "lean_white_meat"]
    elif day_type == "red_meat_day":
        prot_buckets_priority = ["red_meat", "lean_white_meat", "soy_product"]
    elif day_type == "deep_sea_fish_day":
        prot_buckets_priority = ["deep_sea_fish", "shellfish", "lean_white_meat"]
    elif meal_type == "lunch":
        prot_buckets_priority = [
            "lean_white_meat", "red_meat", "deep_sea_fish", "shellfish", "soy_product", "egg",
        ]
    else:  # dinner
        prot_buckets_priority = [
            "lean_white_meat", "shellfish", "deep_sea_fish", "soy_product", "red_meat", "egg",
        ]

    protein_slug = None
    for bucket in prot_buckets_priority:
        protein_slug = _pick(classification.get(bucket, []), weekly_counts)
        if protein_slug:
            bucket_hints["protein"] = bucket
            break

    # --- staple -----------------------------------------------------
    if day_type == "low_activity":
        staple_priority = ["slow_carb_staple", "fast_carb_staple"]
    else:
        staple_priority = ["fast_carb_staple", "slow_carb_staple"]
    staple_slug = None
    for bucket in staple_priority:
        staple_slug = _pick(classification.get(bucket, []), weekly_counts)
        if staple_slug:
            bucket_hints["staple"] = bucket
            break

    # --- vegetable --------------------------------------------------
    veg_priority = ["dark_leafy_green", "cruciferous_fungi_algae"]
    veg_slug = None
    for bucket in veg_priority:
        veg_slug = _pick(classification.get(bucket, []), weekly_counts)
        if veg_slug:
            bucket_hints["vegetable"] = bucket
            break

    # Second veg for bigger meals
    second_veg_slug = None
    second_veg_bucket = None
    if meal_type != "breakfast":
        second_veg_bucket = (
            "cruciferous_fungi_algae"
            if veg_slug in classification.get("dark_leafy_green", [])
            else "dark_leafy_green"
        )
        second_veg_slug = _pick(classification.get(second_veg_bucket, []), weekly_counts)
        if second_veg_slug == veg_slug:
            second_veg_slug = None
            second_veg_bucket = None
        if second_veg_slug:
            bucket_hints["second_vegetable"] = second_veg_bucket

    # --- healthy fat / functional ---------------------------------
    fat_slug = None
    if meal_type == "breakfast" or day_type == "low_activity":
        fat_slug = _pick(classification.get("nut_seed_functional", []), weekly_counts)
        if fat_slug:
            bucket_hints["fat_functional"] = "nut_seed_functional"

    parts: list[dict] = []

    # Protein: scale to the meal's protein target (minus what staple/veg will carry).
    # Subtract an estimate for other carriers first — but since staple/veg are
    # low-protein, we budget ~5 g for them combined and aim the protein food
    # at (meal_protein - 5).
    if protein_slug:
        prot_target = max(10.0, meal_protein - 5.0)
        parts.append(_scale_to_macro(protein_slug, prot_target, "protein"))
        weekly_counts[protein_slug] += 1

    # Staple: scale to the meal's carb target.
    if staple_slug and meal_carbs > 0:
        parts.append(_scale_to_macro(staple_slug, meal_carbs, "carbs"))
        weekly_counts[staple_slug] += 1

    # Veg: fixed 150 g (main) + 100 g (second).
    if veg_slug:
        parts.append(_fixed_portion(veg_slug, 150))
        weekly_counts[veg_slug] += 1
    if second_veg_slug:
        parts.append(_fixed_portion(second_veg_slug, 100))
        weekly_counts[second_veg_slug] += 1

    # Fat: scale to remaining fat grams, capped at the food's typical serving.
    if fat_slug:
        remaining_fat = max(0.0, meal_fat - sum(p["fat_g"] for p in parts))
        if remaining_fat >= 2:
            portion = _scale_to_macro(fat_slug, remaining_fat, "fat")
            # Nuts/seeds: cap at 30 g per meal — nutrient-dense.
            if portion["grams"] > 30:
                portion = _fixed_portion(fat_slug, 30)
            if portion["grams"] > 0:
                parts.append(portion)
                weekly_counts[fat_slug] += 1

    total = _sum_portion(parts)
    return {
        "meal_type": meal_type,
        "target_kcal": round(meal_kcal, 1),
        "target_protein_g": round(meal_protein, 1),
        "target_carbs_g": round(meal_carbs, 1),
        "target_fat_g": round(meal_fat, 1),
        "bucket_hints": bucket_hints,
        "parts": parts,
        "totals": total,
    }


# ── Spec-v1: incremental slot filler ─────────────────────────────────────────

# Snack's slice of a day's kcal when opt-in. Chosen low because _compose_meal
# wasn't designed for snacks — this just keeps the protein/veg/staple solver
# from producing a second dinner on days the user requested a snack slot.
_SNACK_SHARE = 0.10


def _resolve_day_type(db: Session, user_id: int, date_str: str) -> str:
    """Day-type for a single date. Mirrors `_calendar_for_week`'s per-day
    logic without running the full week-wide reinforcement pass — a single
    empty-slot fill doesn't know about the surrounding week."""
    activity, _ = _resolve_activity_for_day(db, user_id, date_str)
    return _ACTIVITY_TO_DAY_TYPE.get(activity, "moderate_activity")


def _recipe_to_meal_slot(recipe: models.Recipe, date_str: str, meal_type: str) -> pc.MealSlot:
    return pc.MealSlot(
        date=date_str,
        meal_type=meal_type,
        status=pc.SLOT_STATUS_RECIPE,
        source_id=recipe.id,
        totals=pc.NutritionTarget(
            calories=float(recipe.calories or 0),
            protein =float(recipe.protein_g or 0),
            carbs   =float(recipe.carbs_g or 0),
            fat     =float(recipe.fat_g or 0),
        ),
    )


def _composed_to_meal_slot(
    composed: dict,
    date_str: str,
    meal_type: str,
    lang: str,
) -> pc.MealSlot:
    name_key = "name_en" if lang == "en" else "name_zh"
    foods = [
        pc.MealSlotFood(
            name    =p.get(name_key) or p["slug"],
            grams   =float(p["grams"]),
            calories=float(p["kcal"]),
            protein =float(p["protein_g"]),
            carbs   =float(p["carbs_g"]),
            fat     =float(p["fat_g"]),
        )
        for p in composed.get("parts", [])
    ]
    t = composed.get("totals", {})
    return pc.MealSlot(
        date=date_str,
        meal_type=meal_type,
        status=pc.SLOT_STATUS_GENERATED,
        source_id=None,
        foods=foods,
        totals=pc.NutritionTarget(
            calories=float(t.get("kcal", 0) or 0),
            protein =float(t.get("protein_g", 0) or 0),
            carbs   =float(t.get("carbs_g", 0) or 0),
            fat     =float(t.get("fat_g", 0) or 0),
        ),
    )


# ── Day-type → quota bucket ──────────────────────────────────────────────────
# `red_meat_day` / `deep_sea_fish_day` bias the picker toward recipes that
# include the reinforcement bucket. Other day types pass no hint.
_DAY_TYPE_TO_QUOTA_BUCKET: dict[str, str] = {
    "red_meat_day":       "red_meat",
    "deep_sea_fish_day":  "deep_sea_fish",
}


def fill_empty_slots(
    db: Session,
    user: models.User,
    date_str: str,
    ctx: Optional[pc.DayPlanningContext] = None,
) -> list[pc.MealSlot]:
    """Return new `MealSlot`s for every empty meal type on (user, date).

    Spec-v1 (Phase 7): picker is **day-level**, not per-slot. We ask
    `recipe_matcher.pick_day_set` for k recipes that jointly approach the
    day's remaining target (lexicographic kcal > protein > carbs > fat),
    then assign them to empty slots by each recipe's `meal_types` tag with
    a kcal tiebreaker (lightest → breakfast, heaviest → dinner). This
    removes the prior `MEAL_SPLIT` per-slot calorie prescription, which
    was hard to hit with real-world recipes.

    The priority chain is enforced by `DayPlanningContext` upstream:
    recorded and fixed meals never appear in `ctx.empty_meal_types()`, so
    this function only ever touches the gaps. For slots the library can't
    cover (too few approved recipes with `ingredients_json`), the
    deterministic solver composes a `generated` slot from the user's
    library as a fallback.

    This function is pure — it does not persist. Callers (the route
    layer) write the results as `MealPlanEntry` rows with the returned
    `status` value.
    """
    if ctx is None:
        ctx = pc.build_context(db, user, date_str)

    empties = ctx.empty_meal_types()
    if not empties:
        return []

    day_type = _resolve_day_type(db, user.id, date_str)
    quota_hint = _DAY_TYPE_TO_QUOTA_BUCKET.get(day_type)
    lang = getattr(user, "language", "zh") or "zh"

    # 1. Day-level pick: k recipes for the k empty slots, jointly fitting
    #    the day's remaining target.
    picks = recipe_matcher.pick_day_set(
        db,
        ctx.remaining_target,
        k=len(empties),
        quota_hint=quota_hint,
        meal_type_filter=empties,
    )

    # 2. Assign picks to slots via meal_types tag + kcal tiebreaker.
    assignments = recipe_matcher.assign_picks_to_slots(picks, empties)

    # 3. Any slot the library couldn't cover falls through to the
    #    deterministic solver below.
    inventory = ctx.available_ingredients
    classification: dict[str, list[str]] = {b: [] for b in FL.EXECUTION_BUCKETS}
    for slug in inventory:
        entry = FL.FOOD_LIBRARY.get(slug)
        if not entry:
            continue
        for bucket in entry["execution_buckets"]:
            classification[bucket].append(slug)

    weekly_counts: Counter = Counter()

    new_slots: list[pc.MealSlot] = []
    for mt in empties:
        recipe = assignments.get(mt)
        if recipe is not None:
            new_slots.append(_recipe_to_meal_slot(recipe, date_str, mt))
            continue

        # Library came up short for this slot — deterministic solver fills
        # it from the user's raw ingredient library. The solver internally
        # scales by MEAL_SPLIT[mt], which is fine for the fallback path;
        # it's still a day-shaped meal even if our main picker is day-level.
        day_target = {
            "calorie_target": ctx.daily_target.calories,
            "protein_g":      ctx.daily_target.protein,
            "carbs_g":        ctx.daily_target.carbs,
            "fat_g":          ctx.daily_target.fat,
        }
        compose_mt = mt if mt in MEAL_SPLIT else "lunch"
        composed = _compose_meal(
            compose_mt, day_type, day_target, classification, weekly_counts,
        )
        new_slots.append(_composed_to_meal_slot(composed, date_str, mt, lang))

    return new_slots


# ── Spec-v1: public week planner ─────────────────────────────────────────────


def _coverage_warnings(days: list[dict], slugs: list[str]) -> list[str]:
    """Non-mutating replacement for `_apply_weekly_floors`'s placement pass.

    The legacy planner inserted extra portions into lunch slots whenever a
    weekly_floor food fell short. Spec-v1 treats each slot as authored (fixed,
    recorded, or planned) and forbids post-hoc mutation — so we just count
    occurrences across the week and surface any deficits as warnings. The
    day-type calendar already biases red_meat/deep_sea_fish picks toward the
    reinforcement days, which covers the common case.
    """
    counts: Counter = Counter()
    for day in days:
        for meal in day["meals"].values():
            for part in meal.get("parts", []):
                counts[part["slug"]] += 1

    warnings: list[str] = []
    for slug in slugs:
        entry = FL.FOOD_LIBRARY.get(slug)
        if not entry:
            continue
        floor = entry.get("weekly_floor", 0)
        if floor <= 0 or counts[slug] >= floor:
            continue
        warnings.append(
            f"'{slug}' placed ×{counts[slug]} this week (weekly_floor={floor}). "
            f"Consider scheduling it explicitly."
        )
    return warnings


def week_plan(db: Session, user: models.User) -> dict:
    """Spec-v1 7-day planner — drop-in replacement for legacy `plan_week`.

    Differences from `plan_week`:
      * No `_apply_weekly_floors` post-hoc mutation. Day-type reinforcement
        still biases picks toward red_meat_day / deep_sea_fish_day; unmet
        floors surface as warnings instead of being patched into lunch.
      * Per-day targets come from `planning_context.daily_target_for_date`,
        which is the single source of truth that `fill_empty_slots` also
        uses (previously duplicated inline in plan_week).

    The output shape is byte-compatible with `plan_week` so the route-layer
    callers continue to work unchanged through the migration.
    """
    slugs = nutrition_audit.load_user_library(db, user.id)

    classification_full = {b: [] for b in FL.EXECUTION_BUCKETS}
    for slug in slugs:
        for bucket in FL.FOOD_LIBRARY[slug]["execution_buckets"]:
            classification_full[bucket].append(slug)
    val_coverage = {b: [] for b in FL.VALIDATION_BUCKETS}
    for slug in slugs:
        for bucket in FL.FOOD_LIBRARY[slug]["validation_buckets"]:
            val_coverage[bucket].append(slug)
    from services.nutrition_audit import _feasibility, _micronutrient_coverage, _sufficiency_check
    micro = _micronutrient_coverage(slugs)
    gender = getattr(getattr(user, "bmr_profile", None), "gender", "female") or "female"
    sufficiency = _sufficiency_check(slugs, gender)
    verdict = _feasibility(val_coverage, micro, sufficiency)

    if verdict["overall"] == "not_closed_loop":
        return {
            "feasibility": "not_closed_loop",
            "blocking_buckets": verdict["missing_blocking_buckets"],
            "message_zh": "当前食物库无法形成最小闭环，系统拒绝生成周菜单。",
            "message_en": (
                "The current closed library cannot form the minimum nutritional "
                "loop — menu generation is refused."
            ),
        }

    baseline = calorie_svc.build_daily_targets(db, user)
    if not baseline.get("has_bmr_profile"):
        return {
            "feasibility": "no_bmr",
            "message_zh": "请先完成身体基础数据（BMR）。",
            "message_en": "Please complete the BMR profile before planning.",
        }

    today = local_dates.app_now()
    week_rows = _calendar_for_week(db, user.id, today, classification_full)

    weekly_counts: Counter = Counter()
    days: list[dict] = []

    for row in week_rows:
        date_str = row["date"]
        day_type = row["day_type"]
        target = pc.daily_target_for_date(db, user, date_str)
        day_target = {
            "calorie_target": target.calories,
            "protein_g":      target.protein,
            "carbs_g":        target.carbs,
            "fat_g":          target.fat,
        }

        meals = {
            mt: _compose_meal(mt, day_type, day_target, classification_full, weekly_counts)
            for mt in ("breakfast", "lunch", "dinner")
        }

        day_totals = {
            "kcal":      round(sum(m["totals"]["kcal"]      for m in meals.values()), 1),
            "protein_g": round(sum(m["totals"]["protein_g"] for m in meals.values()), 1),
            "carbs_g":   round(sum(m["totals"]["carbs_g"]   for m in meals.values()), 1),
            "fat_g":     round(sum(m["totals"]["fat_g"]     for m in meals.values()), 1),
        }
        days.append({
            **row,
            "day_type_label_zh": DAY_TYPE_LABELS[day_type]["zh"],
            "day_type_label_en": DAY_TYPE_LABELS[day_type]["en"],
            "target": day_target,
            "meals": meals,
            "totals": day_totals,
        })

    warnings = _coverage_warnings(days, slugs)
    for gap in verdict.get("sufficiency_gaps", []):
        warnings.append(
            f"micronutrient sufficiency gap: {gap['role']} "
            f"({gap['status']}, best={gap['best_coverage_pct']}%)"
        )

    weekly_totals = {
        "kcal":      round(sum(d["totals"]["kcal"]      for d in days), 1),
        "protein_g": round(sum(d["totals"]["protein_g"] for d in days), 1),
        "carbs_g":   round(sum(d["totals"]["carbs_g"]   for d in days), 1),
        "fat_g":     round(sum(d["totals"]["fat_g"]     for d in days), 1),
    }

    requirement_days: list[dict] = []
    solved_days: list[dict] = []
    for day in days:
        req_meals = {
            mt: {
                "meal_type":        m["meal_type"],
                "target_kcal":      m["target_kcal"],
                "target_protein_g": m["target_protein_g"],
                "target_carbs_g":   m["target_carbs_g"],
                "target_fat_g":     m["target_fat_g"],
                "bucket_hints":     m["bucket_hints"],
            }
            for mt, m in day["meals"].items()
        }
        requirement_days.append({
            "date":               day["date"],
            "weekday":            day["weekday"],
            "activity_level":     day["activity_level"],
            "activity_is_logged": day["activity_is_logged"],
            "day_type":           day["day_type"],
            "day_type_label_zh":  day["day_type_label_zh"],
            "day_type_label_en":  day["day_type_label_en"],
            "target":             day["target"],
            "meals":              req_meals,
        })
        solved_days.append({
            "date":           day["date"],
            "day_type":       day["day_type"],
            "activity_level": day["activity_level"],
            "target":         day["target"],
            "meals": {
                mt: {
                    "meal_type":        m["meal_type"],
                    "target_kcal":      m["target_kcal"],
                    "target_protein_g": m["target_protein_g"],
                    "target_carbs_g":   m["target_carbs_g"],
                    "target_fat_g":     m["target_fat_g"],
                    "parts":            m["parts"],
                    "totals":           m["totals"],
                }
                for mt, m in day["meals"].items()
            },
            "totals": day["totals"],
        })

    weekly_totals_target = {
        "kcal":      round(sum(d["target"]["calorie_target"] for d in days), 1),
        "protein_g": round(sum(d["target"]["protein_g"]      for d in days), 1),
        "carbs_g":   round(sum(d["target"]["carbs_g"]        for d in days), 1),
        "fat_g":     round(sum(d["target"]["fat_g"]          for d in days), 1),
    }

    return {
        "feasibility": verdict["overall"],
        "start_date":  today.strftime("%Y-%m-%d"),
        "targets_baseline": {
            "calorie_target":      baseline["calorie_target"],
            "protein_g":           baseline["protein_g"],
            "carbs_g":             baseline["carbs_g"],
            "fat_g":               baseline["fat_g"],
            "activity_level":      baseline["activity_level"],
            "activity_is_default": baseline["activity_is_default"],
        },
        "nutrition_requirements": {
            "days": requirement_days,
            "weekly_totals_target": weekly_totals_target,
        },
        "solved_picks": {
            "days":          solved_days,
            "weekly_totals": weekly_totals,
            "forced_slots":  [],
            "warnings":      warnings,
        },
    }


# ── Dish pool generation ─────────────────────────────────────────────────────

# Pool targets
_BREAKFAST_POOL_SIZE   = 6
_MAIN_POOL_SIZE        = 24   # lunch + dinner combined (user decides assignment)
_SUPPLEMENT_BREAKFAST_POOL_SIZE = 2
_SUPPLEMENT_MAIN_POOL_SIZE = 8
# Per the design spec: no ingredient may appear in more than floor(pool_size/5)
# dishes within its type group (breakfast or main).
# For main pool of 24: floor(24/5) = 4  →  ≤4/24 ≈ 17 %
# For breakfast pool of 6: floor(6/5) = 1 → ≤1/6 ≈ 17 %

# Day-type affinities for the main pool: which day types each dish sketch suits.
# Sketches are labelled so the frontend can surface contextual hints
# ("good for red-meat day") without forcing assignment.
_DAY_TYPE_AFFINITY: dict[str, list[str]] = {
    "red_meat_day":       ["red_meat"],
    "deep_sea_fish_day":  ["deep_sea_fish"],
    "low_activity":       ["slow_carb_staple"],
    "high_activity":      ["fast_carb_staple"],
    "moderate_activity":  [],
    "pantry_clearance":   [],
}


def _ingredient_fingerprint(parts: list[dict]) -> frozenset[str]:
    return frozenset(p["slug"] for p in parts)


def _diversity_ok(
    slug_counts: Counter,
    parts: list[dict],
    pool_size: int,
) -> bool:
    """Return False if adding these parts would push any ingredient above
    floor(pool_size / 5) appearances in the current pool."""
    cap = max(1, pool_size // 5)
    for p in parts:
        if slug_counts.get(p["slug"], 0) + 1 > cap:
            return False
    return True


def _sketch_day_type_affinities(parts: list[dict]) -> list[str]:
    """Return which day types this dish is particularly well suited for."""
    slugs_in_dish = {p["slug"] for p in parts}
    result: list[str] = []
    for day_type, preferred_buckets in _DAY_TYPE_AFFINITY.items():
        if not preferred_buckets:
            continue
        for slug in slugs_in_dish:
            entry = FL.FOOD_LIBRARY.get(slug)
            if entry and set(entry["execution_buckets"]) & set(preferred_buckets):
                result.append(day_type)
                break
    return result


def _pool_source_label(source: str) -> str:
    return {
        "generated": "Generated",
        "recipe_library": "Recipe library",
        "supplement": "Supplement",
    }.get(source, source or "Generated")


def _stamp_pool_source(dish: dict, source: str) -> dict:
    stamped = dict(dish)
    stamped["source"] = source
    stamped["source_label"] = _pool_source_label(source)
    return stamped


def generate_dish_pool(db: Session, user: models.User, variant: int = 0) -> dict:
    """Generate a pool of ~30 candidate dishes for the user to choose from.

    Returns:
      {
        "feasibility": str,
        "targets_baseline": {...},
        "week_skeleton": [...],   # 7 locked/free day-type hints
        "breakfast_pool": [...],  # 5-6 dishes
        "main_pool":      [...],  # 24-25 lunch/dinner dishes
      }

    Each dish in the pool:
      {
        "sketch_id": str,
        "meal_type": "breakfast" | "main",
        "day_type_affinities": [...],
        "parts": [...],          # ingredient list with grams + macros
        "totals": {...},         # kcal, protein_g, carbs_g, fat_g
        "ingredient_slugs": [...],
      }
    """
    slugs = nutrition_audit.load_user_library(db, user.id)
    classification_full = {b: [] for b in FL.EXECUTION_BUCKETS}
    for slug in slugs:
        for bucket in FL.FOOD_LIBRARY[slug]["execution_buckets"]:
            classification_full[bucket].append(slug)

    val_coverage = {b: [] for b in FL.VALIDATION_BUCKETS}
    for slug in slugs:
        for bucket in FL.FOOD_LIBRARY[slug]["validation_buckets"]:
            val_coverage[bucket].append(slug)

    from services.nutrition_audit import _feasibility, _micronutrient_coverage, _sufficiency_check
    micro = _micronutrient_coverage(slugs)
    gender = getattr(getattr(user, "bmr_profile", None), "gender", "female") or "female"
    sufficiency = _sufficiency_check(slugs, gender)
    verdict = _feasibility(val_coverage, micro, sufficiency)

    if verdict["overall"] == "not_closed_loop":
        return {
            "feasibility": "not_closed_loop",
            "blocking_buckets": verdict["missing_blocking_buckets"],
            "message_zh": "当前食物库无法形成最小闭环，系统拒绝生成菜单池。",
            "message_en": "Closed library cannot form the minimum nutritional loop.",
        }

    baseline = calorie_svc.build_daily_targets(db, user)
    if not baseline.get("has_bmr_profile"):
        return {
            "feasibility": "no_bmr",
            "message_zh": "请先完成身体基础数据（BMR）。",
            "message_en": "Please complete the BMR profile before generating a pool.",
        }

    # Use moderate-activity macro targets as the pool reference baseline.
    bmr = calorie_svc.compute_bmr(
        user.bmr_profile.age, user.bmr_profile.gender,
        user.bmr_profile.height_cm, user.bmr_profile.weight_kg,
    )
    tdee = calorie_svc.compute_tdee(bmr, "moderately_active")
    kcal, _ = calorie_svc.compute_calorie_target(user.bmr_profile.goal, tdee, bmr)
    macros = calorie_svc.compute_macros(
        calories=kcal,
        weight_kg=user.bmr_profile.weight_kg,
        gender=user.bmr_profile.gender,
        age=user.bmr_profile.age,
        goal=user.bmr_profile.goal,
        is_exerciser=True,
    )
    day_target = {
        "calorie_target": macros["calories"],
        "protein_g": macros["protein_g"],
        "carbs_g": macros["carbs_g"],
        "fat_g": macros["fat_g"],
    }

    # Week skeleton: 7-day day-type hints with locked/free flag.
    today = local_dates.app_now()
    week_rows = _calendar_for_week(db, user.id, today, classification_full)
    required_slot_counts, _ = _week_slot_requirements(db, user, week_rows, ignore_planned=True)
    week_skeleton = [
        {
            "date": row["date"],
            "weekday": row["weekday"],
            "day_type": row["day_type"],
            "day_type_label_zh": DAY_TYPE_LABELS[row["day_type"]]["zh"],
            "day_type_label_en": DAY_TYPE_LABELS[row["day_type"]]["en"],
            "is_locked": row["day_type"] in ("red_meat_day", "deep_sea_fish_day"),
        }
        for row in week_rows
    ]

    variant = max(int(variant or 0), 0)

    # ── Build breakfast pool ──────────────────────────────────────────────────
    breakfast_pool: list[dict] = []
    bkfst_slug_counts: Counter = Counter()
    bkfst_seen_fingerprints: set[frozenset] = set()

    # Rotate through protein buckets to diversify (egg, dairy, soy, white meat)
    bkfst_protein_rotation = ["egg", "dairy", "soy_product", "lean_white_meat"]
    breakfast_rotation_offset = variant % len(bkfst_protein_rotation)
    bkfst_attempts = 0

    while len(breakfast_pool) < _BREAKFAST_POOL_SIZE and bkfst_attempts < 40:
        bkfst_attempts += 1
        # Vary which protein bucket we draw from
        rotation_idx = (len(breakfast_pool) + bkfst_attempts + breakfast_rotation_offset) % len(bkfst_protein_rotation)
        week_counts: Counter = Counter(bkfst_slug_counts)
        meal = _compose_meal(
            "breakfast", "moderate_activity", day_target,
            {**classification_full,
             "egg": classification_full.get(bkfst_protein_rotation[rotation_idx], [])
                    or classification_full.get("egg", [])},
            week_counts,
        )
        fp = _ingredient_fingerprint(meal["parts"])
        if fp in bkfst_seen_fingerprints or not meal["parts"]:
            continue
        if not _diversity_ok(bkfst_slug_counts, meal["parts"], _BREAKFAST_POOL_SIZE):
            continue
        for p in meal["parts"]:
            bkfst_slug_counts[p["slug"]] += 1
        bkfst_seen_fingerprints.add(fp)
        breakfast_pool.append({
            "sketch_id": f"breakfast-{len(breakfast_pool)}",
            "meal_type": "breakfast",
            "source": "generated",
            "source_label": _pool_source_label("generated"),
            "day_type_affinities": [],
            "parts": meal["parts"],
            "totals": meal["totals"],
            "ingredient_slugs": sorted(fp),
        })

    # ── Build main pool (lunch + dinner combined) ─────────────────────────────
    main_pool: list[dict] = []
    main_slug_counts: Counter = Counter()
    main_seen_fingerprints: set[frozenset] = set()

    # Cycle through day types to ensure all dietary patterns are represented.
    day_type_cycle = [
        "moderate_activity", "low_activity", "high_activity",
        "red_meat_day", "deep_sea_fish_day", "moderate_activity",
        "low_activity", "high_activity", "red_meat_day", "pantry_clearance",
    ]
    day_type_offset = variant % len(day_type_cycle)
    main_attempts = 0

    while len(main_pool) < _MAIN_POOL_SIZE and main_attempts < 80:
        main_attempts += 1
        day_type = day_type_cycle[(main_attempts + day_type_offset) % len(day_type_cycle)]
        # Alternate lunch and dinner targets to vary macro proportions
        meal_type = "lunch" if (main_attempts + variant) % 2 == 0 else "dinner"
        week_counts: Counter = Counter(main_slug_counts)
        meal = _compose_meal(
            meal_type, day_type, day_target,
            classification_full, week_counts,
        )
        fp = _ingredient_fingerprint(meal["parts"])
        if fp in main_seen_fingerprints or not meal["parts"]:
            continue
        if not _diversity_ok(main_slug_counts, meal["parts"], _MAIN_POOL_SIZE):
            continue
        for p in meal["parts"]:
            main_slug_counts[p["slug"]] += 1
        main_seen_fingerprints.add(fp)
        main_pool.append({
            "sketch_id": f"main-{len(main_pool)}",
            "meal_type": "main",
            "source": "generated",
            "source_label": _pool_source_label("generated"),
            "day_type_affinities": _sketch_day_type_affinities(meal["parts"]),
            "parts": meal["parts"],
            "totals": meal["totals"],
            "ingredient_slugs": sorted(fp),
        })

    return {
        "feasibility": verdict["overall"],
        "targets_baseline": {
            "calorie_target": day_target["calorie_target"],
            "protein_g": day_target["protein_g"],
            "carbs_g": day_target["carbs_g"],
            "fat_g": day_target["fat_g"],
        },
        "variant": variant,
        "week_skeleton": week_skeleton,
        "required_slot_counts": required_slot_counts,
        "requires_breakfast_pool": required_slot_counts["breakfast"] > 0,
        "requires_main_pool": (required_slot_counts["lunch"] + required_slot_counts["dinner"]) > 0,
        "breakfast_pool": breakfast_pool,
        "main_pool": main_pool,
    }


def _target_for_pool_generation(db: Session, user: models.User) -> dict | None:
    baseline = calorie_svc.build_daily_targets(db, user)
    if not baseline.get("has_bmr_profile"):
        return None
    bmr = calorie_svc.compute_bmr(
        user.bmr_profile.age,
        user.bmr_profile.gender,
        user.bmr_profile.height_cm,
        user.bmr_profile.weight_kg,
    )
    tdee = calorie_svc.compute_tdee(bmr, "moderately_active")
    kcal, _ = calorie_svc.compute_calorie_target(user.bmr_profile.goal, tdee, bmr)
    macros = calorie_svc.compute_macros(
        calories=kcal,
        weight_kg=user.bmr_profile.weight_kg,
        gender=user.bmr_profile.gender,
        age=user.bmr_profile.age,
        goal=user.bmr_profile.goal,
        is_exerciser=True,
    )
    return {
        "calorie_target": macros["calories"],
        "protein_g": macros["protein_g"],
        "carbs_g": macros["carbs_g"],
        "fat_g": macros["fat_g"],
    }


def _classification_for_slugs(slugs: list[str] | set[str]) -> dict[str, list[str]]:
    classification = {bucket: [] for bucket in FL.EXECUTION_BUCKETS}
    for slug in sorted({str(s).strip() for s in slugs if str(s).strip()}):
        entry = FL.FOOD_LIBRARY.get(slug)
        if not entry:
            continue
        for bucket in entry["execution_buckets"]:
            classification[bucket].append(slug)
    return classification


def _preferred_supplement_slugs(
    library_slugs: set[str],
    selected_food_slugs: list[str],
    missing_roles: list[str],
    required_buckets: list[str],
) -> list[str]:
    preferred: list[str] = []

    def add(slug: str) -> None:
        slug = str(slug or "").strip()
        if slug and slug in library_slugs and slug not in preferred:
            preferred.append(slug)

    for slug in selected_food_slugs:
        add(slug)
    for bucket in required_buckets:
        for slug in FL.slugs_by_execution_bucket(str(bucket)):
            add(slug)
            if len(preferred) >= 12:
                break
    for role in missing_roles:
        for slug in FL.slugs_by_micronutrient(str(role)):
            add(slug)
            if len(preferred) >= 12:
                break
    return preferred


def _supplement_day_type_for_slug(slug: str, required_buckets: list[str]) -> str:
    buckets = set(FL.FOOD_LIBRARY.get(slug, {}).get("execution_buckets", []))
    required = set(required_buckets or [])
    if "red_meat" in buckets or "red_meat" in required:
        return "red_meat_day"
    if "deep_sea_fish" in buckets or "deep_sea_fish" in required:
        return "deep_sea_fish_day"
    if "slow_carb_staple" in buckets:
        return "low_activity"
    if "fast_carb_staple" in buckets:
        return "high_activity"
    return "moderate_activity"


def _add_preferred_food(meal: dict, preferred_slug: str, meal_type: str) -> dict:
    preferred_slug = str(preferred_slug or "").strip()
    if not preferred_slug or preferred_slug not in FL.FOOD_LIBRARY:
        return meal
    parts = list(meal.get("parts") or [])
    if any(part.get("slug") == preferred_slug for part in parts):
        return meal

    entry = FL.FOOD_LIBRARY[preferred_slug]
    buckets = set(entry.get("execution_buckets", []))
    max_g = float(entry.get("max_practical_serving_g") or 100.0)
    if entry.get("primary_macro") == "fat" or "nut_seed_functional" in buckets:
        grams = min(30.0, max_g)
    elif buckets & {"dark_leafy_green", "cruciferous_fungi_algae"}:
        grams = min(100.0, max_g)
    elif meal_type == "breakfast":
        grams = min(80.0, max_g)
    else:
        grams = min(120.0, max_g)
    if grams <= 0:
        return meal

    parts.append(_fixed_portion(preferred_slug, grams))
    meal = dict(meal)
    meal["parts"] = parts
    meal["totals"] = _sum_portion(parts)
    return meal


def generate_supplement_pool(
    db: Session,
    user: models.User,
    *,
    selected_food_slugs: list[str] | None = None,
    missing_roles: list[str] | None = None,
    required_buckets: list[str] | None = None,
    variant: int = 0,
) -> dict:
    selected_food_slugs = selected_food_slugs or []
    missing_roles = missing_roles or []
    required_buckets = required_buckets or []

    library_slugs = {
        slug for slug in nutrition_audit.load_user_library(db, user.id)
        if slug in FL.FOOD_LIBRARY
    }
    library_slugs.update(
        str(slug).strip()
        for slug in selected_food_slugs
        if str(slug).strip() in FL.FOOD_LIBRARY
    )
    if not library_slugs:
        return {
            "feasibility": "not_closed_loop",
            "message_zh": "Current food library is empty.",
            "message_en": "The food library is empty, so a supplement pool cannot be created.",
        }

    day_target = _target_for_pool_generation(db, user)
    if day_target is None:
        return {
            "feasibility": "no_bmr",
            "message_zh": "Please complete the BMR profile before planning.",
            "message_en": "Please complete the BMR profile before planning.",
        }

    classification = _classification_for_slugs(library_slugs)
    preferred = _preferred_supplement_slugs(
        library_slugs,
        selected_food_slugs,
        missing_roles,
        required_buckets,
    )
    if not preferred:
        preferred = sorted(library_slugs)[:8]

    variant = max(int(variant or 0), 0)

    def build_group(group: str, size: int) -> list[dict]:
        pool: list[dict] = []
        seen: set[frozenset[str]] = set()
        counts: Counter = Counter()
        attempts = 0
        while len(pool) < size and attempts < size * 8:
            attempts += 1
            preferred_slug = preferred[(len(pool) + attempts + variant) % len(preferred)]
            meal_type = "breakfast" if group == "breakfast" else ("lunch" if attempts % 2 else "dinner")
            day_type = _supplement_day_type_for_slug(preferred_slug, required_buckets)
            meal = _compose_meal(meal_type, day_type, day_target, classification, Counter(counts))
            meal = _add_preferred_food(meal, preferred_slug, meal_type)
            parts = meal.get("parts") or []
            fp = _ingredient_fingerprint(parts)
            if not fp or fp in seen:
                continue
            seen.add(fp)
            for part in parts:
                counts[part["slug"]] += 1
            pool.append({
                "sketch_id": f"supplement-{group}-{len(pool)}",
                "meal_type": group,
                "source": "supplement",
                "source_label": _pool_source_label("supplement"),
                "day_type_affinities": _sketch_day_type_affinities(parts),
                "parts": parts,
                "totals": meal["totals"],
                "ingredient_slugs": sorted(fp),
            })
        return pool

    return {
        "feasibility": "ok",
        "variant": variant,
        "breakfast_pool": build_group("breakfast", _SUPPLEMENT_BREAKFAST_POOL_SIZE),
        "main_pool": build_group("main", _SUPPLEMENT_MAIN_POOL_SIZE),
        "warnings": [],
    }


# ── Pool arrangement (selected pool → weekly schedule) ────────────────────────

_MICRO_ROLE_TO_NUTRIENT_KEY: dict[str, str] = {
    "calcium": "calcium_mg",
    "iron": "iron_mg",
    "zinc": "zinc_mg",
    "iodine": "iodine_mcg",
    "selenium": "selenium_mcg",
    "vitamin_a": "vitamin_a_mcg",
    "vitamin_d": "vitamin_d_mcg",
    "vitamin_e": "vitamin_e_mg",
    "vitamin_k": "vitamin_k_mcg",
    "b12": "b12_mcg",
    "folate": "folate_mcg",
    "omega3": "omega3_g",
    "fiber": "fiber_g",
}

_CORE_MEAL_TYPES = ("breakfast", "lunch", "dinner")


def _week_slot_requirements(
    db: Session,
    user: models.User,
    week_rows: list[dict],
    *,
    ignore_planned: bool = False,
) -> tuple[dict[str, int], dict[str, pc.DayPlanningContext]]:
    counts = {meal_type: 0 for meal_type in _CORE_MEAL_TYPES}
    contexts: dict[str, pc.DayPlanningContext] = {}
    for row in week_rows:
        ctx = pc.build_context(db, user, row["date"])
        contexts[row["date"]] = ctx
        filled = {slot.meal_type for slot in ctx.fixed_meals + ctx.recorded_meals}
        if not ignore_planned:
            filled.update(slot.meal_type for slot in ctx.planned_meals)
        for meal_type in _CORE_MEAL_TYPES:
            if meal_type not in filled:
                counts[meal_type] += 1
    return counts, contexts


def _recipe_structured_ingredients(recipe: Optional[models.Recipe]) -> list[dict]:
    if recipe is None or not recipe.ingredients_json:
        return []
    try:
        raw_items = json.loads(recipe.ingredients_json)
    except Exception:
        return []
    ingredients: list[dict] = []
    for raw in raw_items or []:
        if not isinstance(raw, dict):
            continue
        slug = str(raw.get("slug") or "").strip()
        if not slug:
            continue
        grams = round(float(raw.get("grams") or 0), 1)
        if grams <= 0:
            continue
        ingredients.append({"slug": slug, "grams": grams})
    return ingredients


def _recipe_slug_set(recipe: Optional[models.Recipe], *, ingredients: Optional[list[dict]] = None) -> set[str]:
    if ingredients:
        return {item["slug"] for item in ingredients if item.get("slug")}
    if recipe is None or not recipe.ingredient_slugs:
        return set()
    raw = str(recipe.ingredient_slugs or "").strip()
    if not raw:
        return set()
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = [token.strip() for token in raw.split(",")]
    return {
        str(item).strip()
        for item in (parsed or [])
        if str(item).strip()
    }


def _slot_recipe_ingredient_data(
    db: Session,
    slot: pc.MealSlot,
) -> tuple[set[str], dict[str, float], bool]:
    empty_nutrients = {role: 0.0 for role in FL.MICRONUTRIENT_ROLES}
    if slot.status == pc.SLOT_STATUS_RECORDED:
        return set(), empty_nutrients, True

    recipe: Optional[models.Recipe] = None
    if slot.status == pc.SLOT_STATUS_FIXED:
        row = (
            db.query(models.UserFixedMeal)
            .filter(models.UserFixedMeal.id == slot.source_id)
            .first()
        )
        recipe = row.recipe if row else None
    elif slot.status in (pc.SLOT_STATUS_RECIPE, pc.SLOT_STATUS_GENERATED):
        row = (
            db.query(models.MealPlanEntry)
            .filter(models.MealPlanEntry.id == slot.source_id)
            .first()
        )
        recipe = row.recipe if row else None

    ingredients = _recipe_structured_ingredients(recipe)
    slugs = _recipe_slug_set(recipe, ingredients=ingredients)
    nutrients = _sum_ingredient_nutrients(ingredients) if ingredients else empty_nutrients
    return slugs, nutrients, False


def _sum_ingredient_macros(ingredients: list[dict]) -> dict[str, float]:
    kcal = protein = carbs = fat = 0.0
    for ing in ingredients:
        slug = ing.get("slug")
        grams = float(ing.get("grams") or 0)
        entry = FL.FOOD_LIBRARY.get(slug)
        if not entry or grams <= 0:
            continue
        factor = grams / 100.0
        kcal += entry["kcal_per_100g"] * factor
        protein += entry["protein_per_100g"] * factor
        carbs += entry["carbs_per_100g"] * factor
        fat += entry["fat_per_100g"] * factor
    return {
        "kcal": round(kcal, 1),
        "protein_g": round(protein, 1),
        "carbs_g": round(carbs, 1),
        "fat_g": round(fat, 1),
    }


def _sum_ingredient_nutrients(ingredients: list[dict]) -> dict[str, float]:
    totals = {role: 0.0 for role in FL.MICRONUTRIENT_ROLES}
    for ing in ingredients:
        slug = ing.get("slug")
        grams = float(ing.get("grams") or 0)
        entry = FL.FOOD_LIBRARY.get(slug)
        if not entry or grams <= 0:
            continue
        factor = grams / 100.0
        nutrients = entry.get("nutrients", {})
        for role, key in _MICRO_ROLE_TO_NUTRIENT_KEY.items():
            totals[role] += float(nutrients.get(key, 0) or 0) * factor
    return {role: round(value, 2) for role, value in totals.items()}


def _display_name(slug: str, language: str) -> str:
    return FL.display_name(slug, "en" if language == "en" else "zh") or slug


def _missing_micronutrient_guidance(weekly_micro_report: dict[str, dict]) -> dict[str, list[dict]]:
    missing_micronutrients: list[dict] = []
    recommended_index: dict[str, dict] = {}

    for role, info in weekly_micro_report.items():
        if info.get("status") != "missing":
            continue

        carriers = [str(slug) for slug in info.get("carriers", []) if str(slug).strip()]
        recommended_foods: list[dict] = []
        for slug in FL.slugs_by_micronutrient(role):
            if slug in carriers:
                continue

            role_meta = FL.MICRONUTRIENT_ROLES[role]
            rec = {
                "slug": slug,
                "name_zh": FL.display_name(slug, "zh"),
                "name_en": FL.display_name(slug, "en"),
                "roles": [role],
                "role_labels_zh": [role_meta["zh"]],
                "role_labels_en": [role_meta["en"]],
            }
            recommended_foods.append(rec)

            existing = recommended_index.get(slug)
            if existing is None:
                recommended_index[slug] = {
                    "slug": slug,
                    "name_zh": rec["name_zh"],
                    "name_en": rec["name_en"],
                    "roles": [role],
                    "role_labels_zh": [role_meta["zh"]],
                    "role_labels_en": [role_meta["en"]],
                }
            elif role not in existing["roles"]:
                existing["roles"].append(role)
                existing["role_labels_zh"].append(role_meta["zh"])
                existing["role_labels_en"].append(role_meta["en"])

            if len(recommended_foods) >= 6:
                break

        missing_micronutrients.append({
            "role": role,
            "label_zh": info.get("label_zh", role),
            "label_en": info.get("label_en", role),
            "unit": info.get("unit", ""),
            "actual": round(float(info.get("actual", 0) or 0), 2),
            "target": round(float(info.get("target", 0) or 0), 2),
            "gap": round(max(0.0, float(info.get("target", 0) or 0) - float(info.get("actual", 0) or 0)), 2),
            "carriers": carriers,
            "recommended_foods": recommended_foods,
        })

    recommended_foods = sorted(
        recommended_index.values(),
        key=lambda item: (-len(item["roles"]), item["slug"]),
    )
    return {
        "missing_micronutrients": missing_micronutrients,
        "recommended_foods": recommended_foods,
    }


def _execution_bucket_guidance(required_buckets: set[str]) -> list[dict]:
    recommended: dict[str, dict] = {}
    for bucket in sorted(required_buckets):
        label = FL.EXECUTION_BUCKET_LABELS.get(bucket, {"zh": bucket, "en": bucket})
        for slug in FL.slugs_by_execution_bucket(bucket)[:6]:
            recommended.setdefault(slug, {
                "slug": slug,
                "name_zh": FL.display_name(slug, "zh"),
                "name_en": FL.display_name(slug, "en"),
                "roles": [bucket],
                "role_labels_zh": [label["zh"]],
                "role_labels_en": [label["en"]],
            })
    return list(recommended.values())


def _ingredient_text(ingredients: list[dict], language: str) -> str:
    lines: list[str] = []
    for ing in ingredients:
        slug = str(ing.get("slug") or "").strip()
        grams = round(float(ing.get("grams") or 0), 1)
        if not slug or grams <= 0:
            continue
        lines.append(f"{_display_name(slug, language)} {grams}g")
    return "\n".join(lines)


def _required_buckets_for_day(day_type: str) -> set[str]:
    return {
        "red_meat_day": {"red_meat"},
        "deep_sea_fish_day": {"deep_sea_fish"},
    }.get(day_type, set())


def _normalize_selected_dish(
    dish: dict,
    expected_meal_type: str,
    *,
    language: str,
    library_slugs: set[str],
) -> dict:
    if not isinstance(dish, dict):
        raise ValueError("dish must be an object")

    name = str(dish.get("name") or "").strip()
    if not name:
        raise ValueError("dish name is required")

    raw_recipe_id = dish.get("recipe_id")
    recipe_id: Optional[int] = None
    if raw_recipe_id is not None:
        try:
            recipe_id = int(raw_recipe_id)
        except (TypeError, ValueError):
            raise ValueError(f"{name}: invalid recipe_id")
        if recipe_id <= 0:
            raise ValueError(f"{name}: invalid recipe_id")
    source = str(dish.get("source") or ("recipe_library" if recipe_id else "generated")).strip()
    if source not in {"generated", "recipe_library", "supplement"}:
        source = "generated"

    raw_ingredients = dish.get("ingredients") or dish.get("ingredients_json") or []
    if not isinstance(raw_ingredients, list) or not raw_ingredients:
        raise ValueError(f"{name}: ingredients are required")

    ingredients: list[dict] = []
    for raw in raw_ingredients:
        if not isinstance(raw, dict):
            raise ValueError(f"{name}: invalid ingredient entry")
        slug = str(raw.get("slug") or "").strip()
        grams = round(float(raw.get("grams") or 0), 1)
        if not slug or grams <= 0:
            raise ValueError(f"{name}: invalid ingredient grams")
        if slug not in library_slugs:
            raise ValueError(f"{name}: ingredient '{slug}' is outside the user's library")
        ingredients.append({"slug": slug, "grams": grams})

    ingredient_slugs = sorted({item["slug"] for item in ingredients})
    bucket_set = {
        bucket
        for slug in ingredient_slugs
        for bucket in FL.FOOD_LIBRARY.get(slug, {}).get("execution_buckets", [])
    }
    day_type_affinities = sorted({
        str(v)
        for v in (dish.get("day_type_affinities") or [])
        if isinstance(v, str) and v in DAY_TYPES
    })
    method_steps = str(dish.get("method_steps") or "").strip()
    seasonings = [
        {
            "name": str(s.get("name", "")).strip(),
            "grams": round(float(s.get("grams") or 0), 1),
        }
        for s in (dish.get("seasonings") or [])
        if isinstance(s, dict) and str(s.get("name", "")).strip()
    ]
    totals = _sum_ingredient_macros(ingredients)
    nutrients = _sum_ingredient_nutrients(ingredients)
    signature = (
        name,
        expected_meal_type,
        tuple((item["slug"], item["grams"]) for item in ingredients),
    )
    return {
        "dish_id": str(dish.get("dish_id") or f"{expected_meal_type}:{len(ingredient_slugs)}:{name}"),
        "meal_type": expected_meal_type,
        "source": source,
        "source_label": str(dish.get("source_label") or _pool_source_label(source)),
        "recipe_id": recipe_id,
        "name": name,
        "ingredients": ingredients,
        "ingredients_text": _ingredient_text(ingredients, language),
        "ingredient_slugs": ingredient_slugs,
        "day_type_affinities": day_type_affinities,
        "bucket_set": bucket_set,
        "totals": totals,
        "nutrients": nutrients,
        "seasonings": seasonings,
        "method_steps": method_steps,
        "signature": signature,
    }


def _main_combinations(main_dishes: list[dict], slots_needed: int) -> list[tuple[dict, ...]]:
    if slots_needed <= 0:
        return [tuple()]
    if not main_dishes:
        return []
    if slots_needed == 1:
        return [(dish,) for dish in main_dishes]
    if len(main_dishes) == 1:
        return [(main_dishes[0], main_dishes[0])]
    return list(product(main_dishes, repeat=slots_needed))


def _assign_main_slots(main_slots: list[str], picks: tuple[dict, ...]) -> dict[str, dict]:
    if not main_slots:
        return {}
    if len(main_slots) == 1:
        return {main_slots[0]: picks[0]}
    ordered_picks = sorted(
        picks,
        key=lambda item: (float(item["totals"]["kcal"]), item["name"]),
    )
    assignments: dict[str, dict] = {}
    if "lunch" in main_slots and "dinner" in main_slots:
        assignments["lunch"] = ordered_picks[0]
        assignments["dinner"] = ordered_picks[-1]
        return assignments
    for meal_type, pick in zip(main_slots, ordered_picks):
        assignments[meal_type] = pick
    return assignments


def _day_combo_score(
    picks: list[dict],
    *,
    remaining_target: pc.NutritionTarget,
    day_type: str,
    dish_usage: Counter,
    ingredient_usage: Counter,
    nutrient_progress: dict[str, float],
    weekly_targets: dict[str, float],
) -> float:
    totals = {
        "kcal": sum(item["totals"]["kcal"] for item in picks),
        "protein_g": sum(item["totals"]["protein_g"] for item in picks),
        "carbs_g": sum(item["totals"]["carbs_g"] for item in picks),
        "fat_g": sum(item["totals"]["fat_g"] for item in picks),
    }
    score = 0.0
    score += abs(totals["kcal"] - remaining_target.calories)
    score += abs(totals["protein_g"] - remaining_target.protein) * 8.0
    score += abs(totals["carbs_g"] - remaining_target.carbs) * 3.5
    score += abs(totals["fat_g"] - remaining_target.fat) * 5.0

    for dish in picks:
        score += dish_usage[dish["signature"]] * 60.0
    for dish in picks:
        for slug in dish["ingredient_slugs"]:
            score += max(0, ingredient_usage[slug] - 1) * 10.0

    required_buckets = _required_buckets_for_day(day_type)
    if required_buckets:
        if not any(dish["bucket_set"] & required_buckets for dish in picks):
            score += 100000.0
    else:
        score -= sum(10.0 for dish in picks if day_type in dish["day_type_affinities"])

    nutrient_bonus = 0.0
    for role, target in weekly_targets.items():
        if target <= 0:
            continue
        remaining = max(0.0, target - nutrient_progress.get(role, 0.0))
        if remaining <= 0:
            continue
        contribution = sum(dish["nutrients"].get(role, 0.0) for dish in picks)
        nutrient_bonus += min(contribution, remaining) / target
    score -= nutrient_bonus * 300.0
    return score


def _slot_payload_from_context_slot(slot: pc.MealSlot, language: str) -> dict:
    source = slot.status
    label = {
        pc.SLOT_STATUS_FIXED: "Fixed meal" if language == "en" else "固定餐",
        pc.SLOT_STATUS_RECORDED: "Logged meal" if language == "en" else "已记录餐食",
        pc.SLOT_STATUS_RECIPE: "Planned meal" if language == "en" else "已排餐",
        pc.SLOT_STATUS_GENERATED: "Generated meal" if language == "en" else "生成餐食",
    }.get(source, slot.meal_type)
    return {
        "meal_type": slot.meal_type,
        "source": source,
        "status": source,
        "name": label,
        "totals": {
            "kcal": round(float(slot.totals.calories or 0), 1),
            "protein_g": round(float(slot.totals.protein or 0), 1),
            "carbs_g": round(float(slot.totals.carbs or 0), 1),
            "fat_g": round(float(slot.totals.fat or 0), 1),
        },
        "ingredients": [],
        "seasonings": [],
        "method_steps": "",
        "day_type_affinities": [],
    }


def _ctx_payloads(ctx: pc.DayPlanningContext, language: str) -> dict[str, dict]:
    chosen: dict[str, pc.MealSlot] = {}
    for slot in ctx.fixed_meals + ctx.planned_meals + ctx.recorded_meals:
        current = chosen.get(slot.meal_type)
        current_priority = pc.SLOT_PRIORITY.get(current.status, -1) if current else -1
        incoming_priority = pc.SLOT_PRIORITY.get(slot.status, -1)
        if incoming_priority >= current_priority:
            chosen[slot.meal_type] = slot
    return {
        meal_type: _slot_payload_from_context_slot(slot, language)
        for meal_type, slot in chosen.items()
    }


def arrange_selected_pool(
    db: Session,
    user: models.User,
    breakfast_dishes: list[dict],
    main_dishes: list[dict],
) -> dict:
    language = getattr(user, "language", "zh") or "zh"
    library_slugs = set(nutrition_audit.load_user_library(db, user.id))
    if not library_slugs:
        return {
            "error": "not_closed_loop",
            "message_zh": "当前食物库为空，无法生成一周餐单。",
            "message_en": "The food library is empty, so a weekly plan cannot be created.",
        }

    baseline = calorie_svc.build_daily_targets(db, user)
    if not baseline.get("has_bmr_profile"):
        return {
            "error": "no_bmr",
            "message_zh": "请先完成 BMR 档案。",
            "message_en": "Please complete the BMR profile before planning.",
        }

    try:
        breakfast_pool = [
            _normalize_selected_dish(item, "breakfast", language=language, library_slugs=library_slugs)
            for item in breakfast_dishes
        ]
        main_pool = [
            _normalize_selected_dish(item, "main", language=language, library_slugs=library_slugs)
            for item in main_dishes
        ]
    except ValueError as exc:
        return {
            "error": "invalid_selection",
            "message_zh": f"候选菜选择无效：{exc}",
            "message_en": f"Invalid selected dish payload: {exc}",
        }

    classification = {bucket: [] for bucket in FL.EXECUTION_BUCKETS}
    for slug in sorted(library_slugs):
        entry = FL.FOOD_LIBRARY.get(slug)
        if not entry:
            continue
        for bucket in entry["execution_buckets"]:
            classification[bucket].append(slug)

    start_date = local_dates.app_now()
    week_rows = _calendar_for_week(db, user.id, start_date, classification)
    required_slot_counts, context_by_date = _week_slot_requirements(db, user, week_rows)
    locked_requirements = {
        row["day_type"]: _required_buckets_for_day(row["day_type"])
        for row in week_rows
        if _required_buckets_for_day(row["day_type"])
        and any(
            meal_type in ("lunch", "dinner")
            for meal_type in context_by_date[row["date"]].empty_meal_types()
        )
    }
    for day_type, required_buckets in locked_requirements.items():
        if not any(dish["bucket_set"] & required_buckets for dish in main_pool):
            label = DAY_TYPE_LABELS[day_type]["zh"] if language != "en" else DAY_TYPE_LABELS[day_type]["en"]
            return {
                "error": "selection_cannot_cover_reinforcement_day",
                "message_zh": f"当前主菜池无法覆盖“{label}”所需的食材类型，请保留对应主菜后再试。",
                "message_en": f"The selected main-dish pool cannot satisfy the required ingredient type for '{label}'.",
                "required_buckets": sorted(required_buckets),
                "recommended_foods": _execution_bucket_guidance(required_buckets),
            }

    gender = getattr(getattr(user, "bmr_profile", None), "gender", "female") or "female"
    weekly_micro_targets = {
        role: nutrition_audit.rda_for_gender(meta, gender, 0.0) * 7.0
        for role, meta in FL.MICRONUTRIENT_ROLES.items()
    }

    planning_order = sorted(
        week_rows,
        key=lambda row: (0 if _required_buckets_for_day(row["day_type"]) else 1, row["date"]),
    )

    ingredient_usage: Counter = Counter()
    dish_usage: Counter = Counter()
    weekly_micro_actual = {role: 0.0 for role in FL.MICRONUTRIENT_ROLES}
    weekly_micro_carriers = {role: set() for role in FL.MICRONUTRIENT_ROLES}
    arranged_by_date: dict[str, dict] = {}
    warnings: list[str] = []
    has_unstructured_recorded_slots = False
    slot_ingredient_cache: dict[tuple[str, Optional[int]], tuple[set[str], dict[str, float], bool]] = {}

    for row in planning_order:
        date_str = row["date"]
        ctx = context_by_date[date_str]
        empty_slots = [mt for mt in ctx.empty_meal_types() if mt in _CORE_MEAL_TYPES]
        meal_payloads = _ctx_payloads(ctx, language)

        for slot in ctx.fixed_meals + ctx.recorded_meals + ctx.planned_meals:
            cache_key = (slot.status, slot.source_id)
            cached = slot_ingredient_cache.get(cache_key)
            if cached is None:
                cached = _slot_recipe_ingredient_data(db, slot)
                slot_ingredient_cache[cache_key] = cached
            slot_slugs, slot_nutrients, slot_unstructured_record = cached
            has_unstructured_recorded_slots = has_unstructured_recorded_slots or bool(slot_unstructured_record)
            for role in FL.MICRONUTRIENT_ROLES:
                weekly_micro_actual[role] += float(slot_nutrients.get(role, 0.0) or 0.0)
                if slot_slugs:
                    weekly_micro_carriers[role].update(
                        slug
                        for slug in slot_slugs
                        if role in {FL._strip_tier(r) for r in FL.FOOD_LIBRARY.get(slug, {}).get("micronutrient_roles", [])}
                    )

        if not empty_slots:
            arranged_totals = pc.sum_totals(ctx.fixed_meals + ctx.recorded_meals + ctx.planned_meals)
            arranged_by_date[date_str] = {
                **row,
                "day_type_label_zh": DAY_TYPE_LABELS[row["day_type"]]["zh"],
                "day_type_label_en": DAY_TYPE_LABELS[row["day_type"]]["en"],
                "target": {
                    "calorie_target": round(ctx.daily_target.calories, 1),
                    "protein_g": round(ctx.daily_target.protein, 1),
                    "carbs_g": round(ctx.daily_target.carbs, 1),
                    "fat_g": round(ctx.daily_target.fat, 1),
                },
                "remaining_target": {
                    "calorie_target": round(ctx.remaining_target.calories, 1),
                    "protein_g": round(ctx.remaining_target.protein, 1),
                    "carbs_g": round(ctx.remaining_target.carbs, 1),
                    "fat_g": round(ctx.remaining_target.fat, 1),
                },
                "meals": meal_payloads,
                "totals": {
                    "kcal": round(arranged_totals.calories, 1),
                    "protein_g": round(arranged_totals.protein, 1),
                    "carbs_g": round(arranged_totals.carbs, 1),
                    "fat_g": round(arranged_totals.fat, 1),
                },
            }
            continue

        breakfast_needed = "breakfast" in empty_slots
        main_slots = [slot for slot in empty_slots if slot in ("lunch", "dinner")]

        breakfast_options = breakfast_pool if breakfast_needed else [None]
        main_options = _main_combinations(main_pool, len(main_slots))
        if breakfast_needed and not breakfast_options:
            return {
                "error": "breakfast_pool_empty",
                "message_zh": "当前早餐池为空，无法完成排餐。",
                "message_en": "The breakfast pool is empty, so the week cannot be arranged.",
            }
        if len(main_slots) and not main_options:
            return {
                "error": "main_pool_empty",
                "message_zh": "当前主菜池为空，无法完成排餐。",
                "message_en": "The main-dish pool is empty, so the week cannot be arranged.",
            }

        best_payload = None
        best_score = None
        for breakfast_choice in breakfast_options:
            for main_choice in main_options:
                picks = [dish for dish in ([breakfast_choice] if breakfast_choice else []) + list(main_choice) if dish]
                if not picks:
                    continue
                score = _day_combo_score(
                    picks,
                    remaining_target=ctx.remaining_target,
                    day_type=row["day_type"],
                    dish_usage=dish_usage,
                    ingredient_usage=ingredient_usage,
                    nutrient_progress=weekly_micro_actual,
                    weekly_targets=weekly_micro_targets,
                )
                if best_score is None or score < best_score:
                    assignments = _assign_main_slots(main_slots, main_choice)
                    if breakfast_choice is not None:
                        assignments["breakfast"] = breakfast_choice
                    best_score = score
                    best_payload = assignments

        if best_payload is None:
            return {
                "error": "arrangement_failed",
                "message_zh": "当前候选池无法满足这一周的排餐需求，请调整候选后再试。",
                "message_en": "The selected pool could not support a weekly arrangement.",
            }

        fixed_and_recorded = pc.sum_totals(ctx.fixed_meals + ctx.recorded_meals)
        actual_totals = {
            "kcal": round(float(fixed_and_recorded.calories or 0), 1),
            "protein_g": round(float(fixed_and_recorded.protein or 0), 1),
            "carbs_g": round(float(fixed_and_recorded.carbs or 0), 1),
            "fat_g": round(float(fixed_and_recorded.fat or 0), 1),
        }
        for meal_type, dish in best_payload.items():
            meal_payloads[meal_type] = {
                "meal_type": meal_type,
                "source": "selected",
                "status": (
                    pc.SLOT_STATUS_RECIPE
                    if dish.get("source") == "recipe_library" or dish.get("recipe_id")
                    else pc.SLOT_STATUS_GENERATED
                ),
                "candidate_source": dish.get("source", "generated"),
                "source_label": dish.get("source_label") or _pool_source_label(dish.get("source", "generated")),
                "recipe_id": dish.get("recipe_id"),
                "name": dish["name"],
                "totals": dish["totals"],
                "ingredients": dish["ingredients"],
                "seasonings": dish["seasonings"],
                "method_steps": dish["method_steps"],
                "day_type_affinities": dish["day_type_affinities"],
                "pick": dish,
            }
            actual_totals["kcal"] += dish["totals"]["kcal"]
            actual_totals["protein_g"] += dish["totals"]["protein_g"]
            actual_totals["carbs_g"] += dish["totals"]["carbs_g"]
            actual_totals["fat_g"] += dish["totals"]["fat_g"]
            dish_usage[dish["signature"]] += 1
            for slug in dish["ingredient_slugs"]:
                ingredient_usage[slug] += 1
            for role, value in dish["nutrients"].items():
                weekly_micro_actual[role] += value
            for role in FL.MICRONUTRIENT_ROLES:
                weekly_micro_carriers[role].update(
                    slug
                    for slug in dish["ingredient_slugs"]
                    if role in {FL._strip_tier(r) for r in FL.FOOD_LIBRARY.get(slug, {}).get("micronutrient_roles", [])}
                )

        kcal_gap = abs(actual_totals["kcal"] - ctx.daily_target.calories)
        if ctx.daily_target.calories > 0 and kcal_gap > ctx.daily_target.calories * 0.18:
            warnings.append(
                f"{date_str}: daily kcal gap {round(kcal_gap, 1)} exceeds the preferred planning band."
            )

        arranged_by_date[date_str] = {
            **row,
            "day_type_label_zh": DAY_TYPE_LABELS[row["day_type"]]["zh"],
            "day_type_label_en": DAY_TYPE_LABELS[row["day_type"]]["en"],
            "target": {
                "calorie_target": round(ctx.daily_target.calories, 1),
                "protein_g": round(ctx.daily_target.protein, 1),
                "carbs_g": round(ctx.daily_target.carbs, 1),
                "fat_g": round(ctx.daily_target.fat, 1),
            },
            "remaining_target": {
                "calorie_target": round(ctx.remaining_target.calories, 1),
                "protein_g": round(ctx.remaining_target.protein, 1),
                "carbs_g": round(ctx.remaining_target.carbs, 1),
                "fat_g": round(ctx.remaining_target.fat, 1),
            },
            "meals": meal_payloads,
            "totals": {key: round(value, 1) for key, value in actual_totals.items()},
        }

    weekly_micro_report: dict[str, dict] = {}
    missing_micro_roles: list[str] = []
    for role, meta in FL.MICRONUTRIENT_ROLES.items():
        target = round(weekly_micro_targets[role], 2)
        actual = round(weekly_micro_actual[role], 2)
        carriers = sorted(weekly_micro_carriers[role])
        status = "ok" if actual >= target else ("missing" if not carriers else "low")
        weekly_micro_report[role] = {
            "label_zh": meta["zh"],
            "label_en": meta["en"],
            "unit": meta["unit"],
            "actual": actual,
            "target": target,
            "status": status,
            "carriers": carriers,
        }
        if status == "missing":
            missing_micro_roles.append(role)
        elif status == "low":
            warnings.append(
                f"weekly micronutrient coverage is low for {meta['en']} ({actual}/{target} {meta['unit']})."
            )

    if missing_micro_roles and not has_unstructured_recorded_slots:
        labels = ", ".join(FL.MICRONUTRIENT_ROLES[role][f"{'zh' if language != 'en' else 'en'}"] for role in missing_micro_roles)
        guidance = _missing_micronutrient_guidance(weekly_micro_report)
        return {
            "error": "weekly_micronutrients_missing",
            "message_zh": f"当前选择排出的周餐单仍缺少这些微量元素来源：{labels}。",
            "message_en": f"The arranged week still has no usable source for: {labels}.",
            "micronutrients": weekly_micro_report,
            "missing_micronutrients": guidance["missing_micronutrients"],
            "recommended_foods": guidance["recommended_foods"],
            "warnings": warnings,
        }
    if missing_micro_roles and has_unstructured_recorded_slots:
        warnings.append(
            "some recorded meals do not expose structured ingredients, so weekly micronutrient coverage may be understated."
        )

    ordered_days = [arranged_by_date[row["date"]] for row in week_rows]
    weekly_totals = {
        "kcal": round(sum(day["totals"]["kcal"] for day in ordered_days), 1),
        "protein_g": round(sum(day["totals"]["protein_g"] for day in ordered_days), 1),
        "carbs_g": round(sum(day["totals"]["carbs_g"] for day in ordered_days), 1),
        "fat_g": round(sum(day["totals"]["fat_g"] for day in ordered_days), 1),
    }
    weekly_totals_target = {
        "kcal": round(sum(day["target"]["calorie_target"] for day in ordered_days), 1),
        "protein_g": round(sum(day["target"]["protein_g"] for day in ordered_days), 1),
        "carbs_g": round(sum(day["target"]["carbs_g"] for day in ordered_days), 1),
        "fat_g": round(sum(day["target"]["fat_g"] for day in ordered_days), 1),
    }
    ingredient_overuse = sorted(slug for slug, count in ingredient_usage.items() if count > 3)
    if ingredient_overuse:
        warnings.append(
            "high weekly repetition for: " + ", ".join(ingredient_overuse[:6])
        )

    return {
        "start_date": start_date.strftime("%Y-%m-%d"),
        "targets_baseline": {
            "calorie_target": baseline["calorie_target"],
            "protein_g": baseline["protein_g"],
            "carbs_g": baseline["carbs_g"],
            "fat_g": baseline["fat_g"],
            "activity_level": baseline["activity_level"],
            "activity_is_default": baseline["activity_is_default"],
        },
        "required_slot_counts": required_slot_counts,
        "requires_breakfast_pool": required_slot_counts["breakfast"] > 0,
        "requires_main_pool": (required_slot_counts["lunch"] + required_slot_counts["dinner"]) > 0,
        "days": ordered_days,
        "weekly_totals": weekly_totals,
        "weekly_totals_target": weekly_totals_target,
        "micronutrients": weekly_micro_report,
        "warnings": warnings,
    }
