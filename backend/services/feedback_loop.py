"""
Execution feedback loop.

Two layers:

  daily_report(db, user, date)
    * target vs actual macros (calorie / protein / fat / carbs)
    * protein achievement rate
    * calorie overage rate
    * which planned entries were actually logged today

  weekly_review(db, user, end_date=today)
    * 7-day averages
    * weight trend
    * adjustment verdict: raise/lower calories, bump protein, etc.
    * flags: "user keeps skipping food X — mark as non-substitutable"

These reports are what the system uses to *continuously adjust* — no
manual nutritionist review required."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import fmean
from typing import Optional

from sqlalchemy.orm import Session

import models
from services import calorie as calorie_svc


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _day_diet_totals(db: Session, user_id: int, date_str: str) -> dict:
    rows = (
        db.query(models.DietLog)
        .filter(
            models.DietLog.user_id == user_id,
            models.DietLog.date == date_str,
        )
        .all()
    )
    return {
        "kcal": sum(r.calories or 0 for r in rows),
        "protein_g": round(sum(r.protein_g or 0.0 for r in rows), 1),
        "carbs_g": round(sum(r.carbs_g or 0.0 for r in rows), 1),
        "fat_g": round(sum(r.fat_g or 0.0 for r in rows), 1),
        "entries": len(rows),
        "food_names": [r.food_name for r in rows],
    }


def _day_exercise_kcal(db: Session, user_id: int, date_str: str) -> int:
    total = (
        db.query(models.ExerciseLog.calories_burned)
        .filter(
            models.ExerciseLog.user_id == user_id,
            models.ExerciseLog.date == date_str,
        )
        .all()
    )
    return sum(r[0] or 0 for r in total)


# ── Daily report ─────────────────────────────────────────────────────────────

def daily_report(db: Session, user: models.User, date_str: Optional[str] = None) -> dict:
    date_str = date_str or calorie_svc.today_utc_date()
    targets = calorie_svc.build_daily_targets(db, user)
    if not targets.get("has_bmr_profile"):
        return {"has_bmr_profile": False, "date": date_str}

    actual = _day_diet_totals(db, user.id, date_str)
    exercise_kcal = _day_exercise_kcal(db, user.id, date_str)

    target_kcal = targets["calorie_target"]
    target_protein = targets["protein_g"]
    target_fat = targets["fat_g"]
    target_carbs = targets["carbs_g"]

    rates = {
        "kcal": _safe_ratio(actual["kcal"], target_kcal),
        "protein": _safe_ratio(actual["protein_g"], target_protein),
        "carbs": _safe_ratio(actual["carbs_g"], target_carbs),
        "fat": _safe_ratio(actual["fat_g"], target_fat),
    }

    # Status labels guide the UI:
    status = {
        "kcal": _kcal_status(rates["kcal"]),
        "protein": _protein_status(rates["protein"]),
        "carbs": _range_status(rates["carbs"]),
        "fat": _fat_status(rates["fat"]),
    }

    planned_slots = _planned_slots_fulfilled(db, user.id, date_str)

    notes: list[str] = []
    if status["kcal"] == "over":
        notes.append(
            f"热量超出目标 {int((rates['kcal'] - 1) * 100)}%，今日建议增加轻量活动或减少加餐。"
        )
    if status["protein"] == "under":
        notes.append(
            f"蛋白质完成率 {int(rates['protein'] * 100)}%，建议加一份鸡胸/豆腐/酸奶。"
        )
    if status["fat"] == "under":
        notes.append("脂肪未达底线，加入一小份坚果或一勺橄榄油即可。")

    return {
        "has_bmr_profile": True,
        "date": date_str,
        "target": {
            "kcal": target_kcal,
            "protein_g": target_protein,
            "carbs_g": target_carbs,
            "fat_g": target_fat,
        },
        "actual": actual,
        "exercise_kcal": exercise_kcal,
        "net_kcal": actual["kcal"] - exercise_kcal,
        "achievement_rate": rates,
        "status": status,
        "planned_slots": planned_slots,
        "notes": notes,
    }


# ── Weekly review ────────────────────────────────────────────────────────────

def weekly_review(db: Session, user: models.User, end_date: Optional[str] = None) -> dict:
    if end_date:
        end = _parse_date(end_date)
    else:
        end = datetime.now(timezone.utc)
    dates = [(end - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]

    targets = calorie_svc.build_daily_targets(db, user)
    if not targets.get("has_bmr_profile"):
        return {"has_bmr_profile": False}

    dailies = [daily_report(db, user, d) for d in dates]

    # Means (only across days with any log)
    logged = [d for d in dailies if d["actual"]["entries"] > 0]
    if not logged:
        return {
            "has_bmr_profile": True,
            "dates": dates,
            "dailies": dailies,
            "message_zh": "最近 7 天没有饮食记录，无法生成周复盘。",
            "message_en": "No dietary logs in the last 7 days — nothing to review.",
        }

    avg = {
        "kcal": round(fmean(d["actual"]["kcal"] for d in logged), 1),
        "protein_g": round(fmean(d["actual"]["protein_g"] for d in logged), 1),
        "carbs_g": round(fmean(d["actual"]["carbs_g"] for d in logged), 1),
        "fat_g": round(fmean(d["actual"]["fat_g"] for d in logged), 1),
        "protein_achievement": round(fmean(d["achievement_rate"]["protein"] for d in logged), 3),
        "kcal_achievement": round(fmean(d["achievement_rate"]["kcal"] for d in logged), 3),
    }

    # Weight trend: earliest vs latest physical_conditions inside the window.
    weight_rows = (
        db.query(models.PhysicalCondition.date, models.PhysicalCondition.weight_kg)
        .filter(
            models.PhysicalCondition.user_id == user.id,
            models.PhysicalCondition.weight_kg.isnot(None),
            models.PhysicalCondition.date >= dates[0],
            models.PhysicalCondition.date <= dates[-1],
        )
        .order_by(models.PhysicalCondition.date.asc())
        .all()
    )
    if len(weight_rows) >= 2:
        weight_trend = round(weight_rows[-1][1] - weight_rows[0][1], 2)
    else:
        weight_trend = None

    adjustments = _adjustment_suggestions(avg, weight_trend, targets, user)

    skipped_foods = _detect_skipped_key_foods(db, user.id, dates)

    return {
        "has_bmr_profile": True,
        "dates": dates,
        "averages": avg,
        "weight_trend_kg": weight_trend,
        "adjustments": adjustments,
        "skipped_key_foods": skipped_foods,
        "dailies": dailies,
    }


# ── Support logic ────────────────────────────────────────────────────────────

def _safe_ratio(actual: float, target: float) -> float:
    if target <= 0:
        return 0.0
    return round(actual / target, 3)


def _kcal_status(r: float) -> str:
    if r >= 1.15: return "over"
    if r <= 0.80: return "under"
    return "on_track"


def _protein_status(r: float) -> str:
    if r < 0.80: return "under"
    if r > 1.30: return "over"
    return "on_track"


def _fat_status(r: float) -> str:
    if r < 0.70: return "under"
    if r > 1.40: return "over"
    return "on_track"


def _range_status(r: float) -> str:
    if r < 0.80: return "under"
    if r > 1.20: return "over"
    return "on_track"


def _planned_slots_fulfilled(db: Session, user_id: int, date_str: str) -> dict:
    """Did the user log diet for every slot they had planned?"""
    planned = (
        db.query(models.MealPlanEntry.meal_type)
        .filter(
            models.MealPlanEntry.user_id == user_id,
            models.MealPlanEntry.date == date_str,
        )
        .all()
    )
    planned_slots = {r[0] for r in planned}
    logged_slots = {
        r[0] for r in db.query(models.DietLog.meal_type)
        .filter(
            models.DietLog.user_id == user_id,
            models.DietLog.date == date_str,
        )
        .all()
    }
    return {
        "planned": sorted(planned_slots),
        "logged": sorted(logged_slots),
        "missing": sorted(planned_slots - logged_slots),
    }


def _adjustment_suggestions(
    avg: dict, weight_trend: Optional[float], targets: dict, user: models.User,
) -> list[dict]:
    """Apply the rule table the user already documented in the SOP."""
    out: list[dict] = []
    goal = targets.get("goal", "")
    want_fat_loss = goal.startswith("fat_loss")
    weight_kg = user.bmr_profile.weight_kg if user.bmr_profile else None

    # Too slow / too fast weight loss (only evaluate if we have a measurement)
    if want_fat_loss and weight_trend is not None and weight_kg:
        weekly_target_pct = 0.006  # ~0.6 %/week typical safe fat-loss rate
        lower_pct = -0.010
        upper_pct = -0.002
        pct = weight_trend / weight_kg
        kcal_delta_pct = 0
        kcal_delta = 0
        if pct > upper_pct and avg["kcal_achievement"] < 1.05:
            kcal_delta_pct = -0.05
            kcal_delta = round(targets["calorie_target"] * kcal_delta_pct)
            out.append({
                "kind": "calorie_down",
                "delta_kcal": kcal_delta,
                "message_zh": f"体重下降偏慢 ({weight_trend:+.2f} kg)，建议将每日热量下调约 {abs(kcal_delta)} kcal。",
                "message_en": f"Weight loss too slow ({weight_trend:+.2f} kg). Lower daily kcal by ~{abs(kcal_delta)}.",
            })
        elif pct < lower_pct:
            kcal_delta_pct = 0.05
            kcal_delta = round(targets["calorie_target"] * kcal_delta_pct)
            out.append({
                "kind": "calorie_up",
                "delta_kcal": kcal_delta,
                "message_zh": f"体重下降过快 ({weight_trend:+.2f} kg)，建议将每日热量上调约 {kcal_delta} kcal，保护基础代谢。",
                "message_en": f"Weight loss too fast ({weight_trend:+.2f} kg). Raise daily kcal by ~{kcal_delta}.",
            })

    # Protein chronically insufficient
    if avg["protein_achievement"] < 0.85:
        out.append({
            "kind": "protein_up",
            "message_zh": "蛋白质一周平均达成率不足 85%，建议提高高蛋白食物（鸡胸/虾仁/酸奶）的周频率。",
            "message_en": (
                "Weekly protein achievement below 85% — raise frequency of high-protein "
                "foods (chicken breast, shrimp, yogurt)."
            ),
        })

    # Carbs chronically over — often the fat-loss blocker
    carb_ratio = _safe_ratio(avg["carbs_g"], targets["carbs_g"])
    if want_fat_loss and carb_ratio > 1.20:
        out.append({
            "kind": "carb_trim",
            "message_zh": f"碳水化合物摄入持续超标 ({int(carb_ratio*100)}%)，建议主食减量或换慢碳。",
            "message_en": (
                f"Carbohydrates running {int(carb_ratio*100)}% of target — cut staple portion "
                "or swap fast-carb for slow-carb."
            ),
        })

    return out


def _detect_skipped_key_foods(db: Session, user_id: int, dates: list[str]) -> list[dict]:
    """Find foods that the plan scheduled but the user never logged. If the
    same food is skipped repeatedly, surface it for a 'supplement or drop'
    decision."""
    planned = (
        db.query(models.MealPlanEntry)
        .filter(
            models.MealPlanEntry.user_id == user_id,
            models.MealPlanEntry.date.in_(dates),
        )
        .all()
    )
    if not planned:
        return []
    logged_names = Counter()
    for row in db.query(models.DietLog.food_name).filter(
        models.DietLog.user_id == user_id,
        models.DietLog.date.in_(dates),
    ).all():
        logged_names[row[0]] += 1

    planned_counts: dict[str, int] = defaultdict(int)
    for entry in planned:
        name = entry.recipe.name if entry.recipe else (entry.custom_name or "")
        if name:
            planned_counts[name] += 1

    skipped = []
    for name, count in planned_counts.items():
        hit = logged_names.get(name, 0)
        if count >= 2 and hit == 0:
            skipped.append({
                "name": name,
                "planned_count": count,
                "logged_count": hit,
                "message_zh": f"本周计划中「{name}」出现 {count} 次但从未记录食用，建议替换或补充同类食物。",
                "message_en": (
                    f"'{name}' was planned {count}× but never logged — swap it out or "
                    "add a same-category substitute."
                ),
            })
    return skipped
