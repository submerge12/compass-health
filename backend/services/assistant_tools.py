from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models
from services import (
    calorie,
    food_library as FL,
    local_dates,
    menu_planner,
    nutrition_audit,
    planning_context as pc,
    recipe_access,
)


ACTION_SAVE_MEMORY = "save_nutrition_memory"
ACTION_UPSERT_FIXED_BREAKFAST = "upsert_fixed_breakfast"
ACTION_APPLY_DAY_PLAN_SLOT = "apply_day_plan_slot"
ACTION_TYPES = {
    ACTION_SAVE_MEMORY,
    ACTION_UPSERT_FIXED_BREAKFAST,
    ACTION_APPLY_DAY_PLAN_SLOT,
}

STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_EXECUTED = "executed"
STATUS_SUPERSEDED = "superseded"

VALID_MEAL_TYPES = {"breakfast", "lunch", "dinner", "snack"}
_NUTRIENT_KEYS = {
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

_ALIASES: dict[str, list[str]] = {
    "sea bream": ["sea_bass", "tilapia"],
    "bream": ["sea_bass", "tilapia"],
    "seabream": ["sea_bass", "tilapia"],
    "snapper": ["sea_bass", "tilapia"],
    "dorado": ["sea_bass", "tilapia"],
    "鲷鱼": ["sea_bass", "tilapia"],
    "鯛魚": ["sea_bass", "tilapia"],
    "鲈鱼": ["sea_bass"],
    "虾": ["shrimp"],
    "虾仁": ["shrimp"],
    "鸡腿": ["chicken_thigh_skinless"],
    "去皮鸡腿": ["chicken_thigh_skinless"],
    "鸡蛋": ["whole_egg"],
    "全蛋": ["whole_egg"],
    "牛奶": ["milk"],
    "希腊酸奶": ["greek_yogurt"],
    "酸奶": ["greek_yogurt"],
    "糙米饭": ["brown_rice"],
    "糙米": ["brown_rice"],
    "西蓝花": ["broccoli"],
    "西兰花": ["broccoli"],
    "紫菜": ["seaweed"],
    "海苔": ["seaweed"],
    "牛里脊": ["beef_tenderloin"],
    "蛤蜊": ["clam"],
    "菠菜": ["spinach"],
    "胡萝卜": ["carrot"],
    "核桃": ["walnuts"],
    "杏仁": ["almonds"],
    "坚果": ["walnuts", "almonds"],
    "橄榄油": ["olive_oil"],
    "牛肉": ["beef_tenderloin", "beef_sirloin"],
    "瘦牛肉": ["beef_tenderloin", "beef_sirloin"],
    "洋葱": ["onion"],
    "洋葱炒牛肉": ["beef_tenderloin", "onion"],
    "青椒": ["green_pepper"],
    "彩椒": ["bell_pepper"],
    "青椒牛肉": ["beef_tenderloin", "green_pepper"],
    "油菜": ["you_cai"],
    "娃娃菜": ["baby_napa_cabbage"],
    "虾皮": ["dried_shrimp"],
    "芝麻酱": ["sesame_paste"],
    "红豆": ["red_beans"],
    "绿豆": ["mung_beans"],
    "黑豆": ["black_beans"],
    "魔芋": ["konjac"],
    "巴沙鱼": ["basa_fish"],
    "龙利鱼": ["basa_fish"],
    "莴笋": ["celtuce"],
    "西葫芦": ["zucchini"],
    "鲐鱼": ["mackerel"],
    "青花鱼": ["mackerel"],
}


def _safe_loads(raw: Optional[str], fallback: Any) -> Any:
    if raw is None:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _norm(text: str) -> str:
    value = str(text or "").strip().lower()
    value = re.sub(r"[\s\-_()/（）]+", " ", value)
    value = re.sub(r"[^\w\u4e00-\u9fff ]+", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _food_brief(slug: str, *, score: float | None = None) -> dict:
    entry = FL.FOOD_LIBRARY[slug]
    out = {
        "slug": slug,
        "name_zh": FL.display_name(slug, "zh"),
        "name_en": FL.display_name(slug, "en"),
        "primary_macro": entry.get("primary_macro"),
        "execution_buckets": list(entry.get("execution_buckets", ())),
        "micronutrient_roles": list(entry.get("micronutrient_roles", ())),
        "per_100g": {
            "kcal": entry.get("kcal_per_100g", 0),
            "protein_g": entry.get("protein_per_100g", 0),
            "carbs_g": entry.get("carbs_per_100g", 0),
            "fat_g": entry.get("fat_per_100g", 0),
        },
    }
    if score is not None:
        out["score"] = round(score, 2)
    return out


def _serialize_action(row: models.AssistantPendingAction) -> dict:
    return {
        "id": row.id,
        "action_type": row.action_type,
        "summary": row.summary,
        "status": row.status,
        "payload": _safe_loads(row.payload_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "executed_at": row.executed_at.isoformat() if row.executed_at else None,
    }


def _serialize_fixed_meal(row: models.UserFixedMeal) -> dict:
    return {
        "id": row.id,
        "weekday": row.weekday,
        "meal_type": row.meal_type,
        "recipe_id": row.recipe_id,
        "recipe_name": row.recipe.name if row.recipe else None,
        "custom_name": row.custom_name,
        "portion_g": row.portion_g,
        "calories": row.calories,
        "protein_g": row.protein_g,
        "carbs_g": row.carbs_g,
        "fat_g": row.fat_g,
    }


def get_nutrition_memory(db: Session, user_id: int) -> dict:
    row = (
        db.query(models.UserNutritionMemory)
        .filter(models.UserNutritionMemory.user_id == user_id)
        .first()
    )
    memory = _safe_loads(row.memory_json, {}) if row else {}
    if not isinstance(memory, dict):
        memory = {}
    return {
        "memory": memory,
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
    }


def upsert_nutrition_memory(db: Session, user_id: int, payload: dict) -> dict:
    incoming = payload.get("memory")
    if incoming is None:
        incoming = payload.get("patch", {})
    if not isinstance(incoming, dict):
        raise HTTPException(status_code=422, detail="memory must be an object")

    row = (
        db.query(models.UserNutritionMemory)
        .filter(models.UserNutritionMemory.user_id == user_id)
        .first()
    )
    current = {}
    if row is not None:
        current = _safe_loads(row.memory_json, {})
        if not isinstance(current, dict):
            current = {}

    next_memory = incoming if payload.get("replace") else {**current, **incoming}
    if row is None:
        row = models.UserNutritionMemory(
            user_id=user_id,
            memory_json=_json_dumps(next_memory),
        )
        db.add(row)
    else:
        row.memory_json = _json_dumps(next_memory)
    db.flush()
    return get_nutrition_memory(db, user_id)


def get_user_targets(db: Session, user: models.User) -> dict:
    return calorie.build_daily_targets(db, user)


def search_food_library(
    query: str,
    *,
    execution_bucket: str | None = None,
    limit: int = 8,
) -> dict:
    q = _norm(query)
    if not q:
        return {"query": query, "candidates": []}

    bucket_filter = str(execution_bucket or "").strip() or None
    scored: dict[str, float] = {}

    for alias, slugs in _ALIASES.items():
        alias_norm = _norm(alias)
        if q == alias_norm or q in alias_norm or alias_norm in q:
            for idx, slug in enumerate(slugs):
                if slug in FL.FOOD_LIBRARY:
                    scored[slug] = max(scored.get(slug, 0.0), 100.0 - idx)

    q_tokens = [tok for tok in q.split(" ") if tok]
    for slug, entry in FL.FOOD_LIBRARY.items():
        if bucket_filter and bucket_filter not in entry.get("execution_buckets", ()):
            continue
        haystacks = [
            slug,
            entry.get("zh", ""),
            entry.get("en", ""),
            " ".join(entry.get("tags", ())),
            " ".join(entry.get("execution_buckets", ())),
        ]
        normalized = [_norm(x) for x in haystacks if x]
        score = 0.0
        if q == _norm(slug):
            score += 90
        for text in normalized:
            if not text:
                continue
            if q == text:
                score += 80
            elif q in text:
                score += 48
            elif text in q:
                score += 32
            else:
                token_hits = sum(1 for tok in q_tokens if tok and tok in text)
                score += token_hits * 8
        if bucket_filter and bucket_filter in entry.get("execution_buckets", ()):
            score += 10
        if score > 0:
            scored[slug] = max(scored.get(slug, 0.0), score)

    rows = sorted(scored.items(), key=lambda item: (-item[1], item[0]))[: max(1, min(limit, 20))]
    return {
        "query": query,
        "execution_bucket": bucket_filter,
        "candidates": [_food_brief(slug, score=score) for slug, score in rows],
    }


def _clean_ingredients(raw: Any) -> list[dict]:
    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=422, detail="ingredients must be a non-empty list")
    ingredients: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail="ingredient must be an object")
        slug = str(item.get("slug") or "").strip()
        try:
            grams = float(item.get("grams") or 0)
        except (TypeError, ValueError):
            grams = 0.0
        if slug not in FL.FOOD_LIBRARY:
            raise HTTPException(status_code=422, detail=f"Unknown food slug: {slug}")
        if grams <= 0 or grams > 5000:
            raise HTTPException(status_code=422, detail=f"Invalid grams for {slug}")
        ingredients.append({
            "slug": slug,
            "grams": round(grams, 1),
            "required": bool(item.get("required", True)),
        })
    return ingredients


def _optional_positive_float(raw: Any, field: str) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{field} must be a number")
    if value <= 0 or value > 5000:
        raise HTTPException(status_code=422, detail=f"{field} is out of range")
    return value


def calculate_foods(ingredients: list[dict]) -> dict:
    cleaned = _clean_ingredients(ingredients)
    totals = {
        "kcal": 0.0,
        "calories": 0.0,
        "protein_g": 0.0,
        "carbs_g": 0.0,
        "fat_g": 0.0,
        "nutrients": {role: 0.0 for role in FL.MICRONUTRIENT_ROLES},
    }
    items: list[dict] = []
    for item in cleaned:
        slug = item["slug"]
        grams = float(item["grams"])
        entry = FL.FOOD_LIBRARY[slug]
        factor = grams / 100.0
        macros = {
            "kcal": round(entry["kcal_per_100g"] * factor, 1),
            "calories": round(entry["kcal_per_100g"] * factor, 1),
            "protein_g": round(entry["protein_per_100g"] * factor, 1),
            "carbs_g": round(entry["carbs_per_100g"] * factor, 1),
            "fat_g": round(entry["fat_per_100g"] * factor, 1),
        }
        nutrients: dict[str, float] = {}
        for role, key in _NUTRIENT_KEYS.items():
            value = round(float(entry.get("nutrients", {}).get(key, 0) or 0) * factor, 2)
            nutrients[role] = value
            totals["nutrients"][role] += value
        totals["kcal"] += macros["kcal"]
        totals["calories"] += macros["calories"]
        totals["protein_g"] += macros["protein_g"]
        totals["carbs_g"] += macros["carbs_g"]
        totals["fat_g"] += macros["fat_g"]
        items.append({
            "slug": slug,
            "name_zh": FL.display_name(slug, "zh"),
            "name_en": FL.display_name(slug, "en"),
            "grams": grams,
            **macros,
            "nutrients": nutrients,
        })

    for key in ("kcal", "calories", "protein_g", "carbs_g", "fat_g"):
        totals[key] = round(float(totals[key]), 1)
    totals["calories"] = int(round(float(totals["calories"])))
    totals["nutrients"] = {
        role: round(float(value), 2)
        for role, value in totals["nutrients"].items()
    }
    return {"items": items, "totals": totals}


def audit_food_set(db: Session, user: models.User) -> dict:
    audit = nutrition_audit.run_audit(db, user)
    validation = audit.get("validation", {})
    return {
        "slug_count": audit.get("slug_count", 0),
        "library": audit.get("library", []),
        "validation": validation,
        "suggestions": audit.get("suggestions", [])[:12],
        "non_substitutable": audit.get("non_substitutable", [])[:12],
        "missing_nutrients": validation.get("missing_nutrients", []),
        "sufficiency_gaps": validation.get("sufficiency_gaps", []),
    }


def suggest_replacements(db: Session, user: models.User, slug: str) -> dict:
    if slug not in FL.FOOD_LIBRARY:
        raise HTTPException(status_code=422, detail=f"Unknown food slug: {slug}")
    user_slugs = nutrition_audit.load_user_library(db, user.id)
    all_subs = FL.substitutes_for(slug)
    in_library = nutrition_audit.substitutes_for_in_library(slug, user_slugs)
    return {
        "target": _food_brief(slug),
        "within_user_library": in_library,
        "all_library": [_food_brief(s) for s in all_subs[:20]],
    }


_FAT_LOSS_RISK_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("油炸", "fried", "油炸会把热量密度拉高，减脂期更适合改成煎、烤、蒸或空气炸。"),
    ("炸", "fried", "带“炸”的做法通常油脂更高，建议控制频率和份量。"),
    ("奶茶", "sugary_drink", "含糖饮料不太顶饱，容易占用热量预算。"),
    ("甜品", "dessert", "甜品通常糖和脂肪叠加，适合作为小份偶尔吃。"),
    ("蛋糕", "dessert", "蛋糕热量密度高，减脂期需要小份并替换掉其他主食/脂肪。"),
    ("饼干", "dessert", "饼干热量密度高、饱腹感弱，建议小份。"),
    ("薯条", "fried_starch", "油炸淀粉热量密度高，建议替换成土豆/红薯蒸烤版。"),
    ("火锅", "restaurant_meal", "火锅本身可控，风险主要在锅底、蘸料、肥肉和加工丸滑。"),
    ("麻辣烫", "restaurant_meal", "麻辣烫可控，风险主要在汤底油、加工丸滑、粉面和隐形调料。"),
    ("烧烤", "restaurant_meal", "烧烤适合选瘦肉和蔬菜，但要避开肥肉、甜酱和过量主食。"),
    ("汉堡", "fast_food", "汉堡可偶尔安排，但酱料、炸物套餐和含糖饮料会明显抬高热量。"),
    ("披萨", "fast_food", "披萨脂肪和精制碳水较集中，建议小份并搭配高蛋白和蔬菜。"),
    ("方便面", "instant_food", "方便面蛋白和蔬菜不足、钠较高，建议加蛋白和菜并少喝汤。"),
)


def _default_assessment_grams(entry: dict) -> float:
    primary = entry.get("primary_macro")
    buckets = set(entry.get("execution_buckets", ()))
    tags = set(entry.get("tags", ()))
    if "condiment" in tags:
        return min(float(entry.get("max_practical_serving_g", 10) or 10), 15.0)
    if primary == "protein":
        return 150.0
    if primary == "fat":
        return min(float(entry.get("max_practical_serving_g", 20) or 20), 20.0)
    if "dairy" in buckets:
        return 250.0
    if primary == "carb":
        return 150.0
    return min(float(entry.get("max_practical_serving_g", 200) or 200), 200.0)


def _risk_flags(query: str) -> list[dict]:
    text = str(query or "")
    flags: list[dict] = []
    seen: set[str] = set()
    for pattern, code, message in _FAT_LOSS_RISK_PATTERNS:
        if pattern in text and code not in seen:
            flags.append({"code": code, "matched": pattern, "message_zh": message})
            seen.add(code)
    return flags


def evaluate_fat_loss_food(
    db: Session,
    user: models.User,
    query: str,
    *,
    grams: float | None = None,
    meal_type: str | None = None,
    context: str | None = None,
) -> dict:
    """Return local nutrition context for the LLM to judge a wanted food.

    The final judgement is intentionally left to the assistant model, but this
    tool anchors it to local targets, known food-library matches, and risk flags.
    """
    q = str(query or "").strip()
    if not q:
        raise HTTPException(status_code=422, detail="query is required")

    matches = search_food_library(q, limit=8)
    candidates = matches.get("candidates", [])
    target = get_user_targets(db, user)
    target_kcal = float(target.get("calorie_target") or 0.0)
    target_protein = float(target.get("protein_g") or 0.0)
    selected = candidates[0] if candidates else None

    portion = None
    nutrition = None
    rule_flags = _risk_flags(q)
    traffic_light = "unknown"
    rule_summary_zh = "食材库里没有稳定匹配项，需要按做法、油糖和份量判断。"

    if selected:
        slug = selected["slug"]
        entry = FL.FOOD_LIBRARY[slug]
        portion_g = float(grams or 0) if grams is not None else _default_assessment_grams(entry)
        if portion_g <= 0 or portion_g > 2000:
            raise HTTPException(status_code=422, detail="grams must be between 0 and 2000")
        nutrition = calculate_foods([{"slug": slug, "grams": portion_g}])["totals"]
        portion = {"slug": slug, "grams": round(portion_g, 1)}

        kcal = float(nutrition.get("kcal") or 0.0)
        protein = float(nutrition.get("protein_g") or 0.0)
        fat = float(nutrition.get("fat_g") or 0.0)
        calorie_share = (kcal / target_kcal) if target_kcal > 0 else 0.0
        protein_share = (protein / target_protein) if target_protein > 0 else 0.0
        protein_per_100kcal = protein / max(kcal, 1.0) * 100.0
        buckets = set(entry.get("execution_buckets", ()))
        tags = set(entry.get("tags", ()))

        rule_flags.extend([
            {
                "code": "calorie_share",
                "value": round(calorie_share, 3),
                "message_zh": f"估算份量约占每日热量目标 {round(calorie_share * 100)}%。" if target_kcal else "用户尚未提供可用热量目标。",
            },
            {
                "code": "protein_density",
                "value": round(protein_per_100kcal, 1),
                "message_zh": f"每 100 kcal 约含蛋白 {round(protein_per_100kcal, 1)} g。",
            },
        ])

        if "condiment" in tags:
            traffic_light = "yellow"
            rule_summary_zh = "适合小量用来补风味或营养，不适合作为大份主菜。"
        elif "nut_seed_functional" in buckets or fat >= 15:
            traffic_light = "yellow"
            rule_summary_zh = "营养价值可以，但脂肪或热量密度偏高，减脂期要称量。"
        elif protein_per_100kcal >= 10 and calorie_share <= 0.25:
            traffic_light = "green"
            rule_summary_zh = "蛋白密度不错，按清淡做法和合理份量通常适合减脂。"
        elif calorie_share <= 0.18 and (entry.get("primary_macro") == "veg" or "dark_leafy_green" in buckets):
            traffic_light = "green"
            rule_summary_zh = "热量低、适合增加体积感，是减脂期友好的搭配。"
        elif calorie_share <= 0.25:
            traffic_light = "yellow"
            rule_summary_zh = "可以安排，但要看当天主食、油脂和总热量。"
        else:
            traffic_light = "red"
            rule_summary_zh = "按这个份量会占用较多热量，建议减量或替换做法。"

    if any(flag["code"] in {"fried", "dessert", "sugary_drink", "fried_starch"} for flag in rule_flags):
        traffic_light = "red" if traffic_light in {"unknown", "yellow"} else "yellow"
    elif any(flag["code"] in {"restaurant_meal", "fast_food", "instant_food"} for flag in rule_flags):
        traffic_light = "yellow" if traffic_light == "unknown" else traffic_light

    return {
        "query": q,
        "meal_type": meal_type,
        "context": context,
        "traffic_light_hint": traffic_light,
        "rule_summary_zh": rule_summary_zh,
        "matched_foods": candidates,
        "assessed_portion": portion,
        "estimated_nutrition": nutrition,
        "daily_targets": {
            "has_bmr_profile": bool(target.get("has_bmr_profile")),
            "calorie_target": target.get("calorie_target"),
            "protein_g": target.get("protein_g"),
            "carbs_g": target.get("carbs_g"),
            "fat_g": target.get("fat_g"),
        },
        "risk_flags": rule_flags,
        "llm_instruction": (
            "Use these local facts to give a concise fat-loss suitability judgement. "
            "Respond with green/yellow/red light, portion, frequency, and concrete swaps. "
            "If matched_foods is empty, say the judgement is based on the dish name and ask for portion/details when needed."
        ),
    }


def _slot_to_dict(slot: pc.MealSlot) -> dict:
    return {
        "date": slot.date,
        "meal_type": slot.meal_type,
        "status": slot.status,
        "source_id": slot.source_id,
        "foods": [
            {
                "name": food.name,
                "grams": food.grams,
                "calories": food.calories,
                "protein_g": food.protein,
                "carbs_g": food.carbs,
                "fat_g": food.fat,
            }
            for food in slot.foods
        ],
        "totals": {
            "calories": round(slot.totals.calories, 1),
            "protein_g": round(slot.totals.protein, 1),
            "carbs_g": round(slot.totals.carbs, 1),
            "fat_g": round(slot.totals.fat, 1),
        },
    }


def preview_day_plan(db: Session, user: models.User, date: str | None = None) -> dict:
    date_key = local_dates.date_key_or_today(date)
    targets = calorie.build_daily_targets(db, user)
    if not targets.get("has_bmr_profile"):
        return {
            "date": date_key,
            "has_bmr_profile": False,
            "message": "Please complete body goal setup before meal planning.",
        }
    ctx = pc.build_context(db, user, date_key)
    slots = menu_planner.fill_empty_slots(db, user, date_key, ctx)
    return {
        "date": date_key,
        "has_bmr_profile": True,
        "empty_meal_types": ctx.empty_meal_types(),
        "remaining_target": {
            "calories": round(ctx.remaining_target.calories, 1),
            "protein_g": round(ctx.remaining_target.protein, 1),
            "carbs_g": round(ctx.remaining_target.carbs, 1),
            "fat_g": round(ctx.remaining_target.fat, 1),
        },
        "slots": [_slot_to_dict(slot) for slot in slots],
    }


def get_week_overview(db: Session, user: models.User) -> dict:
    raw = menu_planner.week_plan(db, user)
    if raw.get("feasibility") in {"no_bmr", "not_closed_loop"}:
        return raw
    days = []
    for day in raw.get("solved_picks", {}).get("days", [])[:7]:
        meals = {}
        for meal_type, meal in (day.get("meals") or {}).items():
            meals[meal_type] = {
                "totals": meal.get("totals"),
                "parts": [
                    {
                        "slug": part.get("slug"),
                        "name_zh": part.get("name_zh"),
                        "name_en": part.get("name_en"),
                        "grams": part.get("grams"),
                    }
                    for part in (meal.get("parts") or [])[:8]
                ],
            }
        days.append({
            "date": day.get("date"),
            "day_type": day.get("day_type"),
            "activity_level": day.get("activity_level"),
            "target": day.get("target"),
            "totals": day.get("totals"),
            "meals": meals,
        })
    return {
        "feasibility": raw.get("feasibility"),
        "start_date": raw.get("start_date"),
        "targets_baseline": raw.get("targets_baseline"),
        "weekly_totals_target": raw.get("nutrition_requirements", {}).get("weekly_totals_target"),
        "weekly_totals": raw.get("solved_picks", {}).get("weekly_totals"),
        "warnings": raw.get("solved_picks", {}).get("warnings", [])[:10],
        "days": days,
    }


def get_fixed_meals(db: Session, user_id: int) -> dict:
    rows = (
        db.query(models.UserFixedMeal)
        .filter(models.UserFixedMeal.user_id == user_id)
        .order_by(
            models.UserFixedMeal.weekday.asc().nullsfirst(),
            models.UserFixedMeal.meal_type.asc(),
            models.UserFixedMeal.id.asc(),
        )
        .all()
    )
    return {"items": [_serialize_fixed_meal(row) for row in rows]}


def propose_action(
    db: Session,
    user_id: int,
    action_type: str,
    payload: dict,
    summary: str,
) -> dict:
    if action_type not in ACTION_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported action_type: {action_type}")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="payload must be an object")
    if not str(summary or "").strip():
        raise HTTPException(status_code=422, detail="summary is required")

    (
        db.query(models.AssistantPendingAction)
        .filter(
            models.AssistantPendingAction.user_id == user_id,
            models.AssistantPendingAction.action_type == action_type,
            models.AssistantPendingAction.status == STATUS_PENDING,
        )
        .update({"status": STATUS_SUPERSEDED}, synchronize_session="fetch")
    )
    row = models.AssistantPendingAction(
        user_id=user_id,
        action_type=action_type,
        payload_json=_json_dumps(payload),
        summary=str(summary).strip(),
        status=STATUS_PENDING,
    )
    db.add(row)
    db.flush()
    return _serialize_action(row)


def _ingredients_text(ingredients: list[dict], lang: str = "zh") -> str:
    return "\n".join(
        f"{FL.display_name(item['slug'], lang)} {item['grams']}g"
        for item in ingredients
    )


def _create_private_recipe(
    db: Session,
    user_id: int,
    *,
    name: str,
    meal_types: str,
    ingredients: list[dict],
    steps: str | None = None,
) -> models.Recipe:
    totals = calculate_foods(ingredients)["totals"]
    serving_g = round(sum(float(item["grams"]) for item in ingredients), 1)
    recipe = models.Recipe(
        name=str(name or "Assistant meal").strip()[:120],
        ingredients=_ingredients_text(ingredients),
        steps=steps,
        category="assistant",
        is_builtin=False,
        submitted_by=user_id,
        is_approved=False,
        meal_types=meal_types,
        calories=int(round(float(totals["kcal"]))),
        protein_g=float(totals["protein_g"]),
        carbs_g=float(totals["carbs_g"]),
        fat_g=float(totals["fat_g"]),
        serving_g=serving_g,
        ingredient_slugs=_json_dumps(sorted({item["slug"] for item in ingredients})),
        ingredients_json=json.dumps(ingredients, ensure_ascii=False),
    )
    db.add(recipe)
    db.flush()
    return recipe


def _scaled_recipe_macros(recipe: models.Recipe, portion_g: float | None = None) -> dict:
    ingredients = _safe_loads(recipe.ingredients_json, [])
    if ingredients:
        cleaned = _clean_ingredients(ingredients)
        totals = calculate_foods(cleaned)["totals"]
        serving = round(sum(float(item["grams"]) for item in cleaned), 1)
        multiplier = (portion_g / serving) if (portion_g and serving) else 1.0
        return {
            "portion_g": portion_g or serving,
            "calories": int(round(float(totals["kcal"]) * multiplier)),
            "protein_g": round(float(totals["protein_g"]) * multiplier, 1),
            "carbs_g": round(float(totals["carbs_g"]) * multiplier, 1),
            "fat_g": round(float(totals["fat_g"]) * multiplier, 1),
        }

    serving = recipe.serving_g
    multiplier = (portion_g / serving) if (portion_g and serving) else 1.0
    return {
        "portion_g": portion_g or serving,
        "calories": int(round(float(recipe.calories or 0) * multiplier)),
        "protein_g": round(float(recipe.protein_g or 0.0) * multiplier, 1),
        "carbs_g": round(float(recipe.carbs_g or 0.0) * multiplier, 1),
        "fat_g": round(float(recipe.fat_g or 0.0) * multiplier, 1),
    }


def _weekday_filter(query, weekday: int | None):
    if weekday is None:
        return query.filter(models.UserFixedMeal.weekday.is_(None))
    return query.filter(models.UserFixedMeal.weekday == weekday)


def _execute_upsert_fixed_breakfast(db: Session, user_id: int, payload: dict) -> dict:
    ingredients = _clean_ingredients(payload.get("ingredients"))
    weekday_raw = payload.get("weekday")
    try:
        weekday = None if weekday_raw in (None, "") else int(weekday_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="weekday must be 0..6 or null")
    if weekday is not None and not (0 <= weekday <= 6):
        raise HTTPException(status_code=422, detail="weekday must be 0..6 or null")
    meal_type = str(payload.get("meal_type") or "breakfast").strip()
    if meal_type != "breakfast":
        raise HTTPException(status_code=422, detail="upsert_fixed_breakfast only supports breakfast")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    lang = getattr(user, "language", "zh") if user else "zh"
    raw_name = str(payload.get("name") or "").strip()
    if not raw_name or (lang != "en" and raw_name.lower() in {"fixed breakfast", "breakfast"}):
        raw_name = "固定早餐"

    recipe = _create_private_recipe(
        db,
        user_id,
        name=raw_name,
        meal_types="breakfast",
        ingredients=ingredients,
        steps=payload.get("steps"),
    )
    macros = _scaled_recipe_macros(recipe, _optional_positive_float(payload.get("portion_g"), "portion_g") or recipe.serving_g)
    query = db.query(models.UserFixedMeal).filter(
        models.UserFixedMeal.user_id == user_id,
        models.UserFixedMeal.meal_type == "breakfast",
    )
    existing = _weekday_filter(query, weekday).first()
    if existing:
        existing.recipe_id = recipe.id
        existing.custom_name = None
        existing.weekday = weekday
        existing.portion_g = macros["portion_g"]
        existing.calories = macros["calories"]
        existing.protein_g = macros["protein_g"]
        existing.carbs_g = macros["carbs_g"]
        existing.fat_g = macros["fat_g"]
        row = existing
    else:
        row = models.UserFixedMeal(
            user_id=user_id,
            weekday=weekday,
            meal_type="breakfast",
            recipe_id=recipe.id,
            portion_g=macros["portion_g"],
            calories=macros["calories"],
            protein_g=macros["protein_g"],
            carbs_g=macros["carbs_g"],
            fat_g=macros["fat_g"],
        )
        db.add(row)
    db.flush()
    return {
        "recipe_id": recipe.id,
        "fixed_meal": _serialize_fixed_meal(row),
    }


def _execute_apply_day_plan_slot(db: Session, user_id: int, payload: dict) -> dict:
    date = local_dates.validate_date_key(str(payload.get("date") or ""))
    meal_type = str(payload.get("meal_type") or "").strip()
    if meal_type not in VALID_MEAL_TYPES:
        raise HTTPException(status_code=422, detail="Invalid meal_type")

    recipe: models.Recipe | None = None
    if payload.get("recipe_id"):
        recipe = recipe_access.get_visible_recipe(db, int(payload["recipe_id"]), user_id)
        if recipe is None:
            raise HTTPException(status_code=404, detail="Recipe not found")
    else:
        ingredients = _clean_ingredients(payload.get("ingredients"))
        recipe = _create_private_recipe(
            db,
            user_id,
            name=str(payload.get("name") or "Assistant planned meal"),
            meal_types=meal_type,
            ingredients=ingredients,
            steps=payload.get("steps"),
        )

    macros = _scaled_recipe_macros(recipe, _optional_positive_float(payload.get("portion_g"), "portion_g"))
    status = str(payload.get("status") or pc.SLOT_STATUS_GENERATED)
    if status not in {pc.SLOT_STATUS_RECIPE, pc.SLOT_STATUS_GENERATED}:
        status = pc.SLOT_STATUS_GENERATED

    existing = (
        db.query(models.MealPlanEntry)
        .filter(
            models.MealPlanEntry.user_id == user_id,
            models.MealPlanEntry.date == date,
            models.MealPlanEntry.meal_type == meal_type,
        )
        .first()
    )
    if existing:
        existing.recipe_id = recipe.id
        existing.custom_name = None
        existing.portion_g = macros["portion_g"]
        existing.calories = macros["calories"]
        existing.protein_g = macros["protein_g"]
        existing.carbs_g = macros["carbs_g"]
        existing.fat_g = macros["fat_g"]
        existing.status = status
        entry = existing
    else:
        entry = models.MealPlanEntry(
            user_id=user_id,
            date=date,
            meal_type=meal_type,
            recipe_id=recipe.id,
            portion_g=macros["portion_g"],
            calories=macros["calories"],
            protein_g=macros["protein_g"],
            carbs_g=macros["carbs_g"],
            fat_g=macros["fat_g"],
            status=status,
        )
        db.add(entry)
    db.flush()
    return {
        "entry": {
            "id": entry.id,
            "date": entry.date,
            "meal_type": entry.meal_type,
            "recipe_id": entry.recipe_id,
            "portion_g": entry.portion_g,
            "calories": entry.calories,
            "protein_g": entry.protein_g,
            "carbs_g": entry.carbs_g,
            "fat_g": entry.fat_g,
            "status": entry.status,
        }
    }


def execute_action(db: Session, user: models.User, row: models.AssistantPendingAction) -> dict:
    payload = _safe_loads(row.payload_json, {})
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Action payload is invalid")
    if row.action_type == ACTION_SAVE_MEMORY:
        return upsert_nutrition_memory(db, user.id, payload)
    if row.action_type == ACTION_UPSERT_FIXED_BREAKFAST:
        return _execute_upsert_fixed_breakfast(db, user.id, payload)
    if row.action_type == ACTION_APPLY_DAY_PLAN_SLOT:
        return _execute_apply_day_plan_slot(db, user.id, payload)
    raise HTTPException(status_code=422, detail=f"Unsupported action_type: {row.action_type}")


def call_tool(db: Session, user: models.User, name: str, args: dict) -> dict:
    args = args or {}
    if name == "get_user_targets":
        return get_user_targets(db, user)
    if name == "search_food_library":
        return search_food_library(
            str(args.get("query") or ""),
            execution_bucket=args.get("execution_bucket"),
            limit=int(args.get("limit") or 8),
        )
    if name == "calculate_foods":
        return calculate_foods(args.get("ingredients") or args.get("foods") or [])
    if name == "audit_food_set":
        return audit_food_set(db, user)
    if name == "suggest_replacements":
        return suggest_replacements(db, user, str(args.get("slug") or ""))
    if name == "evaluate_fat_loss_food":
        grams = args.get("grams")
        try:
            grams_value = float(grams) if grams not in (None, "") else None
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="grams must be a number")
        return evaluate_fat_loss_food(
            db,
            user,
            str(args.get("query") or ""),
            grams=grams_value,
            meal_type=args.get("meal_type"),
            context=args.get("context"),
        )
    if name == "preview_day_plan":
        return preview_day_plan(db, user, args.get("date"))
    if name == "get_week_overview":
        return get_week_overview(db, user)
    if name == "get_nutrition_memory":
        return get_nutrition_memory(db, user.id)
    if name == "get_fixed_meals":
        return get_fixed_meals(db, user.id)
    if name == "propose_action":
        action = propose_action(
            db,
            user.id,
            str(args.get("action_type") or ""),
            args.get("payload") or {},
            str(args.get("summary") or ""),
        )
        return {"proposed_action": action}
    raise HTTPException(status_code=422, detail=f"Unknown assistant tool: {name}")


def confirm_action(db: Session, user: models.User, action_id: int) -> dict:
    row = (
        db.query(models.AssistantPendingAction)
        .filter(models.AssistantPendingAction.id == action_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Action not found")
    if row.user_id != user.id:
        raise HTTPException(status_code=403, detail="Action belongs to another user")
    if row.status != STATUS_PENDING:
        raise HTTPException(status_code=409, detail=f"Action is already {row.status}")

    row.status = STATUS_CONFIRMED
    db.flush()
    result = execute_action(db, user, row)
    row.status = STATUS_EXECUTED
    row.executed_at = datetime.now(timezone.utc)
    db.flush()
    return {"action": _serialize_action(row), "result": result}
