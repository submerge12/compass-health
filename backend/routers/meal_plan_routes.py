import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from services import (
    autofill,
    calorie,
    food_library as FL,
    llm_quota,
    local_dates,
    meal_scheduler,
    menu_planner,
    nutrition_audit,
    planning_context as pc,
    recipe_access,
    recipe_suggester,
    saved_recipes,
)

log = logging.getLogger("compass.app")

router = APIRouter(prefix="/api/meal-plan", tags=["meal-plan"])


MEAL_TYPES = ("breakfast", "lunch", "dinner")

_CLOSED_LOOP_BUCKET_LABELS = {
    "staple": {"zh": "主食 / 碳水来源", "en": "Staples / carbohydrates"},
    "lean_protein": {"zh": "低脂蛋白", "en": "Lean protein"},
    "red_meat_shellfish": {"zh": "红肉 / 贝类", "en": "Red meat / shellfish"},
    "calcium": {"zh": "钙源", "en": "Calcium source"},
    "iodine": {"zh": "碘源", "en": "Iodine source"},
    "vitamin_d": {"zh": "维生素 D 来源", "en": "Vitamin D source"},
    "dark_green_cruciferous": {"zh": "深绿叶菜 / 十字花科", "en": "Dark-green / cruciferous"},
    "vitamin_e_healthy_fat": {"zh": "维生素 E / 健康脂肪", "en": "Vitamin E / healthy fat"},
}


def _closed_loop_error_detail(pool: dict) -> dict:
    status = pool.get("feasibility", "error")
    detail = {
        "error": status,
        "message_zh": pool.get("message_zh"),
        "message_en": pool.get("message_en"),
    }
    if status != "not_closed_loop":
        return detail

    missing_buckets = []
    recommended: dict[str, dict] = {}
    for bucket in pool.get("blocking_buckets", []):
        label = _CLOSED_LOOP_BUCKET_LABELS.get(bucket, {"zh": bucket, "en": bucket})
        foods = []
        for slug in FL.slugs_by_validation_bucket(bucket)[:6]:
            food = {
                "slug": slug,
                "name_zh": FL.display_name(slug, "zh"),
                "name_en": FL.display_name(slug, "en"),
                "roles": [bucket],
                "role_labels_zh": [label["zh"]],
                "role_labels_en": [label["en"]],
            }
            foods.append(food)
            recommended.setdefault(slug, food)
        missing_buckets.append({
            "bucket": bucket,
            "label_zh": label["zh"],
            "label_en": label["en"],
            "recommended_foods": foods,
        })

    detail.update({
        "missing_blocking_buckets": missing_buckets,
        "recommended_foods": list(recommended.values()),
    })
    return detail


class MealPlanEntryCreate(BaseModel):
    date: str = Field(..., min_length=10, max_length=10)           # "YYYY-MM-DD"
    meal_type: str = Field(..., min_length=1, max_length=20)      # breakfast / lunch / dinner
    recipe_id: Optional[int] = Field(default=None, ge=1)
    custom_name: Optional[str] = Field(default=None, max_length=120)


@router.get("/week")
def get_week_plan(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Return the sliding 7-day window starting today."""
    days = local_dates.date_range_starting_today(7)

    entries = (
        db.query(models.MealPlanEntry)
        .filter(
            models.MealPlanEntry.user_id == current_user.id,
            models.MealPlanEntry.date.in_(days),
        )
        .all()
    )

    # Build an indexed result: date → meal_type → entry
    result: dict[str, dict] = {
        d: {"breakfast": None, "lunch": None, "dinner": None} for d in days
    }
    for e in entries:
        recipe_data = None
        if e.recipe:
            recipe_data = {
                "id": e.recipe.id,
                "name": e.recipe.name,
                "has_steps": bool(e.recipe.steps),
                "has_video": bool(e.recipe.video_url),
            }
        result[e.date][e.meal_type] = {
            "entry_id": e.id,
            "recipe_id": e.recipe_id,
            "custom_name": e.custom_name,
            "recipe": recipe_data,
        }

    return {
        "today": days[0],
        "days": [{"date": d, "meals": result[d]} for d in days],
    }


_LIBRARY_BREAKFAST_LIMIT = 8
_LIBRARY_MAIN_LIMIT = 24


def _stamp_pool_dish(dish: dict, source: str = "generated") -> dict:
    stamped = dict(dish or {})
    stamped.setdefault("source", source)
    stamped.setdefault("source_label", menu_planner.pool_source_label(stamped["source"]))
    if "dish_id" not in stamped and stamped.get("sketch_id") is not None:
        stamped["dish_id"] = str(stamped["sketch_id"])
    return stamped


def _stamp_generated_pool(pool: dict) -> dict:
    pool = dict(pool or {})
    pool["breakfast_pool"] = [
        _stamp_pool_dish(item, "generated")
        for item in pool.get("breakfast_pool", [])
    ]
    pool["main_pool"] = [
        _stamp_pool_dish(item, "generated")
        for item in pool.get("main_pool", [])
    ]
    return pool


def _pool_signature_text(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _pool_signature_number(value: object, digits: int = 1) -> float:
    try:
        return round(float(value or 0), digits)
    except (TypeError, ValueError):
        return 0.0


def _pool_ingredient_signature(items: object) -> tuple[tuple[str, float], ...]:
    if not isinstance(items, list):
        return ()
    ingredients: list[tuple[str, float]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        slug = _pool_signature_text(item.get("slug") or item.get("name"))
        if not slug:
            continue
        grams = _pool_signature_number(item.get("grams"))
        ingredients.append((slug, grams))
    return tuple(sorted(ingredients))


def _pool_dish_signature(dish: dict) -> tuple[object, ...]:
    ingredients = _pool_ingredient_signature(dish.get("ingredients"))
    if not ingredients:
        ingredients = _pool_ingredient_signature(dish.get("parts"))
    if ingredients:
        return ("ingredients", ingredients)

    raw_slugs = dish.get("ingredient_slugs")
    slugs = tuple(sorted(
        _pool_signature_text(slug)
        for slug in (raw_slugs if isinstance(raw_slugs, list) else [])
        if _pool_signature_text(slug)
    ))
    totals = dish.get("totals") or {}
    macro_signature = (
        _pool_signature_number(totals.get("kcal"), 0),
        _pool_signature_number(totals.get("protein_g")),
        _pool_signature_number(totals.get("carbs_g")),
        _pool_signature_number(totals.get("fat_g")),
    )
    if slugs:
        return ("slugs", slugs, macro_signature)
    name = _pool_signature_text(dish.get("name"))
    if name or any(macro_signature):
        return ("name", name, macro_signature)
    return ("id", _pool_signature_text(dish.get("dish_id") or dish.get("sketch_id")))


def _pool_source_rank(dish: dict) -> int:
    return {
        "recipe_library": 0,
        "saved": 1,
        "generated": 2,
        "supplement": 3,
    }.get(str(dish.get("source") or ""), 4)


def _dedupe_pool_dishes(dishes: list[dict]) -> list[dict]:
    positions: dict[tuple[object, ...], int] = {}
    unique: list[dict] = []
    for dish in dishes:
        if not isinstance(dish, dict):
            continue
        signature = _pool_dish_signature(dish)
        if signature in positions:
            existing_index = positions[signature]
            if _pool_source_rank(dish) < _pool_source_rank(unique[existing_index]):
                unique[existing_index] = dish
            continue
        positions[signature] = len(unique)
        unique.append(dish)
    return unique


def _recipe_ingredients_for_pool(recipe: models.Recipe, library_slugs: set[str]) -> Optional[list[dict]]:
    if not recipe.ingredients_json:
        return None
    try:
        raw_items = json.loads(recipe.ingredients_json)
    except Exception:
        return None
    if not isinstance(raw_items, list):
        return None

    ingredients: list[dict] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        slug = str(raw.get("slug") or "").strip()
        if not slug:
            continue
        required = bool(raw.get("required", True))
        if slug not in library_slugs:
            if required:
                return None
            continue
        try:
            grams = round(float(raw.get("grams") or 0), 1)
        except (TypeError, ValueError):
            grams = 0.0
        if grams <= 0:
            if required:
                return None
            continue
        ingredients.append({
            "slug": slug,
            "grams": grams,
            "name_zh": FL.display_name(slug, "zh"),
            "name_en": FL.display_name(slug, "en"),
        })
        if len(ingredients) > 50:
            return None
    return ingredients or None


def _recipe_pool_groups(recipe: models.Recipe) -> set[str]:
    meal_types = {
        token.strip().lower()
        for token in (recipe.meal_types or "").split(",")
        if token.strip()
    }
    if not meal_types:
        return {"breakfast", "main"}
    groups: set[str] = set()
    if "breakfast" in meal_types:
        groups.add("breakfast")
    if meal_types & {"lunch", "dinner", "main"}:
        groups.add("main")
    return groups


def _recipe_to_pool_candidate(recipe: models.Recipe, group: str, ingredients: list[dict]) -> dict:
    slugs = sorted({item["slug"] for item in ingredients})
    return {
        "dish_id": f"recipe-{group}-{recipe.id}",
        "recipe_id": recipe.id,
        "meal_type": group,
        "source": "recipe_library",
        "source_label": menu_planner.pool_source_label("recipe_library"),
        "name": recipe.name,
        "ingredients": ingredients,
        "totals": {
            "kcal": float(recipe.calories or 0),
            "protein_g": float(recipe.protein_g or 0),
            "carbs_g": float(recipe.carbs_g or 0),
            "fat_g": float(recipe.fat_g or 0),
        },
        "ingredient_slugs": slugs,
        "day_type_affinities": menu_planner.day_type_affinities_for_slugs(slugs),
        "method_steps": recipe.steps or "",
        "seasonings": [],
    }


def _visible_recipe_pool_candidates(db: Session, user: models.User) -> dict[str, list[dict]]:
    library_slugs = set(nutrition_audit.load_user_library(db, user.id))
    if not library_slugs:
        return {"breakfast": [], "main": []}

    rows = (
        db.query(models.Recipe)
        .filter(
            or_(
                models.Recipe.is_approved == True,  # noqa: E712
                models.Recipe.submitted_by == user.id,
            )
        )
        .filter(models.Recipe.ingredients_json.isnot(None))
        .order_by(models.Recipe.is_builtin.desc(), models.Recipe.name.asc())
        .all()
    )
    result: dict[str, list[dict]] = {"breakfast": [], "main": []}
    seen: dict[str, set[tuple[object, ...]]] = {"breakfast": set(), "main": set()}
    for recipe in rows:
        if None in (recipe.calories, recipe.protein_g, recipe.carbs_g, recipe.fat_g):
            continue
        ingredients = _recipe_ingredients_for_pool(recipe, library_slugs)
        if not ingredients:
            continue
        for group in sorted(_recipe_pool_groups(recipe)):
            limit = _LIBRARY_BREAKFAST_LIMIT if group == "breakfast" else _LIBRARY_MAIN_LIMIT
            candidate = _recipe_to_pool_candidate(recipe, group, ingredients)
            signature = _pool_dish_signature(candidate)
            if signature in seen[group]:
                continue
            if len(result[group]) >= limit:
                continue
            seen[group].add(signature)
            result[group].append(candidate)
    return result


def _merge_library_candidates(pool: dict, db: Session, user: models.User) -> dict:
    merged = _stamp_generated_pool(pool)
    library = _visible_recipe_pool_candidates(db, user)
    requires_breakfast_pool = bool(merged.get("requires_breakfast_pool", True))
    requires_main_pool = bool(merged.get("requires_main_pool", True))
    merged["breakfast_pool"] = _dedupe_pool_dishes(
        merged.get("breakfast_pool", []) + library["breakfast"]
    ) if requires_breakfast_pool else []
    merged["main_pool"] = _dedupe_pool_dishes(
        merged.get("main_pool", []) + library["main"]
    ) if requires_main_pool else []
    return merged


def _named_or_raw_supplement(pool_data: dict, result: dict) -> list[dict]:
    named_by_id = {
        str(item.get("sketch_id")): item
        for item in result.get("named_dishes", [])
        if isinstance(item, dict) and item.get("sketch_id") is not None
    }
    output: list[dict] = []
    for raw in pool_data.get("breakfast_pool", []) + pool_data.get("main_pool", []):
        sid = str(raw.get("sketch_id"))
        output.append(_stamp_pool_dish(named_by_id.get(sid) or raw, "supplement"))
    return output


@router.get("/pool")
def get_dish_pool(
    variant: int = 0,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Generate a pool of ~30 candidate dish sketches for the user to choose from.

    Returns 6 breakfast candidates and 24 lunch/dinner candidates (combined,
    since the two meal types are interchangeable at the slot level). Each
    sketch carries its ingredient list, macros, and day-type affinity tags.

    Also returns a week_skeleton showing which days are locked (red-meat day,
    deep-sea fish day) vs free, so the frontend can surface scheduling hints.

    No LLM call is made here — dish names are ingredient-list sketches. Call
    POST /api/meal-plan/pool/name to name them (uses the LLM quota).
    """
    pool = menu_planner.generate_dish_pool(db, current_user, variant=variant)
    if "message_zh" in pool:
        raise HTTPException(
            status_code=400,
            detail=_closed_loop_error_detail(pool),
        )
    return _merge_library_candidates(pool, db, current_user)


@router.post("/pool/name")
def name_dish_pool(
    variant: int = 0,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Assign dish names and cooking methods to the ingredient-sketch pool via LLM.

    Regenerates the pool internally (deterministic given the user's food library),
    then calls the LLM to name each sketch. Consumes one slot from the pool_name
    quota (3 per rolling 7 days). If the LLM returns no usable dishes the slot is
    automatically refunded.

    Response:
      breakfast_dishes  — list of named breakfast dishes
      main_dishes       — list of named lunch/dinner dishes (user assigns to slot)
      week_skeleton     — 7-day day-type calendar with is_locked flags
      warnings          — soft notes (unnamed sketches, batch failures)
      llm_quota         — current usage after this call
    """
    pool_data = menu_planner.generate_dish_pool(db, current_user, variant=variant)
    if "message_zh" in pool_data:
        raise HTTPException(
            status_code=400,
            detail=_closed_loop_error_detail(pool_data),
        )

    requires_breakfast_pool = bool(pool_data.get("requires_breakfast_pool", True))
    requires_main_pool = bool(pool_data.get("requires_main_pool", True))
    breakfast_sketches = pool_data.get("breakfast_pool", []) if requires_breakfast_pool else []
    main_sketches = pool_data.get("main_pool", []) if requires_main_pool else []
    all_sketches = breakfast_sketches + main_sketches
    language = current_user.language or "zh"
    library = _visible_recipe_pool_candidates(db, current_user)
    library_breakfast = library["breakfast"] if requires_breakfast_pool else []
    library_main = library["main"] if requires_main_pool else []

    if not all_sketches:
        quota_usage = llm_quota.usage(db, current_user.id, llm_quota.POOL_NAME)
        return {
            "breakfast_dishes": _dedupe_pool_dishes(library_breakfast),
            "main_dishes": _dedupe_pool_dishes(library_main),
            "variant": variant,
            "week_skeleton": pool_data.get("week_skeleton", []),
            "required_slot_counts": pool_data.get("required_slot_counts", {}),
            "requires_breakfast_pool": requires_breakfast_pool,
            "requires_main_pool": requires_main_pool,
            "warnings": [],
            "llm_quota": {**quota_usage, "kind": llm_quota.POOL_NAME},
        }

    pool_quota_call_id: Optional[int] = None
    try:
        quota_charge = llm_quota.check_and_consume(db, current_user.id, llm_quota.POOL_NAME)
    except llm_quota.LLMQuotaExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "quota_exhausted",
                "kind": llm_quota.POOL_NAME,
                "message_zh": "本周菜肴命名次数已用完。",
                "message_en": "Pool naming quota exhausted for this week.",
                "next_refresh_at": exc.next_refresh_at.isoformat()
                if getattr(exc, "next_refresh_at", None) else None,
            },
        )
    pool_quota_call_id = quota_charge.get("call_log_id")
    db.commit()

    try:
        result = recipe_suggester.suggest_pool_names(all_sketches, language)
    except Exception as exc:
        if llm_quota.refund_call(db, pool_quota_call_id, user_id=current_user.id, kind=llm_quota.POOL_NAME):
            db.commit()
        raise HTTPException(
            status_code=502,
            detail={
                "error": "llm_failed",
                "message_zh": "菜谱命名失败，请稍后重试。",
                "message_en": f"Pool naming failed: {exc.__class__.__name__}",
            },
        )

    named_dishes = [_stamp_pool_dish(d, "generated") for d in result.get("named_dishes", [])]
    if not named_dishes:
        if llm_quota.refund_call(db, pool_quota_call_id, user_id=current_user.id, kind=llm_quota.POOL_NAME):
            db.commit()

    quota_usage = llm_quota.usage(db, current_user.id, llm_quota.POOL_NAME)
    breakfast_dishes = _dedupe_pool_dishes(
        [d for d in named_dishes if d["meal_type"] == "breakfast"] + library_breakfast
    )
    main_dishes = _dedupe_pool_dishes(
        [d for d in named_dishes if d["meal_type"] == "main"] + library_main
    )
    return {
        "breakfast_dishes": breakfast_dishes,
        "main_dishes":      main_dishes,
        "variant":          variant,
        "week_skeleton":    pool_data.get("week_skeleton", []),
        "required_slot_counts": pool_data.get("required_slot_counts", {}),
        "requires_breakfast_pool": requires_breakfast_pool,
        "requires_main_pool": requires_main_pool,
        "warnings":         result.get("warnings", []),
        "llm_quota":        {**quota_usage, "kind": llm_quota.POOL_NAME},
    }


class PoolSupplementIssue(BaseModel):
    error: Optional[str] = Field(default=None, max_length=80)
    missing_roles: list[str] = Field(default_factory=list, max_length=20)
    required_buckets: list[str] = Field(default_factory=list, max_length=20)


class PoolCurrentPool(BaseModel):
    required_slot_counts: dict[str, int] = Field(default_factory=dict)
    requires_breakfast_pool: Optional[bool] = None
    requires_main_pool: Optional[bool] = None


class PoolSupplementRequest(BaseModel):
    selected_food_slugs: list[str] = Field(default_factory=list, max_length=30)
    issue: Optional[PoolSupplementIssue] = None
    missing_roles: list[str] = Field(default_factory=list, max_length=20)
    required_buckets: list[str] = Field(default_factory=list, max_length=20)
    current_pool: Optional[PoolCurrentPool] = None
    variant: int = Field(default=0, ge=0, le=1000)


@router.post("/pool/supplement")
def supplement_dish_pool(
    body: PoolSupplementRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    issue = body.issue or PoolSupplementIssue()
    missing_roles = body.missing_roles or issue.missing_roles or []
    required_buckets = body.required_buckets or issue.required_buckets or []
    current_counts = body.current_pool.required_slot_counts if body.current_pool else {}
    breakfast_required_count = int(current_counts.get("breakfast", 1) or 0)
    main_required_count = int(current_counts.get("lunch", 1) or 0) + int(current_counts.get("dinner", 1) or 0)
    requires_breakfast_pool = (
        bool(body.current_pool.requires_breakfast_pool)
        if body.current_pool and body.current_pool.requires_breakfast_pool is not None
        else breakfast_required_count > 0
    )
    requires_main_pool = (
        bool(body.current_pool.requires_main_pool)
        if body.current_pool and body.current_pool.requires_main_pool is not None
        else main_required_count > 0
    )
    pool_data = menu_planner.generate_supplement_pool(
        db,
        current_user,
        selected_food_slugs=body.selected_food_slugs,
        missing_roles=missing_roles,
        required_buckets=required_buckets,
        variant=body.variant,
        requires_breakfast_pool=requires_breakfast_pool,
        requires_main_pool=requires_main_pool,
    )
    if "message_zh" in pool_data and pool_data.get("feasibility") != "ok":
        raise HTTPException(status_code=400, detail=_closed_loop_error_detail(pool_data))

    language = current_user.language or "zh"
    all_sketches = pool_data.get("breakfast_pool", []) + pool_data.get("main_pool", [])
    warnings = list(pool_data.get("warnings", []))
    result: dict = {"named_dishes": [], "warnings": []}
    if all_sketches:
        try:
            result = recipe_suggester.suggest_pool_names(all_sketches, language)
        except Exception as exc:
            warnings.append(f"supplement naming failed ({exc.__class__.__name__}); returned sketches instead")
        else:
            warnings.extend(result.get("warnings", []))

    supplement_dishes = _named_or_raw_supplement(pool_data, result)
    return {
        "breakfast_dishes": [d for d in supplement_dishes if d.get("meal_type") == "breakfast"] if requires_breakfast_pool else [],
        "main_dishes": [d for d in supplement_dishes if d.get("meal_type") == "main"] if requires_main_pool else [],
        "variant": body.variant,
        "requires_breakfast_pool": requires_breakfast_pool,
        "requires_main_pool": requires_main_pool,
        "warnings": warnings,
        "quota_waived": {"kind": llm_quota.POOL_NAME, "reason": "gap_supplement"},
    }


class PoolIngredient(BaseModel):
    slug: str = Field(..., min_length=1, max_length=80)
    grams: float = Field(..., gt=0, le=3000)


class PoolSeasoning(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    grams: Optional[float] = Field(default=None, ge=0, le=100)


class PoolDish(BaseModel):
    dish_id: Optional[str] = Field(default=None, max_length=80)
    recipe_id: Optional[int] = Field(default=None, ge=1)
    meal_type: str = Field(..., min_length=1, max_length=20)
    source: str = Field(default="generated", max_length=40)
    source_label: Optional[str] = Field(default=None, max_length=80)
    name: str = Field(..., min_length=1, max_length=120)
    ingredients: list[PoolIngredient] = Field(..., min_length=1, max_length=50)
    totals: dict[str, float]
    ingredient_slugs: list[str] = Field(default_factory=list, max_length=50)
    day_type_affinities: list[str] = Field(default_factory=list, max_length=20)
    method_steps: Optional[str] = Field(default=None, max_length=4000)
    seasonings: list[PoolSeasoning] = Field(default_factory=list, max_length=30)


class MealPlanArrange(BaseModel):
    breakfast_dishes: list[PoolDish] = Field(..., max_length=20)
    main_dishes: list[PoolDish] = Field(..., max_length=80)


def _ingredient_lines(ingredients: list[PoolIngredient], language: str) -> str:
    lines: list[str] = []
    for item in ingredients:
        slug = str(item.slug or "").strip()
        grams = round(float(item.grams or 0), 1)
        if not slug or grams <= 0:
            continue
        label = FL.display_name(slug, "en" if language == "en" else "zh") or slug
        lines.append(f"{label} {grams}g")
    return "\n".join(lines)


def _pool_dish_to_pick(dish: dict, meal_type: str, language: str) -> "MealPick":
    ingredients = [
        {"slug": item["slug"], "grams": round(float(item["grams"] or 0), 1), "required": True}
        for item in dish.get("ingredients", [])
    ]
    ingredient_slugs = dish.get("ingredient_slugs") or [item["slug"] for item in ingredients]
    totals = dish.get("totals", {})
    serving_g = round(sum(float(item["grams"] or 0) for item in ingredients), 1) or None
    return MealPick(
        recipe_id=int(dish["recipe_id"]) if dish.get("recipe_id") else None,
        name=dish.get("name"),
        ingredients=_ingredient_lines(
            [PoolIngredient(slug=item["slug"], grams=item["grams"]) for item in ingredients],
            language,
        ),
        ingredients_json=[PoolIngredient(slug=item["slug"], grams=item["grams"]) for item in ingredients],
        ingredient_slugs=ingredient_slugs,
        meal_types="breakfast" if meal_type == "breakfast" else "lunch,dinner",
        portion_g=serving_g,
        calories=int(round(float(totals.get("kcal", 0) or 0))),
        protein_g=float(totals.get("protein_g", 0) or 0),
        carbs_g=float(totals.get("carbs_g", 0) or 0),
        fat_g=float(totals.get("fat_g", 0) or 0),
        method_steps=str(dish.get("method_steps") or "").strip() or None,
        seasonings=[
            PoolSeasoning(name=str(item.get("name", "")).strip(), grams=float(item.get("grams") or 0))
            for item in dish.get("seasonings", [])
            if str(item.get("name", "")).strip()
        ],
        day_type_affinities=[str(v) for v in dish.get("day_type_affinities", []) if isinstance(v, str)],
    )


@router.post("/arrange")
def arrange_meal_plan(
    body: MealPlanArrange,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    week_dates = local_dates.date_range_starting_today(7)
    replaceable = (
        db.query(models.MealPlanEntry)
        .filter(
            models.MealPlanEntry.user_id == current_user.id,
            models.MealPlanEntry.date.in_(week_dates),
            models.MealPlanEntry.status != pc.SLOT_STATUS_RECORDED,
        )
        .all()
    )

    try:
        for row in replaceable:
            db.delete(row)
        db.flush()

        plan = menu_planner.arrange_selected_pool(
            db,
            current_user,
            [item.model_dump() for item in body.breakfast_dishes],
            [item.model_dump() for item in body.main_dishes],
        )
        if plan.get("error"):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": plan.get("error"),
                    "message_zh": plan.get("message_zh"),
                    "message_en": plan.get("message_en"),
                    "warnings": plan.get("warnings", []),
                    "micronutrients": plan.get("micronutrients"),
                    "missing_micronutrients": plan.get("missing_micronutrients", []),
                    "required_buckets": plan.get("required_buckets", []),
                    "recommended_foods": plan.get("recommended_foods", []),
                },
            )

        recipe_cache: dict[tuple, models.Recipe] = {}
        arranged_entry_count = 0
        language = current_user.language or "zh"
        for day in plan.get("days", []):
            for meal_type, meal in day.get("meals", {}).items():
                pick_payload = meal.get("pick")
                if meal.get("source") != "selected" or not isinstance(pick_payload, dict):
                    meal.pop("pick", None)
                    continue
                pick = _pool_dish_to_pick(pick_payload, meal_type, language)
                candidate_source = str(pick_payload.get("source") or pick_payload.get("candidate_source") or "")
                entry_status = (
                    pc.SLOT_STATUS_RECIPE
                    if pick.recipe_id is not None or candidate_source == "recipe_library"
                    else pc.SLOT_STATUS_GENERATED
                )
                signature = ("recipe_id", pick.recipe_id) if pick.recipe_id is not None else (
                    pick.name,
                    meal_type,
                    tuple((item.slug, round(float(item.grams or 0), 1)) for item in (pick.ingredients_json or [])),
                )
                recipe = recipe_cache.get(signature)
                if recipe is None:
                    recipe = _resolve_recipe(db, current_user.id, meal_type, pick)
                    recipe_cache[signature] = recipe
                try:
                    saved_recipes.save_on_select(db, current_user, recipe.id)
                except saved_recipes.SavedRecipeCapReached:
                    cap = saved_recipes.cap_for_user(current_user)
                    plan.setdefault("warnings", []).append(
                        f"Saved-recipe library is full ({cap}); generated recipe '{recipe.name}' was arranged but not saved."
                    )
                entry = _upsert_entry(
                    db,
                    current_user.id,
                    day["date"],
                    meal_type,
                    recipe,
                    pick,
                    status=entry_status,
                )
                db.flush()
                arranged_entry_count += 1
                meal["recipe_id"] = recipe.id
                meal["entry_id"] = entry.id
                meal["status"] = entry_status
                meal.pop("pick", None)

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    log.info(
        "meal-plan arranged from selected pool",
        extra={
            "event": "meal_plan_arranged",
            "domain": "meal_plan",
            "replaced_entry_count": len(replaceable),
            "arranged_entry_count": arranged_entry_count,
            "selected_breakfast_count": len(body.breakfast_dishes),
            "selected_main_count": len(body.main_dishes),
            "warning_count": len(plan.get("warnings", [])),
        },
    )
    return {
        **plan,
        "replaced_entry_count": len(replaceable),
        "arranged_entry_count": arranged_entry_count,
    }


@router.post("/entry")
def add_entry(
    body: MealPlanEntryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if not body.recipe_id and not body.custom_name:
        raise HTTPException(status_code=422, detail="recipe_id or custom_name required")
    if body.meal_type not in ("breakfast", "lunch", "dinner"):
        raise HTTPException(status_code=422, detail="Invalid meal_type")

    recipe = None
    if body.recipe_id:
        recipe = recipe_access.get_visible_recipe(db, body.recipe_id, current_user.id)
        if recipe is None:
            raise HTTPException(status_code=404, detail="Recipe not found")

    existing = (
        db.query(models.MealPlanEntry)
        .filter(
            models.MealPlanEntry.user_id == current_user.id,
            models.MealPlanEntry.date == body.date,
            models.MealPlanEntry.meal_type == body.meal_type,
        )
        .first()
    )

    if existing:
        existing.recipe_id = body.recipe_id
        existing.custom_name = body.custom_name
        db.commit()
        warnings = meal_scheduler.validate_slot(
            db, current_user.id, body.date, body.meal_type, recipe
        ) if recipe else []
        log.info(
            "meal-plan entry updated",
            extra={
                "event": "meal_plan_entry_saved",
                "domain": "meal_plan",
                "entry_id": existing.id,
                "date": existing.date,
                "meal_type": existing.meal_type,
                "updated_existing": True,
                "has_recipe": existing.recipe_id is not None,
                "has_custom_name": bool(existing.custom_name),
                "warnings_count": len(warnings),
            },
        )
        return {"id": existing.id, "date": existing.date,
                "meal_type": existing.meal_type, "warnings": warnings}

    entry = models.MealPlanEntry(
        user_id=current_user.id,
        date=body.date,
        meal_type=body.meal_type,
        recipe_id=body.recipe_id,
        custom_name=body.custom_name,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    warnings = meal_scheduler.validate_slot(
        db, current_user.id, body.date, body.meal_type, recipe
    ) if recipe else []
    log.info(
        "meal-plan entry created",
        extra={
            "event": "meal_plan_entry_saved",
            "domain": "meal_plan",
            "entry_id": entry.id,
            "date": entry.date,
            "meal_type": entry.meal_type,
            "updated_existing": False,
            "has_recipe": entry.recipe_id is not None,
            "has_custom_name": bool(entry.custom_name),
            "warnings_count": len(warnings),
        },
    )
    return {"id": entry.id, "date": entry.date,
            "meal_type": entry.meal_type, "warnings": warnings}


@router.delete("/entry/{entry_id}")
def delete_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    entry = (
        db.query(models.MealPlanEntry)
        .filter(
            models.MealPlanEntry.id == entry_id,
            models.MealPlanEntry.user_id == current_user.id,
        )
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    log.info(
        "meal-plan entry deleted",
        extra={
            "event": "meal_plan_entry_deleted",
            "domain": "meal_plan",
            "entry_id": entry.id,
            "date": entry.date,
            "meal_type": entry.meal_type,
            "had_recipe": entry.recipe_id is not None,
            "had_custom_name": bool(entry.custom_name),
        },
    )
    db.delete(entry)
    db.commit()
    return {"message": "Deleted"}


# ── Candidate generation ─────────────────────────────────────────────────────

def _saved_recipe_candidate(row: models.UserSavedRecipe) -> dict:
    r = row.recipe
    return {
        "source": "saved",
        "recipe_id": r.id,
        "saved_id": row.id,
        "name": r.name,
        "ingredients": r.ingredients,
        "method_steps": r.steps,
        "meal_types": r.meal_types,
        "totals": {
            "kcal": r.calories,
            "protein_g": r.protein_g,
            "carbs_g": r.carbs_g,
            "fat_g": r.fat_g,
        },
        "serving_g": r.serving_g,
    }


def _fresh_candidate(cand: dict) -> dict:
    return {"source": "fresh", **cand}


@router.get("/candidates")
def get_candidates(
    refresh: bool = False,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Return per-slot candidates for the upcoming 7-day meal plan.

    Candidates come from two sources:

      * the user's saved-recipe library (matched by meal_type), always
        returned for free — no LLM call involved;
      * fresh LLM-generated dishes, included only when `refresh=true` AND
        the user's recipe-suggester quota allows. Each fresh-refresh call
        counts once against the 3-per-rolling-7-days budget.

    The response carries the live quota so the UI can show "N refreshes
    remaining" and "next refresh available at ...".
    """
    plan = menu_planner.week_plan(db, current_user)
    if plan.get("feasibility") == "not_closed_loop":
        log.warning(
            "meal-plan candidates blocked by infeasible library",
            extra={
                "event": "meal_plan_candidates_blocked",
                "domain": "meal_plan",
                "reason": "not_closed_loop",
                "blocking_buckets_count": len(plan.get("blocking_buckets", [])),
            },
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "not_closed_loop",
                "message_zh": plan.get("message_zh"),
                "message_en": plan.get("message_en"),
                "blocking_buckets": plan.get("blocking_buckets", []),
            },
        )
    if plan.get("feasibility") == "no_bmr":
        log.info(
            "meal-plan candidates blocked by missing bmr profile",
            extra={
                "event": "meal_plan_candidates_blocked",
                "domain": "meal_plan",
                "reason": "no_bmr",
            },
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "no_bmr",
                "message_zh": plan.get("message_zh"),
                "message_en": plan.get("message_en"),
            },
        )

    solved = plan["solved_picks"]
    requirements = plan["nutrition_requirements"]
    language = current_user.language or "zh"

    # Saved-library → per-meal-type buckets. A saved recipe with empty
    # meal_types is treated as usable for any slot.
    saved_rows = saved_recipes.list_for_user(db, current_user.id)
    by_meal_type: dict[str, list[models.UserSavedRecipe]] = {mt: [] for mt in MEAL_TYPES}
    for row in saved_rows:
        mt_csv = (row.recipe.meal_types or "").strip()
        if not mt_csv:
            for mt in MEAL_TYPES:
                by_meal_type[mt].append(row)
            continue
        for token in mt_csv.split(","):
            token = token.strip().lower()
            if token in by_meal_type:
                by_meal_type[token].append(row)

    # Decide whether to invoke the LLM. If the user asked for fresh ideas
    # we count it against the quota (one call = one whole-week refresh).
    fresh_result: dict = {"candidates": {}, "warnings": []}
    quota_usage = llm_quota.usage(db, current_user.id, llm_quota.RECIPE_SUGGEST)
    refresh_status = "not_requested"

    if refresh:
        refresh_quota_call_id: Optional[int] = None
        try:
            quota_charge = llm_quota.check_and_consume(db, current_user.id, llm_quota.RECIPE_SUGGEST)
        except llm_quota.LLMQuotaExceeded:
            refresh_status = "quota_exhausted"
        else:
            refresh_quota_call_id = quota_charge.get("call_log_id")
            db.commit()
            slugs = nutrition_audit.load_user_library(db, current_user.id)
            try:
                fresh_result = recipe_suggester.suggest_for_solved_picks(
                    solved,
                    slugs,
                    language=language,
                )
            except Exception as exc:
                if llm_quota.refund_call(
                    db,
                    refresh_quota_call_id,
                    user_id=current_user.id,
                    kind=llm_quota.RECIPE_SUGGEST,
                ):
                    db.commit()
                fresh_result = {"candidates": {}, "warnings": [f"refresh failed ({exc.__class__.__name__})"]}
                refresh_status = "refunded_error"
            else:
                fresh_count = sum(len(items) for items in fresh_result.get("candidates", {}).values())
                if fresh_count == 0:
                    if llm_quota.refund_call(
                        db,
                        refresh_quota_call_id,
                        user_id=current_user.id,
                        kind=llm_quota.RECIPE_SUGGEST,
                    ):
                        db.commit()
                    refresh_status = "refunded_no_candidates"
                else:
                    refresh_status = "refreshed"
            quota_usage = llm_quota.usage(db, current_user.id, llm_quota.RECIPE_SUGGEST)

    fresh_by_slot = fresh_result.get("candidates", {})

    # Build the response by projecting over nutrition_requirements so the
    # frontend can render cleanly without needing solved_picks.
    days_payload: list[dict] = []
    for req_day in requirements["days"]:
        meals_payload: dict[str, dict] = {}
        for mt, req_meal in req_day["meals"].items():
            slot_key = f"{req_day['date']}/{mt}"
            fresh_list = fresh_by_slot.get(slot_key, [])
            saved_list = [
                _saved_recipe_candidate(row) for row in by_meal_type.get(mt, [])
            ]
            meals_payload[mt] = {
                "meal_type": mt,
                "target_kcal": req_meal["target_kcal"],
                "target_protein_g": req_meal["target_protein_g"],
                "target_carbs_g": req_meal["target_carbs_g"],
                "target_fat_g": req_meal["target_fat_g"],
                "bucket_hints": req_meal["bucket_hints"],
                "saved_candidates": saved_list,
                "fresh_candidates": [_fresh_candidate(c) for c in fresh_list],
            }
        days_payload.append({
            "date": req_day["date"],
            "weekday": req_day["weekday"],
            "day_type": req_day["day_type"],
            "day_type_label_zh": req_day["day_type_label_zh"],
            "day_type_label_en": req_day["day_type_label_en"],
            "activity_level": req_day["activity_level"],
            "activity_is_logged": req_day["activity_is_logged"],
            "target": req_day["target"],
            "meals": meals_payload,
        })

    saved_candidate_count = sum(
        len(meal["saved_candidates"])
        for day in days_payload
        for meal in day["meals"].values()
    )
    fresh_candidate_count = sum(
        len(meal["fresh_candidates"])
        for day in days_payload
        for meal in day["meals"].values()
    )
    log.info(
        "meal-plan candidates viewed",
        extra={
            "event": "meal_plan_candidates_viewed",
            "domain": "meal_plan",
            "refresh_requested": refresh,
            "refresh_status": refresh_status,
            "day_count": len(days_payload),
            "saved_library_count": len(saved_rows),
            "saved_candidate_count": saved_candidate_count,
            "fresh_candidate_count": fresh_candidate_count,
            "warnings_count": len(fresh_result.get("warnings", [])),
        },
    )
    return {
        "start_date": plan["start_date"],
        "targets_baseline": plan["targets_baseline"],
        "days": days_payload,
        "weekly_totals_target": requirements["weekly_totals_target"],
        "saved_library": {
            "count": len(saved_rows),
            "cap": saved_recipes.cap_for_user(current_user),
        },
        "llm_quota": {
            **quota_usage,
            "kind": llm_quota.RECIPE_SUGGEST,
        },
        "refresh_status": refresh_status,
        "warnings": fresh_result.get("warnings", []),
    }


# ── Streaming refresh (Server-Sent Events) ───────────────────────────────────

def _sse(event: str, payload: dict) -> str:
    """Format a single SSE frame."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _meals_payload_for_day(
    req_day: dict,
    fresh_by_slot: dict[str, list[dict]],
    saved_by_meal_type: dict[str, list[models.UserSavedRecipe]],
) -> dict:
    """Assemble the per-day meal payload consumed by the frontend."""
    meals_payload: dict[str, dict] = {}
    for mt, req_meal in req_day["meals"].items():
        slot_key = f"{req_day['date']}/{mt}"
        fresh_list = fresh_by_slot.get(slot_key, [])
        saved_list = [
            _saved_recipe_candidate(row) for row in saved_by_meal_type.get(mt, [])
        ]
        meals_payload[mt] = {
            "meal_type": mt,
            "target_kcal": req_meal["target_kcal"],
            "target_protein_g": req_meal["target_protein_g"],
            "target_carbs_g": req_meal["target_carbs_g"],
            "target_fat_g": req_meal["target_fat_g"],
            "bucket_hints": req_meal["bucket_hints"],
            "saved_candidates": saved_list,
            "fresh_candidates": [_fresh_candidate(c) for c in fresh_list],
        }
    return {
        "date": req_day["date"],
        "weekday": req_day["weekday"],
        "day_type": req_day["day_type"],
        "day_type_label_zh": req_day["day_type_label_zh"],
        "day_type_label_en": req_day["day_type_label_en"],
        "activity_level": req_day["activity_level"],
        "activity_is_logged": req_day["activity_is_logged"],
        "target": req_day["target"],
        "meals": meals_payload,
    }


@router.get("/candidates/stream")
async def stream_candidate_refresh(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Refresh meal-plan candidates, streaming per-day results as Server-Sent
    Events so the UI can render a progress modal.

    Validates quota and plan feasibility up-front (raising HTTP errors for
    pre-stream failures), then opens a `text/event-stream` that emits:

      * ``start`` — week-level framing (total days, baseline targets,
        saved library, initial quota).
      * ``day_ready`` — one per day, payload matches a single entry of the
        sync endpoint's ``days`` array.
      * ``done`` — final summary (refresh_status, aggregated warnings,
        post-consume quota).

    Quota is consumed once, at stream start, to match the sync endpoint's
    fire-and-charge semantics (a client that disconnects mid-stream has
    already paid for the LLM work that is continuing in the background).
    """
    # Pre-stream validation — convert these to regular HTTP errors so the
    # frontend's fetch() rejects before opening the event reader.
    try:
        llm_quota.check(db, current_user.id, llm_quota.RECIPE_SUGGEST)
    except llm_quota.LLMQuotaExceeded as exc:
        log.info(
            "meal-plan candidates stream blocked by exhausted quota",
            extra={
                "event": "meal_plan_candidates_stream_blocked",
                "domain": "meal_plan",
                "reason": "quota_exhausted",
            },
        )
        raise HTTPException(
            status_code=429,
            detail={
                "error": "quota_exhausted",
                "kind": llm_quota.RECIPE_SUGGEST,
                "message_zh": "本周刷新次数已用完。",
                "message_en": "Refresh quota exhausted for this week.",
                "next_refresh_at": exc.next_refresh_at.isoformat()
                    if getattr(exc, "next_refresh_at", None) else None,
            },
        )

    plan = menu_planner.week_plan(db, current_user)
    if plan.get("feasibility") == "not_closed_loop":
        log.warning(
            "meal-plan candidates stream blocked by infeasible library",
            extra={
                "event": "meal_plan_candidates_stream_blocked",
                "domain": "meal_plan",
                "reason": "not_closed_loop",
                "blocking_buckets_count": len(plan.get("blocking_buckets", [])),
            },
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "not_closed_loop",
                "message_zh": plan.get("message_zh"),
                "message_en": plan.get("message_en"),
                "blocking_buckets": plan.get("blocking_buckets", []),
            },
        )
    if plan.get("feasibility") == "no_bmr":
        log.info(
            "meal-plan candidates stream blocked by missing bmr profile",
            extra={
                "event": "meal_plan_candidates_stream_blocked",
                "domain": "meal_plan",
                "reason": "no_bmr",
            },
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "no_bmr",
                "message_zh": plan.get("message_zh"),
                "message_en": plan.get("message_en"),
            },
        )

    solved = plan["solved_picks"]
    requirements = plan["nutrition_requirements"]
    language = current_user.language or "zh"
    library_slugs = nutrition_audit.load_user_library(db, current_user.id)

    # Index saved-library rows by meal type once — reused in every day event.
    saved_rows = saved_recipes.list_for_user(db, current_user.id)
    saved_by_meal_type: dict[str, list[models.UserSavedRecipe]] = {
        mt: [] for mt in MEAL_TYPES
    }
    for row in saved_rows:
        mt_csv = (row.recipe.meal_types or "").strip()
        if not mt_csv:
            for mt in MEAL_TYPES:
                saved_by_meal_type[mt].append(row)
            continue
        for token in mt_csv.split(","):
            token = token.strip().lower()
            if token in saved_by_meal_type:
                saved_by_meal_type[token].append(row)

    # Pair every req_day with its solved_picks slot bundle so the LLM can be
    # handed the solver's picks as guidance.
    solved_by_date = {d["date"]: d for d in solved.get("days", [])}
    day_units: list[tuple[dict, list[dict]]] = []  # (req_day, day_slots)
    for req_day in requirements["days"]:
        solved_day = solved_by_date.get(req_day["date"])
        day_slots = (
            recipe_suggester.build_day_slots(solved_day) if solved_day else []
        )
        day_units.append((req_day, day_slots))

    # Consume quota up front — matches sync endpoint semantics.
    quota_usage_before = llm_quota.usage(db, current_user.id, llm_quota.RECIPE_SUGGEST)
    stream_quota_call_id: Optional[int] = None
    try:
        quota_charge = llm_quota.check_and_consume(db, current_user.id, llm_quota.RECIPE_SUGGEST)
    except llm_quota.LLMQuotaExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "quota_exhausted",
                "kind": llm_quota.RECIPE_SUGGEST,
                "message_zh": "本周刷新次数已用完。",
                "message_en": "Refresh quota exhausted for this week.",
                "next_refresh_at": exc.next_refresh_at.isoformat()
                if getattr(exc, "next_refresh_at", None) else None,
            },
        )
    stream_quota_call_id = quota_charge.get("call_log_id")
    db.commit()
    quota_usage_after = llm_quota.usage(db, current_user.id, llm_quota.RECIPE_SUGGEST)

    saved_library_payload = {
        "count": len(saved_rows),
        "cap": saved_recipes.cap_for_user(current_user),
    }
    log.info(
        "meal-plan candidates stream started",
        extra={
            "event": "meal_plan_candidates_stream_started",
            "domain": "meal_plan",
            "day_count": len(day_units),
            "saved_library_count": saved_library_payload["count"],
            "quota_used_before": quota_usage_before.get("used"),
            "quota_remaining_before": quota_usage_before.get("remaining"),
        },
    )

    async def event_stream():
        yield _sse("start", {
            "total_days": len(day_units),
            "start_date": plan["start_date"],
            "targets_baseline": plan["targets_baseline"],
            "weekly_totals_target": requirements["weekly_totals_target"],
            "saved_library": saved_library_payload,
            "llm_quota": {**quota_usage_before, "kind": llm_quota.RECIPE_SUGGEST},
        })

        # Launch all day-level LLM calls concurrently. Sync LLM client →
        # asyncio.to_thread lets them overlap on I/O. We wrap each call so
        # req_day rides along with its result — as_completed only exposes
        # completion order, not the originating task.
        async def _run_day(req_day: dict, day_slots: list[dict]) -> tuple[dict, dict]:
            result = await asyncio.to_thread(
                recipe_suggester.suggest_for_day,
                req_day["date"],
                day_slots,
                library_slugs,
                language,
                recipe_suggester.CANDIDATES_PER_SLOT,
            )
            return req_day, result

        day_tasks = [
            asyncio.create_task(_run_day(rd, ds)) for rd, ds in day_units
        ]

        warnings_total: list[str] = []
        total_fresh_candidates = 0
        try:
            for finished in asyncio.as_completed(day_tasks):
                req_day, day_result = await finished
                warnings_total.extend(day_result["warnings"])
                for slot_cands in day_result["candidates"].values():
                    total_fresh_candidates += len(slot_cands)
                payload = _meals_payload_for_day(
                    req_day,
                    day_result["candidates"],
                    saved_by_meal_type,
                )
                yield _sse("day_ready", payload)
        except Exception as exc:
            log.exception("candidates stream failed mid-flight: %s", exc)
            # Fully failed — refund the quota we charged up front.
            if llm_quota.refund_call(
                db,
                stream_quota_call_id,
                user_id=current_user.id,
                kind=llm_quota.RECIPE_SUGGEST,
            ):
                db.commit()
            yield _sse("error", {
                "error": "stream_failed",
                "message_zh": "生成过程中出现错误，请稍后重试。本次刷新次数已退回。",
                "message_en": "Something went wrong while generating candidates. The refresh has been refunded.",
            })
            return

        # If every single slot came back empty, the LLM gave us nothing and
        # the user shouldn't have to pay for it. Refund so they can retry.
        final_quota = quota_usage_after
        final_status = "refreshed"
        if total_fresh_candidates == 0:
            if llm_quota.refund_call(
                db,
                stream_quota_call_id,
                user_id=current_user.id,
                kind=llm_quota.RECIPE_SUGGEST,
            ):
                db.commit()
                final_quota = llm_quota.usage(
                    db, current_user.id, llm_quota.RECIPE_SUGGEST,
                )
                final_status = "refunded_no_candidates"
                log.warning(
                    "candidates stream produced 0 candidates across all days; "
                    "refunded quota for user=%d", current_user.id,
                )

        log.info(
            "meal-plan candidates stream finished",
            extra={
                "event": "meal_plan_candidates_stream_finished",
                "domain": "meal_plan",
                "day_count": len(day_units),
                "fresh_candidate_count": total_fresh_candidates,
                "warnings_count": len(warnings_total),
                "refresh_status": final_status,
                "quota_used_after": final_quota.get("used"),
                "quota_remaining_after": final_quota.get("remaining"),
            },
        )
        yield _sse("done", {
            "refresh_status": final_status,
            "saved_library": saved_library_payload,
            "llm_quota": {**final_quota, "kind": llm_quota.RECIPE_SUGGEST},
            "warnings": warnings_total,
        })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable proxy buffering so events flush promptly
        },
    )


# ── Selecting a day's meals ──────────────────────────────────────────────────

class MealPick(BaseModel):
    recipe_id: Optional[int] = Field(default=None, ge=1)      # existing master-DB recipe
    name: Optional[str] = Field(default=None, max_length=120)           # required when recipe_id is None
    ingredients: Optional[str] = Field(default=None, max_length=4000)
    ingredients_json: Optional[list[PoolIngredient]] = Field(default=None, max_length=50)
    ingredient_slugs: Optional[list[str]] = Field(default=None, max_length=50)
    meal_types: Optional[str] = Field(default=None, max_length=80)     # CSV: lunch,dinner
    portion_g: Optional[float] = Field(default=None, gt=0, le=3000)
    calories: Optional[int] = Field(default=None, ge=0, le=5000)
    protein_g: Optional[float] = Field(default=None, ge=0, le=500)
    carbs_g: Optional[float] = Field(default=None, ge=0, le=1000)
    fat_g: Optional[float] = Field(default=None, ge=0, le=500)
    method_steps: Optional[str] = Field(default=None, max_length=4000)
    seasonings: Optional[list[PoolSeasoning]] = Field(default=None, max_length=30)
    day_type_affinities: Optional[list[str]] = Field(default=None, max_length=20)


class MealPlanSelect(BaseModel):
    date: str = Field(..., min_length=10, max_length=10)
    breakfast: Optional[MealPick] = None
    lunch: Optional[MealPick] = None
    dinner: Optional[MealPick] = None


def _resolve_recipe(db: Session, user_id: int, meal_type: str, pick: MealPick) -> models.Recipe:
    """Return the Recipe row for the pick, creating a pending one if fresh."""
    if pick.recipe_id is not None:
        recipe = recipe_access.get_visible_recipe(db, pick.recipe_id, user_id)
        if not recipe:
            raise HTTPException(status_code=404, detail=f"Recipe {pick.recipe_id} not found")
        return recipe

    if not pick.name:
        raise HTTPException(
            status_code=422,
            detail=f"{meal_type} pick requires either recipe_id or a dish name",
        )

    ingredients_json = [
        {"slug": item.slug, "grams": round(float(item.grams or 0), 1), "required": True}
        for item in (pick.ingredients_json or [])
        if str(item.slug or "").strip()
    ]
    ingredient_slugs = pick.ingredient_slugs or [item["slug"] for item in ingredients_json]
    ingredients_text = pick.ingredients
    if not ingredients_text and ingredients_json:
        ingredients_text = "\n".join(
            f"{FL.display_name(item['slug'], 'zh') or item['slug']} {item['grams']}g"
            for item in ingredients_json
        )

    # Fresh LLM-generated dish — persist as pending for admin review.
    recipe = models.Recipe(
        name=pick.name,
        ingredients=ingredients_text,
        steps=pick.method_steps,
        meal_types=pick.meal_types or meal_type,
        calories=pick.calories,
        protein_g=pick.protein_g,
        carbs_g=pick.carbs_g,
        fat_g=pick.fat_g,
        serving_g=pick.portion_g,
        ingredient_slugs=json.dumps(sorted({slug for slug in ingredient_slugs if slug})),
        ingredients_json=json.dumps(ingredients_json, ensure_ascii=False) if ingredients_json else None,
        is_builtin=False,
        submitted_by=user_id,
        is_approved=False,
    )
    db.add(recipe)
    db.flush()
    return recipe


def _upsert_entry(
    db: Session,
    user_id: int,
    date: str,
    meal_type: str,
    recipe: models.Recipe,
    pick: MealPick,
    *,
    status: Optional[str] = None,
):
    existing = (
        db.query(models.MealPlanEntry)
        .filter(
            models.MealPlanEntry.user_id == user_id,
            models.MealPlanEntry.date == date,
            models.MealPlanEntry.meal_type == meal_type,
        )
        .first()
    )
    use_recipe_defaults = pick.recipe_id is not None and status == pc.SLOT_STATUS_RECIPE
    portion_g = recipe.serving_g if use_recipe_defaults else (pick.portion_g if pick.portion_g is not None else recipe.serving_g)
    calories = recipe.calories if use_recipe_defaults else (pick.calories if pick.calories is not None else recipe.calories)
    protein_g = recipe.protein_g if use_recipe_defaults else (pick.protein_g if pick.protein_g is not None else recipe.protein_g)
    carbs_g = recipe.carbs_g if use_recipe_defaults else (pick.carbs_g if pick.carbs_g is not None else recipe.carbs_g)
    fat_g = recipe.fat_g if use_recipe_defaults else (pick.fat_g if pick.fat_g is not None else recipe.fat_g)

    if existing:
        existing.recipe_id = recipe.id
        existing.custom_name = None
        existing.portion_g = portion_g
        existing.calories = calories
        existing.protein_g = protein_g
        existing.carbs_g = carbs_g
        existing.fat_g = fat_g
        if status is not None:
            existing.status = status
        return existing

    entry = models.MealPlanEntry(
        user_id=user_id,
        date=date,
        meal_type=meal_type,
        recipe_id=recipe.id,
        portion_g=portion_g,
        calories=calories,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
        status=status or pc.SLOT_STATUS_RECIPE,
    )
    db.add(entry)
    return entry


@router.post("/select")
def select_day_meals(
    body: MealPlanSelect,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Commit meal picks for a day, one to three at a time.

    Each chosen recipe is auto-saved to the saved-recipe library (up to the
    tier cap).  The response always includes a `warnings` list — empty means
    all picks are diverse; non-empty carries ingredient-overuse or day-type
    mismatch hints.  Warnings do not block the save.
    """
    saved: dict[str, dict] = {}
    all_warnings: list[dict] = []
    picks = {
        "breakfast": body.breakfast,
        "lunch": body.lunch,
        "dinner": body.dinner,
    }
    for meal_type, pick in picks.items():
        if pick is None:
            continue
        recipe = _resolve_recipe(db, current_user.id, meal_type, pick)

        try:
            saved_recipes.save_on_select(db, current_user, recipe.id)
        except saved_recipes.SavedRecipeCapReached:
            db.rollback()
            cap = saved_recipes.cap_for_user(current_user)
            current = saved_recipes.count_for_user(db, current_user.id)
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "saved_recipe_cap_reached",
                    "cap": cap,
                    "current": current,
                    "blocking_meal_type": meal_type,
                    "message_zh": (
                        f"个人菜谱库已达上限（{cap} 个），请先删除后再选择新菜品。"
                    ),
                    "message_en": (
                        f"Saved-recipe library full ({cap} dishes). "
                        "Please delete one before selecting a new dish."
                    ),
                },
            )

        # Validate ingredient distribution — soft warning only.
        slot_warnings = meal_scheduler.validate_slot(
            db, current_user.id, body.date, meal_type, recipe
        )
        for w in slot_warnings:
            w["meal_type"] = meal_type
        all_warnings.extend(slot_warnings)

        entry = _upsert_entry(db, current_user.id, body.date, meal_type, recipe, pick)
        saved[meal_type] = {
            "recipe_id": recipe.id,
            "pending_review": not recipe.is_approved,
        }
        db.flush()
        _ = entry
    db.commit()
    saved_library_count = saved_recipes.count_for_user(db, current_user.id)
    saved_library_cap = saved_recipes.cap_for_user(current_user)
    log.info(
        "meal-plan day selected",
        extra={
            "event": "meal_plan_day_selected",
            "domain": "meal_plan",
            "date": body.date,
            "selected_meal_count": len(saved),
            "pending_review_count": sum(1 for item in saved.values() if item["pending_review"]),
            "warnings_count": len(all_warnings),
            "saved_library_count": saved_library_count,
            "saved_library_cap": saved_library_cap,
        },
    )
    return {
        "date": body.date,
        "saved": saved,
        "warnings": all_warnings,
        "saved_library": {
            "count": saved_library_count,
            "cap": saved_library_cap,
        },
    }


# ── Confirmation + confirm-to-log ────────────────────────────────────────────

@router.post("/confirm")
def confirm_day(
    date: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """User-initiated save: marks the plan confirmed and copies to DietLog now."""
    entries = (
        db.query(models.MealPlanEntry)
        .filter(
            models.MealPlanEntry.user_id == current_user.id,
            models.MealPlanEntry.date == date,
        )
        .all()
    )
    if not entries:
        raise HTTPException(status_code=404, detail="No meal plan for that date")

    filled: list[str] = []
    for entry in entries:
        if entry.meal_type not in MEAL_TYPES:
            continue
        existing_log = (
            db.query(models.DietLog)
            .filter(
                models.DietLog.user_id == current_user.id,
                models.DietLog.date == date,
                models.DietLog.meal_type == entry.meal_type,
            )
            .first()
        )
        if existing_log:
            pc.mark_plan_slot_recorded(db, current_user.id, date, entry.meal_type)
            continue
        db.add(autofill.build_diet_log_from_entry(entry))
        pc.mark_plan_slot_recorded(db, current_user.id, date, entry.meal_type)
        filled.append(entry.meal_type)

    existing_conf = (
        db.query(models.DailyMealPlanConfirmation)
        .filter(
            models.DailyMealPlanConfirmation.user_id == current_user.id,
            models.DailyMealPlanConfirmation.date == date,
        )
        .first()
    )
    if not existing_conf:
        db.add(models.DailyMealPlanConfirmation(
            user_id=current_user.id,
            date=date,
        ))
    db.commit()
    log.info(
        "meal-plan day confirmed",
        extra={
            "event": "meal_plan_day_confirmed",
            "domain": "meal_plan",
            "date": date,
            "filled_meal_count": len(filled),
            "created_confirmation": existing_conf is None,
        },
    )
    return {"date": date, "filled": filled, "confirmed": True}


# ── Saved-recipe library ─────────────────────────────────────────────────────

def _saved_recipe_payload(row: models.UserSavedRecipe) -> dict:
    r = row.recipe
    return {
        "saved_id": row.id,
        "saved_at": row.saved_at.isoformat() if row.saved_at else None,
        "recipe": {
            "id": r.id,
            "name": r.name,
            "ingredients": r.ingredients,
            "steps": r.steps,
            "meal_types": r.meal_types,
            "calories": r.calories,
            "protein_g": r.protein_g,
            "carbs_g": r.carbs_g,
            "fat_g": r.fat_g,
            "serving_g": r.serving_g,
            "is_approved": r.is_approved,
        },
    }


@router.get("/saved-recipes")
def list_saved_recipes(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    rows = saved_recipes.list_for_user(db, current_user.id)
    cap = saved_recipes.cap_for_user(current_user)
    return {
        "items": [_saved_recipe_payload(r) for r in rows],
        "count": len(rows),
        "cap": cap,
    }


@router.delete("/saved-recipes/{recipe_id}")
def delete_saved_recipe(
    recipe_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    removed = saved_recipes.delete_for_user(db, current_user.id, recipe_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Saved recipe not found")
    db.commit()
    count = saved_recipes.count_for_user(db, current_user.id)
    cap = saved_recipes.cap_for_user(current_user)
    log.info(
        "saved recipe deleted",
        extra={
            "event": "saved_recipe_deleted",
            "domain": "meal_plan",
            "recipe_id": recipe_id,
            "saved_library_count": count,
            "saved_library_cap": cap,
        },
    )
    return {
        "recipe_id": recipe_id,
        "count": count,
        "cap": cap,
    }
