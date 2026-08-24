from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from services.legacy_write_gate import reject_legacy_write
from database import get_db
from services import calorie, deepseek, llm_quota, local_dates, planning_context as pc
from services.local_dates import date_or_422

router = APIRouter(prefix="/api/diet", tags=["diet"])
app_log = logging.getLogger("compass.app")
llm_log = logging.getLogger("compass.llm")
DietMealType = Literal["breakfast", "lunch", "dinner", "snack"]

class DietLogRequest(BaseModel):
    meal_type: DietMealType
    food_name: str = Field(..., min_length=1, max_length=120)
    calories: int = Field(..., ge=0, le=5000)
    protein_g: Optional[float] = Field(default=0.0, ge=0, le=500)
    carbs_g: Optional[float] = Field(default=0.0, ge=0, le=1000)
    fat_g: Optional[float] = Field(default=0.0, ge=0, le=500)
    date: Optional[str] = Field(default=None, min_length=10, max_length=10)


class DietIngredientRequest(BaseModel):
    meal_type: DietMealType
    ingredients: str = Field(..., min_length=1, max_length=4000)        # raw ingredient list, one per line
    date: Optional[str] = Field(default=None, min_length=10, max_length=10)


def _refund_diet_estimate_quota(
    db: Optional[Session],
    user_id: Optional[int],
    call_log_id: Optional[int],
) -> None:
    if call_log_id is None or db is None or user_id is None:
        return
    if llm_quota.refund_call(db, call_log_id, user_id=user_id, kind=llm_quota.DIET_ESTIMATE):
        db.commit()


def estimate_nutrition_with_deepseek(
    ingredients: str,
    db: Optional[Session] = None,
    user_id: Optional[int] = None,
) -> dict:
    """
    Use DeepSeek to estimate nutrition values from raw ingredient text.
    Returns:
        {
            "food_name": str,
            "calories": int,
            "protein_g": float,
            "carbs_g": float,
            "fat_g": float
        }
    """
    ingredient_lines = len([line for line in ingredients.splitlines() if line.strip()])
    llm_log.info(
        "diet ingredient estimation requested",
        extra={
            "event": "diet_estimation_requested",
            "domain": "diet",
            "ingredient_line_count": ingredient_lines,
            "ingredient_chars": len(ingredients),
        },
    )

    quota_call_id: Optional[int] = None
    if db is not None and user_id is not None:
        try:
            quota_usage = llm_quota.check_and_consume(db, user_id, llm_quota.DIET_ESTIMATE)
        except llm_quota.LLMQuotaExceeded as exc:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "quota_exhausted",
                    "kind": llm_quota.DIET_ESTIMATE,
                    "message_zh": "本周 AI 营养估算次数已用完，先保存为待分析记录。",
                    "message_en": "AI nutrition-estimate quota is exhausted for this week; the log was saved as pending.",
                    "next_refresh_at": exc.next_refresh_at.isoformat()
                    if getattr(exc, "next_refresh_at", None) else None,
                },
            )
        else:
            quota_call_id = quota_usage.get("call_log_id")
            db.commit()

    system_prompt = """
You are a nutrition analysis assistant.

The user will provide a meal ingredient list.
You must estimate the nutrition for the whole meal.

Return ONLY valid JSON in this exact format:
{
  "food_name": "meal name",
  "calories": 0,
  "protein_g": 0,
  "carbs_g": 0,
  "fat_g": 0
}

Rules:
1. Return only JSON
2. calories must be an integer
3. protein_g, carbs_g, fat_g must be numbers
4. If the quantity is unclear, make a reasonable real-world estimate
5. The output must be valid JSON
""".strip()

    user_prompt = f"""
Estimate the nutrition for the following meal ingredients:

{ingredients}
""".strip()

    def _json_from_content(content: str) -> dict:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise
            return json.loads(content[start:end + 1])

    def _bump_estimate(value: object) -> float:
        return max(0.0, float(value or 0) * 1.1)

    try:
        client = deepseek.get_client()
        resp = client.chat.completions.create(
            model=deepseek.DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1200,
        )

        choice = resp.choices[0]
        message = choice.message
        content = message.content
        if not content:
            reasoning_content = getattr(message, "reasoning_content", "") or ""
            llm_log.warning(
                "diet ingredient estimation returned empty content",
                extra={
                    "event": "diet_estimation_empty_content",
                    "domain": "diet",
                    "ingredient_line_count": ingredient_lines,
                    "finish_reason": getattr(choice, "finish_reason", None),
                    "reasoning_content_chars": len(reasoning_content),
                },
            )
            raise ValueError("Empty response from DeepSeek")

        data = _json_from_content(content)

        result = {
            "food_name": str(data.get("food_name", "食材餐")),
            "calories": int(round(_bump_estimate(data.get("calories", 0)))),
            "protein_g": round(_bump_estimate(data.get("protein_g", 0.0)), 1),
            "carbs_g": round(_bump_estimate(data.get("carbs_g", 0.0)), 1),
            "fat_g": round(_bump_estimate(data.get("fat_g", 0.0)), 1),
        }
        llm_log.info(
            "diet ingredient estimation succeeded",
            extra={
                "event": "diet_estimation_succeeded",
                "domain": "diet",
                "ingredient_line_count": ingredient_lines,
                "food_name": result["food_name"][:80],
                "calories": result["calories"],
            },
        )
        return result
    except json.JSONDecodeError:
        _refund_diet_estimate_quota(db, user_id, quota_call_id)
        llm_log.warning(
            "diet ingredient estimation returned invalid json",
            extra={
                "event": "diet_estimation_invalid_json",
                "domain": "diet",
                "ingredient_line_count": ingredient_lines,
            },
        )
        raise HTTPException(
            status_code=502,
            detail="DeepSeek returned invalid JSON"
        )
    except HTTPException:
        _refund_diet_estimate_quota(db, user_id, quota_call_id)
        llm_log.warning(
            "diet ingredient estimation rejected",
            extra={
                "event": "diet_estimation_rejected",
                "domain": "diet",
                "ingredient_line_count": ingredient_lines,
            },
        )
        raise
    except Exception as e:
        _refund_diet_estimate_quota(db, user_id, quota_call_id)
        llm_log.exception(
            "diet ingredient estimation failed",
            extra={
                "event": "diet_estimation_failed",
                "domain": "diet",
                "ingredient_line_count": ingredient_lines,
                "exc_class": e.__class__.__name__,
            },
        )
        raise HTTPException(
            status_code=502,
            detail="DeepSeek nutrition estimation failed"
        )


def pending_nutrition_result(ingredients: str, meal_type: str) -> dict:
    meal_labels = {
        "breakfast": "早餐",
        "lunch": "午餐",
        "dinner": "晚餐",
        "snack": "加餐",
    }
    lines = [line.strip() for line in ingredients.splitlines() if line.strip()]
    preview = " + ".join(lines[:2])
    if len(lines) > 2:
        preview += " ..."
    food_name = preview or meal_labels.get(meal_type, meal_type) or "食材餐"
    return {
        "food_name": food_name[:80],
        "calories": 0,
        "protein_g": 0.0,
        "carbs_g": 0.0,
        "fat_g": 0.0,
    }


def apply_nutrition_result(entry: models.DietLog, result: dict) -> None:
    entry.food_name = result["food_name"] or entry.food_name
    entry.calories = result["calories"]
    entry.protein_g = result["protein_g"]
    entry.carbs_g = result["carbs_g"]
    entry.fat_g = result["fat_g"]


@router.post("/log")
def log_diet(
    body: DietLogRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reject_legacy_write()
    if body.meal_type not in {"breakfast", "lunch", "dinner", "snack"}:
        raise HTTPException(status_code=422, detail="Invalid meal_type")
    date = date_or_422(body.date)
    entry = models.DietLog(
        user_id=current_user.id,
        date=date,
        meal_type=body.meal_type,
        food_name=body.food_name,
        calories=body.calories,
        protein_g=body.protein_g or 0.0,
        carbs_g=body.carbs_g or 0.0,
        fat_g=body.fat_g or 0.0,
    )
    db.add(entry)
    pc.mark_plan_slot_recorded(db, current_user.id, date, body.meal_type)
    db.commit()
    db.refresh(entry)
    app_log.info(
        "diet logged",
        extra={
            "event": "diet_logged",
            "domain": "diet",
            "source": "manual",
            "log_id": entry.id,
            "date": date,
            "meal_type": body.meal_type,
            "food_name": (body.food_name or "")[:80],
            "calories": body.calories,
            "protein_g": body.protein_g or 0.0,
            "carbs_g": body.carbs_g or 0.0,
            "fat_g": body.fat_g or 0.0,
        },
    )
    return {"id": entry.id, "message": "Diet entry logged"}


@router.post("/log-ingredients")
def log_diet_ingredients(
    body: DietIngredientRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reject_legacy_write()
    """
    Log a meal by raw ingredient list.
    DeepSeek estimates nutrition values and stores them in DietLog.
    """
    if not body.ingredients or not body.ingredients.strip():
        raise HTTPException(status_code=400, detail="ingredients cannot be empty")
    if body.meal_type not in {"breakfast", "lunch", "dinner", "snack"}:
        raise HTTPException(status_code=422, detail="Invalid meal_type")

    date_str = date_or_422(body.date)
    meal_labels = {
        "breakfast": "早餐",
        "lunch": "午餐",
        "dinner": "晚餐",
        "snack": "加餐",
    }

    nutrition_status = "estimated"
    estimation_error = None
    try:
        result = estimate_nutrition_with_deepseek(body.ingredients, db, current_user.id)
    except HTTPException as exc:
        nutrition_status = "pending"
        estimation_error = str(exc.detail)
        llm_log.warning(
            "diet ingredient estimation deferred",
            extra={
                "event": "diet_estimation_deferred",
                "domain": "diet",
                "ingredient_line_count": len([line for line in body.ingredients.splitlines() if line.strip()]),
                "status_code": exc.status_code,
            },
        )
        result = pending_nutrition_result(body.ingredients, body.meal_type)

    food_name = result["food_name"] or meal_labels.get(body.meal_type, body.meal_type)

    entry = models.DietLog(
        user_id=current_user.id,
        date=date_str,
        meal_type=body.meal_type,
        food_name=food_name,
        ingredients=body.ingredients,
        calories=result["calories"],
        protein_g=result["protein_g"],
        carbs_g=result["carbs_g"],
        fat_g=result["fat_g"],
    )
    db.add(entry)
    pc.mark_plan_slot_recorded(db, current_user.id, date_str, body.meal_type)
    db.commit()
    db.refresh(entry)
    app_log.info(
        "diet ingredients logged",
        extra={
            "event": "diet_logged",
            "domain": "diet",
            "source": "ingredients_llm" if nutrition_status == "estimated" else "ingredients_pending",
            "log_id": entry.id,
            "date": date_str,
            "meal_type": body.meal_type,
            "food_name": entry.food_name[:80],
            "ingredient_line_count": len([line for line in body.ingredients.splitlines() if line.strip()]),
            "calories": entry.calories,
            "protein_g": entry.protein_g,
            "carbs_g": entry.carbs_g,
            "fat_g": entry.fat_g,
        },
    )

    return {
        "id": entry.id,
        "message": "Diet ingredients logged",
        "nutrition_status": nutrition_status,
        "estimation_error": estimation_error,
        "nutrition": {
            "food_name": entry.food_name,
            "calories": entry.calories,
            "protein_g": entry.protein_g,
            "carbs_g": entry.carbs_g,
            "fat_g": entry.fat_g,
        },
    }


@router.post("/log/{log_id}/reanalyze")
def reanalyze_diet_log(
    log_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reject_legacy_write()
    entry = db.query(models.DietLog).filter(
        models.DietLog.id == log_id,
        models.DietLog.user_id == current_user.id
    ).first()

    if not entry:
        raise HTTPException(status_code=404, detail="Log not found")
    if not entry.ingredients or not entry.ingredients.strip():
        raise HTTPException(status_code=400, detail="Only ingredient-based logs can be reanalyzed")

    nutrition_status = "estimated"
    estimation_error = None
    try:
        result = estimate_nutrition_with_deepseek(entry.ingredients, db, current_user.id)
    except HTTPException as exc:
        nutrition_status = "pending"
        estimation_error = str(exc.detail)
        llm_log.warning(
            "diet ingredient reanalysis deferred",
            extra={
                "event": "diet_reanalysis_deferred",
                "domain": "diet",
                "log_id": entry.id,
                "ingredient_line_count": len([line for line in entry.ingredients.splitlines() if line.strip()]),
                "status_code": exc.status_code,
            },
        )
    else:
        apply_nutrition_result(entry, result)
        db.commit()
        db.refresh(entry)
        app_log.info(
            "diet ingredients reanalyzed",
            extra={
                "event": "diet_reanalyzed",
                "domain": "diet",
                "log_id": entry.id,
                "date": entry.date,
                "meal_type": entry.meal_type,
                "food_name": entry.food_name[:80],
                "calories": entry.calories,
                "protein_g": entry.protein_g,
                "carbs_g": entry.carbs_g,
                "fat_g": entry.fat_g,
            },
        )

    return {
        "id": entry.id,
        "nutrition_status": nutrition_status,
        "estimation_error": estimation_error,
        "nutrition": {
            "food_name": entry.food_name,
            "calories": entry.calories,
            "protein_g": entry.protein_g,
            "carbs_g": entry.carbs_g,
            "fat_g": entry.fat_g,
        },
    }


@router.delete("/log/{log_id}")
def delete_diet_log(
    log_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reject_legacy_write()
    entry = db.query(models.DietLog).filter(
        models.DietLog.id == log_id,
        models.DietLog.user_id == current_user.id
    ).first()

    if not entry:
        raise HTTPException(status_code=404, detail="Log not found")

    date, meal_type = entry.date, entry.meal_type
    app_log.info(
        "diet log deleted",
        extra={
            "event": "diet_log_deleted",
            "domain": "diet",
            "log_id": entry.id,
            "date": entry.date,
            "meal_type": entry.meal_type,
            "source": "ingredients_llm" if entry.ingredients else "manual",
            "calories": entry.calories,
        },
    )
    db.delete(entry)
    db.flush()
    pc.revert_plan_slot_if_no_record(db, current_user.id, date, meal_type)
    db.commit()
    return {"message": "Deleted"}


@router.get("/today")
def get_diet_today(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = local_dates.today_key()
    logs = (
        db.query(models.DietLog)
        .filter(
            models.DietLog.user_id == current_user.id,
            models.DietLog.date == today
        )
        .order_by(models.DietLog.logged_at)
        .all()
    )

    total_calories = sum(l.calories for l in logs)
    total_protein = sum(l.protein_g for l in logs)
    total_carbs = sum(l.carbs_g for l in logs)
    total_fat = sum(l.fat_g for l in logs)

    targets = calorie.build_daily_targets(db, current_user)
    daily_target = targets.get("calorie_target", 0) or 0
    tdee_value = targets.get("tdee", 0) or 0

    protein_classification = None
    if targets.get("has_bmr_profile"):
        p = current_user.bmr_profile
        protein_classification = calorie.classify_protein(
            protein_g=total_protein,
            weight_kg=p.weight_kg,
            goal=p.goal,
            is_exerciser=targets.get("is_exerciser", False),
        )

    return {
        "logs": [
            {
                "id": l.id,
                "meal_type": l.meal_type,
                "food_name": l.food_name,
                "ingredients": l.ingredients,
                "calories": l.calories,
                "protein_g": l.protein_g,
                "carbs_g": l.carbs_g,
                "fat_g": l.fat_g,
                "logged_at": l.logged_at.isoformat(),
            }
            for l in logs
        ],
        "totals": {
            "calories": total_calories,
            "protein_g": round(total_protein, 1),
            "carbs_g": round(total_carbs, 1),
            "fat_g": round(total_fat, 1),
        },
        "tdee": round(tdee_value),
        "calorie_target": round(daily_target),
        "remaining_calories": round(daily_target - total_calories),
        "macro_targets": {
            "protein_g": targets.get("protein_g", 0),
            "carbs_g": targets.get("carbs_g", 0),
            "fat_g": targets.get("fat_g", 0),
        },
        "protein_classification": protein_classification,
        "daily_targets": targets,
    }


@router.get("/history")
def get_diet_history(
    days: int = Query(7, ge=1, le=90),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = []

    for d in local_dates.date_range_ending_today(days):
        logs = (
            db.query(models.DietLog)
            .filter(
                models.DietLog.user_id == current_user.id,
                models.DietLog.date == d
            )
            .all()
        )

        result.append({
            "date": d,
            "total_calories": sum(l.calories for l in logs),
            "breakdown": {
                "protein_g": round(sum(l.protein_g for l in logs), 1),
                "carbs_g": round(sum(l.carbs_g for l in logs), 1),
                "fat_g": round(sum(l.fat_g for l in logs), 1),
            },
        })

    return result
