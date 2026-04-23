"""
Calorie and macronutrient engine for Compass Health.

All energy numbers are kcal/day. Weights are in kg. Protein/carbs/fat are in grams.
TDEE is computed dynamically from the user's BMR and today's DailyActivityPlan.

Algorithm (9-step recipe):

  Step 0  Inputs: sex, age, weight, height, activity_level, goal.
  Step 1  BMR (Mifflin-St Jeor); TDEE = BMR × activity_factor.
  Step 2  Raw calorie target by goal, then clamp into [lower, upper].
          Lower wins when lower > upper (flag: lower_overrides_upper).
  Step 3  Protein per-kg = clamp(base_target + age_adjust, lower, upper).
          (Body-fat adjustment intentionally NOT implemented.)
  Step 4  Fat = max(min_fat, 20 % of calories / 9). Soft max = 40 % / 9.
  Step 5  Carbs = remainder of calories.
  Step 6  Read carb range; if female, raise carb_min_g to ≥ 120 g.
  Step 7  Backtrack: if carbs > max → push excess kcal to fat;
          if carbs < min → pull from fat (down to min) then protein (down to lower).
  Step 8  Emit status labels for calorie / protein / fat / carbs.
  Step 9  Return everything plus any warnings.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

import models


# ── Activity ─────────────────────────────────────────────────────────────────
ACTIVITY_MULTIPLIERS: dict[str, float] = {
    "sedentary":         1.10,
    "lightly_active":    1.20,
    "moderately_active": 1.35,
    "strength_training": 1.50,
}
DEFAULT_ACTIVITY = "lightly_active"
EXERCISER_LEVELS = {"moderately_active", "strength_training"}


# ── Goals ────────────────────────────────────────────────────────────────────
GOALS = {
    "improve_health",
    "body_recomp",
    "fat_loss_slow",
    "fat_loss_moderate",
    "fat_loss_fast",
    "muscle_gain_slow",
    "muscle_gain_moderate",
    "muscle_gain_fast",
}

LEGACY_GOAL_MAP = {
    "lose_weight": "fat_loss_slow",
    "maintain":    "improve_health",
    "gain_muscle": "muscle_gain_slow",
}


def normalize_goal(goal: str) -> str:
    return LEGACY_GOAL_MAP.get(goal, goal)


# ── Step 1: BMR / TDEE ───────────────────────────────────────────────────────

def compute_bmr(age: int, gender: str, height_cm: float, weight_kg: float) -> float:
    """Mifflin-St Jeor."""
    if gender == "male":
        return 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    return 10 * weight_kg + 6.25 * height_cm - 5 * age - 161


def compute_tdee(bmr: float, activity_level: str) -> float:
    mult = ACTIVITY_MULTIPLIERS.get(activity_level, ACTIVITY_MULTIPLIERS[DEFAULT_ACTIVITY])
    return bmr * mult


# ── Step 2: Calorie target ───────────────────────────────────────────────────

GOAL_CALORIE_FACTOR: dict[str, float] = {
    "improve_health":       1.00,
    "body_recomp":          0.90,
    "fat_loss_slow":        0.90,
    "fat_loss_moderate":    0.85,
    "fat_loss_fast":        0.80,
    "muscle_gain_slow":     1.10,
    "muscle_gain_moderate": 1.15,
    "muscle_gain_fast":     1.20,
}


def _calorie_bounds(goal: str, tdee: float, bmr: float) -> tuple[Optional[float], Optional[float]]:
    """(lower, upper) for the goal. None means no bound on that side."""
    g = normalize_goal(goal)
    if g == "improve_health":      return None, None
    if g == "body_recomp":         return bmr + 100, tdee - 300
    if g == "fat_loss_slow":       return bmr + 100, None
    if g == "fat_loss_moderate":   return bmr + 100, tdee - 500
    if g == "fat_loss_fast":       return bmr + 100, tdee - 700
    if g == "muscle_gain_slow":    return tdee + 200, tdee + 300
    if g == "muscle_gain_moderate":return tdee + 300, tdee + 500
    if g == "muscle_gain_fast":    return tdee + 400, tdee + 700
    return None, None


def compute_calorie_target(goal: str, tdee: float, bmr: float) -> tuple[float, str]:
    """Return (calorie_target, status).

    status ∈ {on_target, lower_bound_applied, upper_bound_applied, lower_overrides_upper}.
    Lower bound wins when it conflicts with the upper cap — undereating below the
    safety floor is the greater harm.
    """
    g = normalize_goal(goal)
    raw = tdee * GOAL_CALORIE_FACTOR.get(g, 1.00)
    lower, upper = _calorie_bounds(g, tdee, bmr)

    if lower is not None and upper is not None and lower > upper:
        return lower, "lower_overrides_upper"

    target = raw
    if upper is not None:
        target = min(target, upper)
    if lower is not None:
        target = max(target, lower)

    if lower is not None and target == lower and raw < lower:
        return target, "lower_bound_applied"
    if upper is not None and target == upper and raw > upper:
        return target, "upper_bound_applied"
    return target, "on_target"


# ── Step 3: Protein bands ────────────────────────────────────────────────────

# (lower_per_kg, target_per_kg, upper_per_kg) by (goal_family, is_exerciser).
#   lower  = safe minimum (below → "insufficient")
#   target = default recommendation (before age adjustment)
#   upper  = high-end tolerable limit (appropriate up to here)
PROTEIN_BANDS: dict[tuple[str, bool], tuple[float, float, float]] = {
    ("improve_health", False):   (0.8, 1.2, 1.5),
    ("improve_health", True):    (1.2, 1.6, 1.9),
    ("muscle_gain", False):      (1.4, 2.0, 2.3),
    ("muscle_gain", True):       (1.4, 2.0, 2.3),
    ("body_recomp", False):      (1.2, 1.8, 2.1),
    ("body_recomp", True):       (1.6, 2.2, 2.5),
    ("fat_loss", False):         (1.4, 2.0, 2.4),
    ("fat_loss", True):          (1.8, 2.4, 2.8),
}

# Margin above the "upper" band before protein is flagged "excessive".
PROTEIN_EXCESSIVE_MARGIN_PER_KG = 0.2


def _goal_family(goal: str) -> str:
    g = normalize_goal(goal)
    if g.startswith("fat_loss"):     return "fat_loss"
    if g.startswith("muscle_gain"):  return "muscle_gain"
    return g  # improve_health / body_recomp


def protein_band(goal: str, is_exerciser: bool) -> tuple[float, float, float]:
    return PROTEIN_BANDS[(_goal_family(goal), is_exerciser)]


def _protein_age_adj(age: int) -> float:
    if age >= 50: return 0.2
    if age >= 35: return 0.1
    return 0.0


def classify_protein(protein_g: float, weight_kg: float, goal: str, is_exerciser: bool) -> str:
    """Classify an actual intake against the band for (goal, exerciser)."""
    if weight_kg <= 0:
        return "appropriate"
    per_kg = protein_g / weight_kg
    lower, _target, upper = protein_band(goal, is_exerciser)
    if per_kg < lower:
        return "insufficient"
    if per_kg <= upper:
        return "appropriate"
    if per_kg <= upper + PROTEIN_EXCESSIVE_MARGIN_PER_KG:
        return "slightly_high"
    return "excessive"


# ── Step 6: Carb bands ───────────────────────────────────────────────────────

# (carb_min_per_kg, carb_max_per_kg) by normalized goal.
CARB_BANDS: dict[str, tuple[float, float]] = {
    "improve_health":       (3.0, 5.0),
    "body_recomp":          (2.5, 3.5),
    "fat_loss_slow":        (2.5, 3.5),
    "fat_loss_moderate":    (2.0, 3.0),
    "fat_loss_fast":        (1.5, 2.5),
    "muscle_gain_slow":     (4.0, 6.0),
    "muscle_gain_moderate": (4.5, 6.5),
    "muscle_gain_fast":     (5.0, 7.0),
}

FEMALE_CARB_FLOOR_G = 120.0


def carb_band(goal: str) -> tuple[float, float]:
    return CARB_BANDS.get(normalize_goal(goal), CARB_BANDS["improve_health"])


# ── Steps 3–8: Macro distribution ────────────────────────────────────────────

def compute_macros(
    calories: float,
    weight_kg: float,
    gender: str,
    age: int,
    goal: str,
    is_exerciser: bool,
) -> dict:
    """Distribute calories into protein/fat/carbs and emit status labels.

    Order of operations: protein first (Step 3), fat next with a 20 % floor
    (Step 4), then carbs as the balancing variable (Steps 5–7).
    """
    if calories <= 0 or weight_kg <= 0:
        return _empty_macros(calories)

    # Step 3 — protein
    lower_p, target_p, upper_p = protein_band(goal, is_exerciser)
    target_per_kg = max(lower_p, min(upper_p, target_p + _protein_age_adj(age)))
    protein_g = weight_kg * target_per_kg
    protein_lower_g = weight_kg * lower_p
    protein_upper_g = weight_kg * upper_p

    # Step 4 — fat
    fat_min_g = (0.6 if gender == "male" else 0.8) * weight_kg
    fat_g = max(fat_min_g, calories * 0.20 / 9)
    fat_soft_max_g = calories * 0.40 / 9

    # Step 5 — initial carbs (remainder)
    carbs_g = max(0.0, (calories - protein_g * 4 - fat_g * 9) / 4)

    # Step 6 — carb range, with female floor
    carbs_min_per_kg, carbs_max_per_kg = carb_band(goal)
    carbs_min_g = carbs_min_per_kg * weight_kg
    carbs_max_g = carbs_max_per_kg * weight_kg
    if gender == "female":
        carbs_min_g = max(carbs_min_g, FEMALE_CARB_FLOOR_G)

    # Step 7 — backtrack
    carb_below_unavoidable = False
    if carbs_g > carbs_max_g:
        excess_kcal = (carbs_g - carbs_max_g) * 4
        carbs_g = carbs_max_g
        fat_g += excess_kcal / 9
    elif carbs_g < carbs_min_g:
        gap_kcal = (carbs_min_g - carbs_g) * 4

        fat_reducible_kcal = max(0.0, (fat_g - fat_min_g) * 9)
        take = min(gap_kcal, fat_reducible_kcal)
        fat_g -= take / 9
        carbs_g += take / 4
        gap_kcal -= take

        if gap_kcal > 0:
            prot_reducible_kcal = max(0.0, (protein_g - protein_lower_g) * 4)
            take = min(gap_kcal, prot_reducible_kcal)
            protein_g -= take / 4
            carbs_g += take / 4
            gap_kcal -= take

        if gap_kcal > 0:
            carb_below_unavoidable = True

    # Step 8 — status labels
    protein_status = _classify_protein_per_kg(protein_g / weight_kg, lower_p, upper_p)
    fat_status = _classify_fat(fat_g, fat_min_g, fat_soft_max_g)
    carb_status = _classify_carb(carbs_g, carbs_min_g, carbs_max_g, carb_below_unavoidable)

    return {
        "calories": round(calories),
        "protein_g": round(protein_g, 1),
        "carbs_g": round(carbs_g, 1),
        "fat_g": round(fat_g, 1),
        "protein_band": list(protein_band(goal, is_exerciser)),
        "protein_range_g": (round(protein_lower_g, 1), round(protein_upper_g, 1)),
        "carbs_range_g": (round(carbs_min_g, 1), round(carbs_max_g, 1)),
        "fat_min_g": round(fat_min_g, 1),
        "fat_soft_max_g": round(fat_soft_max_g, 1),
        "protein_status": protein_status,
        "fat_status": fat_status,
        "carb_status": carb_status,
    }


def _classify_protein_per_kg(per_kg: float, lower: float, upper: float) -> str:
    if per_kg < lower:
        return "insufficient"
    if per_kg <= upper:
        return "appropriate"
    if per_kg <= upper + PROTEIN_EXCESSIVE_MARGIN_PER_KG:
        return "slightly_high"
    return "excessive"


def _classify_fat(fat_g: float, fat_min_g: float, fat_soft_max_g: float) -> str:
    if fat_g < fat_min_g:
        return "below_min"
    if fat_g > fat_soft_max_g:
        return "high"
    return "appropriate"


def _classify_carb(carbs_g: float, carb_min_g: float, carb_max_g: float, unavoidable: bool) -> str:
    if carbs_g < carb_min_g:
        return "below_range_unavoidable" if unavoidable else "below_range"
    if carbs_g > carb_max_g:
        return "above_range"
    return "appropriate"


def _empty_macros(calories: float) -> dict:
    return {
        "calories": max(0, round(calories)),
        "protein_g": 0, "carbs_g": 0, "fat_g": 0,
        "protein_band": None,
        "protein_range_g": (0, 0),
        "carbs_range_g": (0, 0),
        "fat_min_g": 0, "fat_soft_max_g": 0,
        "protein_status": "insufficient",
        "fat_status": "below_min",
        "carb_status": "below_range",
    }


# ── Daily activity helpers ───────────────────────────────────────────────────

def today_utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_activity_for_date(db: Session, user_id: int, date_str: str) -> Optional[str]:
    """Return the stored activity for a given date, or None if not logged."""
    rec = (
        db.query(models.DailyActivityPlan)
        .filter(
            models.DailyActivityPlan.user_id == user_id,
            models.DailyActivityPlan.date == date_str,
        )
        .first()
    )
    return rec.activity_level if rec else None


def default_activity_for_user(db: Session, user_id: int) -> str:
    """7-day modal average, or the DEFAULT_ACTIVITY fallback."""
    today = datetime.now(timezone.utc)
    cutoff = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")
    recent = (
        db.query(models.DailyActivityPlan.activity_level)
        .filter(
            models.DailyActivityPlan.user_id == user_id,
            models.DailyActivityPlan.date >= cutoff,
            models.DailyActivityPlan.date < today_str,
        )
        .all()
    )
    if not recent:
        return DEFAULT_ACTIVITY
    counts = Counter(r[0] for r in recent if r[0] in ACTIVITY_MULTIPLIERS)
    if not counts:
        return DEFAULT_ACTIVITY
    return counts.most_common(1)[0][0]


def resolve_activity_for_today(db: Session, user_id: int) -> tuple[str, bool]:
    """Returns (activity_level, is_logged). is_logged=False means default was used."""
    today = today_utc_date()
    logged = get_activity_for_date(db, user_id, today)
    if logged:
        return logged, True
    return default_activity_for_user(db, user_id), False


# ── Edit window (19:00 prev day UTC → 08:00 target day UTC) ──────────────────

WINDOW_OPEN_HOUR = 19   # 7 PM prev day
WINDOW_CLOSE_HOUR = 8   # 8 AM target day


def editable_target_date(now: Optional[datetime] = None) -> Optional[str]:
    """Which date can currently be edited? None = outside the window."""
    now = now or datetime.now(timezone.utc)
    if now.hour >= WINDOW_OPEN_HOUR:
        return (now + timedelta(days=1)).strftime("%Y-%m-%d")
    if now.hour < WINDOW_CLOSE_HOUR:
        return now.strftime("%Y-%m-%d")
    return None


def is_in_edit_window(target_date: str, now: Optional[datetime] = None) -> bool:
    return editable_target_date(now) == target_date


# ── Step 9: Convenience — assemble a full daily plan ─────────────────────────

def _build_warnings(calorie_status: str, carb_status: str) -> list[str]:
    w: list[str] = []
    if calorie_status == "lower_bound_applied":
        w.append("Calorie target was raised to the safety lower bound.")
    if calorie_status == "lower_overrides_upper":
        w.append(
            "Calorie lower bound exceeds the goal cap — consider switching to "
            "body_recomp or fat_loss_slow, or raising activity level."
        )
    if carb_status == "below_range_unavoidable":
        w.append("Minimum carbohydrate cannot be met under the current calorie target.")
    return w


def build_daily_targets(db: Session, user: models.User) -> dict:
    """Assemble today's calorie and macro targets. Safe to return from an API."""
    profile = user.bmr_profile
    if not profile:
        return {"has_bmr_profile": False}

    activity, is_logged = resolve_activity_for_today(db, user.id)
    bmr = compute_bmr(profile.age, profile.gender, profile.height_cm, profile.weight_kg)
    tdee = compute_tdee(bmr, activity)
    calories, calorie_status = compute_calorie_target(profile.goal, tdee, bmr)
    is_exerciser = activity in EXERCISER_LEVELS

    macros = compute_macros(
        calories=calories,
        weight_kg=profile.weight_kg,
        gender=profile.gender,
        age=profile.age,
        goal=profile.goal,
        is_exerciser=is_exerciser,
    )

    warnings = _build_warnings(calorie_status, macros["carb_status"])

    return {
        "has_bmr_profile": True,
        "bmr": round(bmr, 1),
        "tdee": round(tdee, 1),
        "activity_level": activity,
        "activity_is_default": not is_logged,
        "goal": normalize_goal(profile.goal),
        "calorie_target": macros["calories"],
        "calorie_status": calorie_status,
        "protein_g": macros["protein_g"],
        "carbs_g": macros["carbs_g"],
        "fat_g": macros["fat_g"],
        "protein_band": macros["protein_band"],
        "protein_range_g": macros["protein_range_g"],
        "carbs_range_g": macros["carbs_range_g"],
        "fat_min_g": macros["fat_min_g"],
        "fat_soft_max_g": macros["fat_soft_max_g"],
        "protein_status": macros["protein_status"],
        "fat_status": macros["fat_status"],
        "carb_status": macros["carb_status"],
        "warnings": warnings,
        "is_exerciser": is_exerciser,
    }
