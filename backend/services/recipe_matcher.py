"""Spec-v1 recipe matcher.

`is_available(recipe, inventory)` decides whether a Recipe row is usable given
the user's current ingredient inventory. Reads the structured
`Recipe.ingredients_json` column (see backend/models.py) which each entry
shaped `{slug, grams, required}`; only `required: true` slugs gate
availability.

`match_recipes` filters a query by meal_type and availability, then ranks the
survivors by how well they fit the remaining daily target — the planner
consumes this ordering before falling back to the LLM.

`pick_day_set` is the spec-v1 day-level picker. Given a daily remaining
target and k empty slots, it greedily selects k recipes that jointly hit
the day's totals, with lexicographic priority kcal > protein > carbs > fat.
It does NOT gate on pantry inventory — the weekly procurement flow handles
ingredient availability. It honors optional weekly-quota hints (red_meat,
deep_sea_fish) by preferring quota-satisfying recipes until at least one
pick covers the quota.
"""

from __future__ import annotations

import json
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from services.planning_context import NutritionTarget


# ── JSON helpers ─────────────────────────────────────────────────────────────

def _parse_ingredients_json(raw: Optional[str]) -> list[dict]:
    """Return the structured ingredient list, or [] if absent / malformed.

    A recipe without `ingredients_json` is treated as "no structured data" —
    `is_available` will return False so the planner falls through to the LLM.
    That matches the spec's intent: only recipes with known ingredient
    metadata should enter the candidate pool.
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


def required_slugs(recipe) -> list[str]:
    ings = _parse_ingredients_json(getattr(recipe, "ingredients_json", None))
    return [i["slug"] for i in ings if i.get("required", True)]


def all_slugs(recipe) -> list[str]:
    ings = _parse_ingredients_json(getattr(recipe, "ingredients_json", None))
    return [i["slug"] for i in ings]


# ── Availability ─────────────────────────────────────────────────────────────

def is_available(recipe, inventory: Iterable[str]) -> bool:
    """True iff every *required* ingredient is present in `inventory`.

    Optional ingredients (e.g. seasonings) never gate availability — a recipe
    that requires rice + chicken + optional scallion is available whenever the
    user has rice and chicken, regardless of whether scallion is on hand.
    """
    needed = required_slugs(recipe)
    if not needed:
        # No structured metadata → cannot verify → not a library candidate.
        return False
    stock = set(inventory)
    return all(slug in stock for slug in needed)


# ── Ranking ──────────────────────────────────────────────────────────────────

def _fit_score(recipe, remaining: NutritionTarget) -> float:
    """Lower = better fit for the remaining daily target.

    Prioritises covering protein without overshooting fat — matches the spec's
    hard-constraint ordering (calories, protein, carbs, fat). Each dimension
    contributes its absolute deviation, with protein weighted up and fat
    weighted up only when the recipe would push the user over the day's fat
    budget (a soft penalty elsewhere).
    """
    cal  = float(recipe.calories or 0)
    prot = float(recipe.protein_g or 0)
    carb = float(recipe.carbs_g or 0)
    fat  = float(recipe.fat_g or 0)

    dev_cal  = abs(cal  - remaining.calories) / max(remaining.calories, 1.0)
    dev_prot = abs(prot - remaining.protein)  / max(remaining.protein,  1.0)
    dev_carb = abs(carb - remaining.carbs)    / max(remaining.carbs,    1.0)
    dev_fat  = abs(fat  - remaining.fat)      / max(remaining.fat,      1.0)

    fat_overshoot = max(0.0, fat - remaining.fat) / max(remaining.fat, 1.0)

    return dev_cal + 1.5 * dev_prot + dev_carb + dev_fat + 2.0 * fat_overshoot


def match_recipes(
    db: Session,
    meal_type: str,
    inventory: Iterable[str],
    remaining: NutritionTarget,
    limit: int = 10,
):
    """Return up to `limit` available recipes for this meal slot, ranked.

    `inventory` is the user's available-ingredient slug list (typically
    sourced from FoodPreference + pantry data in later phases). `remaining`
    is `ctx.remaining_target / empty_slot_count` — the share of the day's
    leftover budget this slot should aim for.
    """
    # Imported lazily to avoid circular-import during app startup.
    from models import Recipe

    stock = set(inventory)

    q = (
        db.query(Recipe)
        .filter(Recipe.is_approved.is_(True))
        .filter(Recipe.ingredients_json.isnot(None))
    )
    if meal_type:
        # Recipe.meal_types is a CSV string ("breakfast,lunch"); broaden match
        # to any substring hit. A stricter filter lives in the caller once the
        # meal_types column is normalised.
        q = q.filter(Recipe.meal_types.like(f"%{meal_type}%"))

    candidates = [r for r in q.all() if is_available(r, stock)]
    candidates.sort(key=lambda r: _fit_score(r, remaining))
    return candidates[:limit]


# ── Day-level set picker ─────────────────────────────────────────────────────

# Quota hint → execution_buckets slug set. Resolved lazily to keep
# food_library's import footprint out of this module's import time.
def _slugs_for_execution_bucket(bucket: str) -> set[str]:
    from services import food_library as FL
    return {
        slug for slug, entry in FL.FOOD_LIBRARY.items()
        if bucket in entry.get("execution_buckets", ())
    }


def _recipe_hits_bucket(recipe, bucket_slugs: set[str]) -> bool:
    """True if any ingredient in this recipe is in `bucket_slugs`."""
    if not bucket_slugs:
        return False
    ings = _parse_ingredients_json(getattr(recipe, "ingredients_json", None))
    return any(ing.get("slug") in bucket_slugs for ing in ings)


def _recipe_totals(recipe) -> NutritionTarget:
    return NutritionTarget(
        calories=float(recipe.calories or 0),
        protein =float(recipe.protein_g or 0),
        carbs   =float(recipe.carbs_g or 0),
        fat     =float(recipe.fat_g or 0),
    )


def _per_pick_target(remaining: NutritionTarget, slots_left: int) -> NutritionTarget:
    if slots_left <= 0:
        return NutritionTarget()
    return NutritionTarget(
        calories=remaining.calories / slots_left,
        protein =remaining.protein  / slots_left,
        carbs   =remaining.carbs    / slots_left,
        fat     =remaining.fat      / slots_left,
    )


def pick_day_set(
    db: Session,
    daily_remaining: NutritionTarget,
    *,
    k: int,
    quota_hint: Optional[str] = None,      # "red_meat" | "deep_sea_fish" | None
    excluded_recipe_ids: Iterable[int] = (),
    meal_type_filter: Optional[Iterable[str]] = None,
) -> list:
    """Pick `k` recipes that jointly approach `daily_remaining`.

    Greedy + lexicographic by (kcal_delta, protein_delta, carbs_delta,
    fat_delta) — matches the user-specified priority order. At each step
    the target for the next pick is `remaining / slots_left`, so early
    picks leave room for later ones.

    `quota_hint` is a food_library execution_bucket (e.g. "red_meat").
    While no prior pick satisfies it, quota-satisfying candidates are
    preferred regardless of macro fit; once one pick covers it, the
    hint is dropped and the remaining picks go by pure macro lex.

    No pantry gating: the weekly procurement step is responsible for
    ensuring ingredients exist; picking is a library-level concern. The
    recipe must have `ingredients_json` (needed for the shopping-list
    expansion) and be approved.

    `meal_type_filter` is optional — if provided, only recipes whose
    `meal_types` CSV intersects the filter are considered. Pass the set
    of empty meal_types for the day to avoid picking a recipe that has
    no assignable slot.

    Returns up to `k` recipes. If the library can't produce `k` distinct
    approved recipes, returns fewer — the caller should then fall back
    to the deterministic solver for any uncovered slots.
    """
    from models import Recipe

    excluded = set(excluded_recipe_ids)
    quota_slugs: set[str] = (
        _slugs_for_execution_bucket(quota_hint) if quota_hint else set()
    )

    q = (
        db.query(Recipe)
        .filter(Recipe.is_approved.is_(True))
        .filter(Recipe.ingredients_json.isnot(None))
    )
    all_recipes = [r for r in q.all() if r.id not in excluded]

    if meal_type_filter is not None:
        wanted = {mt.strip().lower() for mt in meal_type_filter if mt}

        def _meal_type_ok(r) -> bool:
            csv = (getattr(r, "meal_types", "") or "").lower()
            if not csv:
                # Untagged recipes are assumed usable for any slot.
                return True
            return any(token.strip() in wanted for token in csv.split(","))

        all_recipes = [r for r in all_recipes if _meal_type_ok(r)]

    picks: list = []
    remaining = NutritionTarget(
        calories=daily_remaining.calories,
        protein =daily_remaining.protein,
        carbs   =daily_remaining.carbs,
        fat     =daily_remaining.fat,
    )
    quota_satisfied = not quota_slugs   # no hint ⇒ trivially satisfied

    for i in range(k):
        slots_left = k - i
        target = _per_pick_target(remaining, slots_left)

        pool = [r for r in all_recipes if r not in picks]
        if not pool:
            break

        def _score(r):
            totals = _recipe_totals(r)
            dcal  = abs(totals.calories - target.calories)
            dprot = abs(totals.protein  - target.protein)
            dcarb = abs(totals.carbs    - target.carbs)
            dfat  = abs(totals.fat      - target.fat)
            # While the quota is unmet, recipes that hit it sort before
            # those that don't — quota_penalty=0 (hit) beats 1 (miss).
            # Once satisfied, every candidate scores 0 here.
            if not quota_satisfied:
                quota_penalty = 0 if _recipe_hits_bucket(r, quota_slugs) else 1
            else:
                quota_penalty = 0
            return (quota_penalty, dcal, dprot, dcarb, dfat)

        pool.sort(key=_score)
        best = pool[0]
        picks.append(best)

        # If this pick covered the quota, drop the hint for subsequent picks.
        if not quota_satisfied and _recipe_hits_bucket(best, quota_slugs):
            quota_satisfied = True

        # Subtract (clamped at 0 so remaining never goes negative — an
        # early oversized pick should still leave zero for later picks,
        # not force them to "subtract back").
        best_totals = _recipe_totals(best)
        remaining = remaining.subtract(best_totals)

    return picks


def assign_picks_to_slots(
    picks: list,
    empty_meal_types: list[str],
) -> dict:
    """Assign `picks` to `empty_meal_types` by meal_types tag, kcal tiebreaker.

    Rules:
      * If a pick's `meal_types` CSV names the slot, prefer it for that slot.
      * Kcal tiebreaker: lightest → breakfast, heaviest → dinner, middle
        → lunch/snack.
      * If no pick tags a given slot, fall back to the kcal-tiebreaker
        pool unfiltered.

    Returns a dict `{meal_type: Recipe}` covering as many empty slots as
    there are picks. Slots without a pick are omitted — caller falls
    back to the deterministic solver.
    """
    remaining = list(picks)
    assignments: dict = {}

    def _tagged_for(slot: str, pool: list) -> list:
        out = []
        for r in pool:
            csv = (getattr(r, "meal_types", "") or "").lower()
            if not csv:
                # Untagged recipes match anything — keep them as fallbacks.
                continue
            if slot in {token.strip() for token in csv.split(",")}:
                out.append(r)
        return out

    # Claim the kcal extremes first so the median pick lands on lunch/snack:
    # if we processed lunch before dinner, lunch's median-of-remaining could
    # grab the heaviest and leave dinner with the lighter pick.
    slot_order = ["breakfast", "dinner", "lunch", "snack"]
    ordered_slots = [s for s in slot_order if s in empty_meal_types]
    # (Any oddball slot name goes to the end in the order provided.)
    ordered_slots += [s for s in empty_meal_types if s not in slot_order]

    for slot in ordered_slots:
        if not remaining:
            break
        tagged = _tagged_for(slot, remaining)
        pool = tagged if tagged else remaining

        if slot == "breakfast":
            pick = min(pool, key=lambda r: float(r.calories or 0))
        elif slot == "dinner":
            pick = max(pool, key=lambda r: float(r.calories or 0))
        else:  # lunch, snack, or anything else — take the median by kcal
            sorted_pool = sorted(pool, key=lambda r: float(r.calories or 0))
            pick = sorted_pool[len(sorted_pool) // 2]

        assignments[slot] = pick
        remaining.remove(pick)

    return assignments
