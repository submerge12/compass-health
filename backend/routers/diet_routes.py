from datetime import datetime, timedelta, timezone
import json
import logging
import os
from typing import Optional
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
import httpx
from openai import OpenAI

import models
from auth import get_current_user
from database import get_db
from services import calorie, planning_context as pc

router = APIRouter(prefix="/api/diet", tags=["diet"])
app_log = logging.getLogger("compass.app")
llm_log = logging.getLogger("compass.llm")

load_dotenv()


def get_deepseek_client() -> OpenAI:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY is not configured")
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com", http_client=httpx.Client(trust_env=False))


class DietLogRequest(BaseModel):
    meal_type: str          # breakfast / lunch / dinner / snack
    food_name: str
    calories: int
    protein_g: Optional[float] = 0.0
    carbs_g: Optional[float] = 0.0
    fat_g: Optional[float] = 0.0
    date: Optional[str] = None


class DietIngredientRequest(BaseModel):
    meal_type: str          # breakfast / lunch / dinner / snack
    ingredients: str        # raw ingredient list, one per line
    date: Optional[str] = None


def estimate_nutrition_with_deepseek(ingredients: str) -> dict:
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

    client = get_deepseek_client()

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

    try:
        resp = client.chat.completions.create(
            model="deepseek-reasoner",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=300,
        )

        content = resp.choices[0].message.content
        if not content:
            raise ValueError("Empty response from DeepSeek")

        data = json.loads(content)

        result = {
            "food_name": str(data.get("food_name", "食材餐")),
            "calories": int(data.get("calories", 0)),
            "protein_g": float(data.get("protein_g", 0.0)),
            "carbs_g": float(data.get("carbs_g", 0.0)),
            "fat_g": float(data.get("fat_g", 0.0)),
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
        llm_log.warning(
            "diet ingredient estimation returned invalid json",
            extra={
                "event": "diet_estimation_invalid_json",
                "domain": "diet",
                "ingredient_line_count": ingredient_lines,
            },
        )
        raise HTTPException(
            status_code=500,
            detail="DeepSeek returned invalid JSON"
        )
    except HTTPException:
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
            status_code=500,
            detail=f"DeepSeek nutrition estimation failed: {str(e)}"
        )


@router.post("/log")
def log_diet(
    body: DietLogRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    date = body.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
    """
    Log a meal by raw ingredient list.
    DeepSeek estimates nutrition values and stores them in DietLog.
    """
    if not body.ingredients or not body.ingredients.strip():
        raise HTTPException(status_code=400, detail="ingredients cannot be empty")

    date_str = body.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    meal_labels = {
        "breakfast": "早餐",
        "lunch": "午餐",
        "dinner": "晚餐",
        "snack": "加餐",
    }

    result = estimate_nutrition_with_deepseek(body.ingredients)

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
            "source": "ingredients_llm",
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
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
    days: int = 7,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = datetime.now(timezone.utc)
    result = []

    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
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
