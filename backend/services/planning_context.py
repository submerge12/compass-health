"""Spec-v1 planning context.

Shared data structures the meal-plan pipeline consumes at every stage:

    intake → fixed → recorded → recipe matcher → plan generator → nutrition check

Each layer reads the same `DayPlanningContext`, so the deduction order stays
explicit and the priority chain (recorded > fixed > recipe > generated) is
enforced by `highest_priority_slot`, not by ad-hoc table checks.

The builder (`build_context`) assembles a context for one user-day from the
database. It is intentionally DB-aware so callers pass a session once and get
a fully populated object back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy.orm import Session


# ── Slot-status vocabulary ───────────────────────────────────────────────────

SLOT_STATUS_RECORDED  = "recorded"
SLOT_STATUS_FIXED     = "fixed"
SLOT_STATUS_RECIPE    = "recipe"
SLOT_STATUS_GENERATED = "generated"
SLOT_STATUS_EMPTY     = "empty"

SLOT_STATUSES: tuple[str, ...] = (
    SLOT_STATUS_RECORDED,
    SLOT_STATUS_FIXED,
    SLOT_STATUS_RECIPE,
    SLOT_STATUS_GENERATED,
    SLOT_STATUS_EMPTY,
)

# Priority: higher wins when two rows describe the same (date, meal_type).
# A recorded meal always overrides a plan; a fixed meal always overrides a
# generated one; etc.
SLOT_PRIORITY: dict[str, int] = {
    SLOT_STATUS_RECORDED:  4,
    SLOT_STATUS_FIXED:     3,
    SLOT_STATUS_RECIPE:    2,
    SLOT_STATUS_GENERATED: 1,
    SLOT_STATUS_EMPTY:     0,
}


# ── Meal-type vocabulary ─────────────────────────────────────────────────────

MEAL_TYPE_BREAKFAST = "breakfast"
MEAL_TYPE_LUNCH     = "lunch"
MEAL_TYPE_DINNER    = "dinner"
MEAL_TYPE_SNACK     = "snack"

MEAL_TYPES: tuple[str, ...] = (
    MEAL_TYPE_BREAKFAST,
    MEAL_TYPE_LUNCH,
    MEAL_TYPE_DINNER,
    MEAL_TYPE_SNACK,
)


# ── Data types ───────────────────────────────────────────────────────────────

@dataclass
class NutritionTarget:
    calories: float = 0.0
    protein:  float = 0.0
    carbs:    float = 0.0
    fat:      float = 0.0

    def subtract(self, other: "NutritionTarget") -> "NutritionTarget":
        return NutritionTarget(
            calories=max(0.0, self.calories - other.calories),
            protein =max(0.0, self.protein  - other.protein),
            carbs   =max(0.0, self.carbs    - other.carbs),
            fat     =max(0.0, self.fat      - other.fat),
        )


@dataclass
class MealSlotFood:
    name:     str
    grams:    float
    calories: float
    protein:  float
    carbs:    float
    fat:      float


@dataclass
class MealSlot:
    date:      str                              # "YYYY-MM-DD"
    meal_type: str                              # breakfast/lunch/dinner/snack
    status:    str                              # SLOT_STATUS_*
    source_id: Optional[int] = None             # recipe_id / dietlog_id / fixed_meal_id
    foods:     list[MealSlotFood] = field(default_factory=list)
    totals:    NutritionTarget   = field(default_factory=NutritionTarget)


@dataclass
class DayPlanningContext:
    date:                 str
    daily_target:         NutritionTarget
    fixed_meals:          list[MealSlot]       = field(default_factory=list)
    recorded_meals:       list[MealSlot]       = field(default_factory=list)
    # MealPlanEntry rows already on the calendar (status: recipe / generated).
    # These do NOT affect remaining_target — they are what the planner
    # already produced and should preserve. They DO affect empty_meal_types()
    # so fill_empty_slots never overwrites existing plans.
    planned_meals:        list[MealSlot]       = field(default_factory=list)
    remaining_target:     NutritionTarget     = field(default_factory=NutritionTarget)
    available_ingredients: list[str]           = field(default_factory=list)

    def filled_meal_types(self) -> set[str]:
        """Meal slots already covered by a fixed, recorded, or planned entry —
        the plan generator must skip these."""
        return (
            {s.meal_type for s in self.fixed_meals}
            | {s.meal_type for s in self.recorded_meals}
            | {s.meal_type for s in self.planned_meals}
        )

    def empty_meal_types(self) -> list[str]:
        filled = self.filled_meal_types()
        # Snack is opt-in: only considered "empty" if fixed meals explicitly
        # cover it (i.e. the user wants a snack slot) — otherwise the planner
        # would fabricate a fourth meal the user didn't ask for.
        #
        # Caller-side: if you want an explicit snack slot regardless of fixed
        # meals, request it directly rather than through this helper.
        wants_snack = any(s.meal_type == MEAL_TYPE_SNACK for s in self.fixed_meals + self.recorded_meals)
        core = [MEAL_TYPE_BREAKFAST, MEAL_TYPE_LUNCH, MEAL_TYPE_DINNER]
        if wants_snack:
            core.append(MEAL_TYPE_SNACK)
        return [mt for mt in core if mt not in filled]


# ── Priority resolution ──────────────────────────────────────────────────────

def highest_priority_slot(slots: Iterable[MealSlot]) -> Optional[MealSlot]:
    """Pick the winning slot when several rows cover the same (date, meal_type).

    Returns `None` if `slots` is empty. Used by the read-side projection (and
    by the shopping-list aggregator) to apply the priority chain uniformly.
    """
    best: Optional[MealSlot] = None
    best_priority = -1
    for slot in slots:
        p = SLOT_PRIORITY.get(slot.status, -1)
        if p > best_priority:
            best = slot
            best_priority = p
    return best


# ── Totals helper ────────────────────────────────────────────────────────────

def sum_totals(slots: Iterable[MealSlot]) -> NutritionTarget:
    total = NutritionTarget()
    for s in slots:
        total.calories += s.totals.calories
        total.protein  += s.totals.protein
        total.carbs    += s.totals.carbs
        total.fat      += s.totals.fat
    return total


# ── Context builder ──────────────────────────────────────────────────────────

def _meal_plan_status(row) -> str:
    """Interpret a MealPlanEntry.status, falling back if the backfill missed
    the row (pre-migration rows default to 'recipe' at the schema level)."""
    status = getattr(row, "status", None)
    if status in (SLOT_STATUS_RECIPE, SLOT_STATUS_GENERATED):
        return status
    return SLOT_STATUS_RECIPE if row.recipe_id is not None else SLOT_STATUS_GENERATED


# ── DietLog ↔ MealPlanEntry status flip ──────────────────────────────────────
#
# Priority-chain enforcement at the write layer: when a DietLog appears for
# (user, date, meal_type), any MealPlanEntry for the same slot is marked
# `recorded` so the frontend's status badges stay consistent with what the
# read-side projector would report. When the DietLog is removed, we revert
# the entry to its base status (recipe or generated, derived from recipe_id).
#
# The projector itself does not rely on the stored status being flipped — it
# skips planned rows whose meal_type already has a DietLog — so these helpers
# exist purely for display consistency and for anyone querying MealPlanEntry
# directly.

def mark_plan_slot_recorded(
    db: Session,
    user_id: int,
    date: str,       # "YYYY-MM-DD"
    meal_type: str,
) -> bool:
    """Flip a matching MealPlanEntry's status to `recorded`. No-op if no
    entry exists. Does NOT commit — the caller's transaction owns that."""
    from models import MealPlanEntry

    row = (
        db.query(MealPlanEntry)
        .filter_by(user_id=user_id, date=date, meal_type=meal_type)
        .first()
    )
    if row is None:
        return False
    if row.status != SLOT_STATUS_RECORDED:
        row.status = SLOT_STATUS_RECORDED
    return True


def revert_plan_slot_if_no_record(
    db: Session,
    user_id: int,
    date: str,
    meal_type: str,
) -> bool:
    """If no DietLog remains for this slot, revert the MealPlanEntry status
    to its base ('recipe' if recipe_id is set, else 'generated').

    Called after a DietLog delete so the UI doesn't keep showing a slot as
    consumed once the underlying log is gone. Returns True if an entry was
    reverted. Does NOT commit.
    """
    from models import DietLog, MealPlanEntry

    still_logged = (
        db.query(DietLog.id)
        .filter_by(user_id=user_id, date=date, meal_type=meal_type)
        .first()
    )
    if still_logged is not None:
        return False

    row = (
        db.query(MealPlanEntry)
        .filter_by(user_id=user_id, date=date, meal_type=meal_type)
        .first()
    )
    if row is None or row.status != SLOT_STATUS_RECORDED:
        return False

    row.status = (
        SLOT_STATUS_RECIPE if row.recipe_id is not None else SLOT_STATUS_GENERATED
    )
    return True


def daily_target_for_date(db: Session, user, date: str) -> NutritionTarget:
    """Compute this date's kcal + macro target.

    Mirrors the per-date loop in `menu_planner.week_plan`: BMR is fixed by the
    profile, TDEE flexes with the day's logged (or defaulted) activity, macros
    come from `services.calorie`. Returns a zeroed target when the user has
    no BMR profile — caller decides how to handle that case.
    """
    from services import calorie as calorie_svc

    profile = getattr(user, "bmr_profile", None)
    if profile is None:
        return NutritionTarget()

    activity = calorie_svc.get_activity_for_date(db, user.id, date) \
        or calorie_svc.default_activity_for_user(db, user.id)
    bmr = calorie_svc.compute_bmr(profile.age, profile.gender, profile.height_cm, profile.weight_kg)
    tdee = calorie_svc.compute_tdee(bmr, activity)
    kcal, _ = calorie_svc.compute_calorie_target(profile.goal, tdee, bmr)
    macros = calorie_svc.compute_macros(
        calories=kcal,
        weight_kg=profile.weight_kg,
        gender=profile.gender,
        age=profile.age,
        goal=profile.goal,
        is_exerciser=activity in calorie_svc.EXERCISER_LEVELS,
    )
    return NutritionTarget(
        calories=float(macros["calories"]),
        protein =float(macros["protein_g"]),
        carbs   =float(macros["carbs_g"]),
        fat     =float(macros["fat_g"]),
    )


def build_context(
    db: Session,
    user,                       # models.User — avoid circular import
    date: str,                  # "YYYY-MM-DD"
    daily_target: Optional[NutritionTarget] = None,
    available_ingredients: Optional[list[str]] = None,
) -> DayPlanningContext:
    """Assemble a `DayPlanningContext` for (user, date).

    Reads DietLog, UserFixedMeal, and existing MealPlanEntry rows, converts
    them to `MealSlot`s, and computes the remaining target after the deduction
    order:

        remaining = daily_target − Σ fixed − Σ recorded

    MealPlanEntry rows contribute to `planned_meals` only — they do NOT affect
    `remaining_target`, so regenerating an empty slot does not double-count
    any already-planned one.

    If `daily_target` is omitted it is computed via `daily_target_for_date`.
    If `available_ingredients` is omitted it is loaded from the user's
    closed library (`services.nutrition_audit.load_user_library`).
    """
    # Imported lazily to avoid a circular-import with models.py on startup.
    from models import DietLog, UserFixedMeal, MealPlanEntry

    if daily_target is None:
        daily_target = daily_target_for_date(db, user, date)

    if available_ingredients is None:
        from services import nutrition_audit
        available_ingredients = nutrition_audit.load_user_library(db, user.id)

    weekday = datetime.strptime(date, "%Y-%m-%d").weekday()

    recorded_by_slot: dict[str, MealSlot] = {}
    for row in db.query(DietLog).filter_by(user_id=user.id, date=date).all():
        slot = recorded_by_slot.get(row.meal_type)
        if slot is None:
            slot = MealSlot(
                date=date,
                meal_type=row.meal_type,
                status=SLOT_STATUS_RECORDED,
                source_id=row.id,
                totals=NutritionTarget(),
            )
            recorded_by_slot[row.meal_type] = slot
        slot.source_id = max(slot.source_id or 0, row.id or 0)
        slot.totals.calories += float(row.calories or 0)
        slot.totals.protein += float(row.protein_g or 0)
        slot.totals.carbs += float(row.carbs_g or 0)
        slot.totals.fat += float(row.fat_g or 0)

    recorded = list(recorded_by_slot.values())
    recorded_meal_types = {s.meal_type for s in recorded}

    fixed: list[MealSlot] = []
    fixed_rows = (
        db.query(UserFixedMeal)
        .filter(UserFixedMeal.user_id == user.id)
        .filter((UserFixedMeal.weekday == weekday) | (UserFixedMeal.weekday.is_(None)))
        .all()
    )
    for row in fixed_rows:
        if row.meal_type in recorded_meal_types:
            # Recorded meal supersedes the fixed one for this specific day.
            continue
        fixed.append(MealSlot(
            date=date,
            meal_type=row.meal_type,
            status=SLOT_STATUS_FIXED,
            source_id=row.id,
            totals=NutritionTarget(
                calories=float(row.calories or 0),
                protein =float(row.protein_g or 0),
                carbs   =float(row.carbs_g or 0),
                fat     =float(row.fat_g or 0),
            ),
        ))
    fixed_meal_types = {s.meal_type for s in fixed}

    planned: list[MealSlot] = []
    for row in db.query(MealPlanEntry).filter_by(user_id=user.id, date=date).all():
        # Recorded and fixed outrank a stored plan — skip so priority stays consistent.
        if row.meal_type in recorded_meal_types or row.meal_type in fixed_meal_types:
            continue
        planned.append(MealSlot(
            date=date,
            meal_type=row.meal_type,
            status=_meal_plan_status(row),
            source_id=row.id,
            totals=NutritionTarget(
                calories=float(row.calories or 0),
                protein =float(row.protein_g or 0),
                carbs   =float(row.carbs_g or 0),
                fat     =float(row.fat_g or 0),
            ),
        ))

    remaining = daily_target.subtract(sum_totals(recorded)).subtract(sum_totals(fixed))

    return DayPlanningContext(
        date=date,
        daily_target=daily_target,
        fixed_meals=fixed,
        recorded_meals=recorded,
        planned_meals=planned,
        remaining_target=remaining,
        available_ingredients=list(available_ingredients),
    )


# ── Week-level read projection ───────────────────────────────────────────────

def project_week(
    db: Session,
    user,
    start_date: str,
    length_days: int = 7,
) -> list[DayPlanningContext]:
    """Return one `DayPlanningContext` per day in the week starting `start_date`.

    This is the read-side view consumed by the frontend and the shopping-list
    aggregator. The priority chain (recorded > fixed > planned) is applied
    inside each day's context; callers render whichever slot lists are
    populated.
    """
    from datetime import timedelta

    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    return [
        build_context(db, user, (start + timedelta(days=i)).strftime("%Y-%m-%d"))
        for i in range(length_days)
    ]
