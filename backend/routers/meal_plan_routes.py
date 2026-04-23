import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from services import (
    autofill,
    calorie,
    food_library as FL,
    llm_quota,
    meal_scheduler,
    menu_planner,
    nutrition_audit,
    planning_context as pc,
    recipe_suggester,
    saved_recipes,
)

log = logging.getLogger("compass.app")

router = APIRouter(prefix="/api/meal-plan", tags=["meal-plan"])


MEAL_TYPES = ("breakfast", "lunch", "dinner")


class MealPlanEntryCreate(BaseModel):
    date: str           # "YYYY-MM-DD"
    meal_type: str      # breakfast / lunch / dinner
    recipe_id: Optional[int] = None
    custom_name: Optional[str] = None


@router.get("/week")
def get_week_plan(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Return the 7-day window centred on today (today −3 … today +3)."""
    today = datetime.now(timezone.utc)
    days = [(today + timedelta(days=off)).strftime("%Y-%m-%d") for off in range(-3, 4)]

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

    today_str = today.strftime("%Y-%m-%d")
    return {
        "today": today_str,
        "days": [{"date": d, "meals": result[d]} for d in days],
    }


@router.get("/pool")
def get_dish_pool(
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
    pool = menu_planner.generate_dish_pool(db, current_user)
    if "message_zh" in pool:
        status = pool.get("feasibility", "error")
        raise HTTPException(
            status_code=400,
            detail={
                "error": status,
                "message_zh": pool.get("message_zh"),
                "message_en": pool.get("message_en"),
            },
        )
    return pool


@router.post("/pool/name")
def name_dish_pool(
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
    try:
        llm_quota.check(db, current_user.id, llm_quota.POOL_NAME)
    except llm_quota.LLMQuotaExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "quota_exhausted",
                "kind": llm_quota.POOL_NAME,
                "message_zh": "本周菜谱命名次数已用完。",
                "message_en": "Pool naming quota exhausted for this week.",
                "next_refresh_at": exc.next_refresh_at.isoformat()
                    if getattr(exc, "next_refresh_at", None) else None,
            },
        )

    pool_data = menu_planner.generate_dish_pool(db, current_user)
    if "message_zh" in pool_data:
        raise HTTPException(
            status_code=400,
            detail={
                "error": pool_data.get("feasibility", "error"),
                "message_zh": pool_data.get("message_zh"),
                "message_en": pool_data.get("message_en"),
            },
        )

    all_sketches = pool_data.get("breakfast_pool", []) + pool_data.get("main_pool", [])
    language = current_user.language or "zh"

    llm_quota.consume(db, current_user.id, llm_quota.POOL_NAME)
    db.commit()

    try:
        result = recipe_suggester.suggest_pool_names(all_sketches, language)
    except Exception as exc:
        llm_quota.refund_latest(db, current_user.id, llm_quota.POOL_NAME)
        db.commit()
        raise HTTPException(
            status_code=502,
            detail={
                "error": "llm_failed",
                "message_zh": "菜谱命名失败，请稍后重试。",
                "message_en": f"Pool naming failed: {exc.__class__.__name__}",
            },
        )

    named_dishes = result.get("named_dishes", [])
    if not named_dishes:
        llm_quota.refund_latest(db, current_user.id, llm_quota.POOL_NAME)
        db.commit()

    quota_usage = llm_quota.usage(db, current_user.id, llm_quota.POOL_NAME)
    return {
        "breakfast_dishes": [d for d in named_dishes if d["meal_type"] == "breakfast"],
        "main_dishes":      [d for d in named_dishes if d["meal_type"] == "main"],
        "week_skeleton":    pool_data.get("week_skeleton", []),
        "required_slot_counts": pool_data.get("required_slot_counts", {}),
        "requires_breakfast_pool": bool(pool_data.get("requires_breakfast_pool", True)),
        "requires_main_pool": bool(pool_data.get("requires_main_pool", True)),
        "warnings":         result.get("warnings", []),
        "llm_quota":        {**quota_usage, "kind": llm_quota.POOL_NAME},
    }


class PoolIngredient(BaseModel):
    slug: str
    grams: float


class PoolSeasoning(BaseModel):
    name: str
    grams: Optional[float] = None


class PoolDish(BaseModel):
    dish_id: Optional[str] = None
    meal_type: str
    name: str
    ingredients: list[PoolIngredient]
    totals: dict[str, float]
    ingredient_slugs: list[str] = []
    day_type_affinities: list[str] = []
    method_steps: Optional[str] = None
    seasonings: list[PoolSeasoning] = []


class MealPlanArrange(BaseModel):
    breakfast_dishes: list[PoolDish]
    main_dishes: list[PoolDish]


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
    week_dates = [
        (datetime.now(timezone.utc) + timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range(7)
    ]
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
                signature = (
                    pick.name,
                    meal_type,
                    tuple((item.slug, round(float(item.grams or 0), 1)) for item in (pick.ingredients_json or [])),
                )
                recipe = recipe_cache.get(signature)
                if recipe is None:
                    recipe = _resolve_recipe(db, current_user.id, meal_type, pick)
                    recipe_cache[signature] = recipe
                entry = _upsert_entry(
                    db,
                    current_user.id,
                    day["date"],
                    meal_type,
                    recipe,
                    pick,
                    status=pc.SLOT_STATUS_GENERATED,
                )
                db.flush()
                arranged_entry_count += 1
                meal["recipe_id"] = recipe.id
                meal["entry_id"] = entry.id
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
        recipe = db.query(models.Recipe).filter(
            models.Recipe.id == body.recipe_id
        ).first()

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
        try:
            llm_quota.check(db, current_user.id, llm_quota.RECIPE_SUGGEST)
        except llm_quota.LLMQuotaExceeded:
            refresh_status = "quota_exhausted"
        else:
            slugs = nutrition_audit.load_user_library(db, current_user.id)
            fresh_result = recipe_suggester.suggest_for_solved_picks(
                solved,
                slugs,
                language=language,
            )
            llm_quota.consume(db, current_user.id, llm_quota.RECIPE_SUGGEST)
            db.commit()
            quota_usage = llm_quota.usage(db, current_user.id, llm_quota.RECIPE_SUGGEST)
            refresh_status = "refreshed"

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
    llm_quota.consume(db, current_user.id, llm_quota.RECIPE_SUGGEST)
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
            llm_quota.refund_latest(db, current_user.id, llm_quota.RECIPE_SUGGEST)
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
            if llm_quota.refund_latest(db, current_user.id, llm_quota.RECIPE_SUGGEST):
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
    recipe_id: Optional[int] = None      # existing master-DB recipe
    name: Optional[str] = None           # required when recipe_id is None
    ingredients: Optional[str] = None
    ingredients_json: Optional[list[PoolIngredient]] = None
    ingredient_slugs: Optional[list[str]] = None
    meal_types: Optional[str] = None     # CSV: lunch,dinner
    portion_g: Optional[float] = None
    calories: Optional[int] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    method_steps: Optional[str] = None
    seasonings: Optional[list[PoolSeasoning]] = None
    day_type_affinities: Optional[list[str]] = None


class MealPlanSelect(BaseModel):
    date: str
    breakfast: Optional[MealPick] = None
    lunch: Optional[MealPick] = None
    dinner: Optional[MealPick] = None


def _resolve_recipe(db: Session, user_id: int, meal_type: str, pick: MealPick) -> models.Recipe:
    """Return the Recipe row for the pick, creating a pending one if fresh."""
    if pick.recipe_id is not None:
        recipe = db.query(models.Recipe).filter(models.Recipe.id == pick.recipe_id).first()
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
    portion_g = pick.portion_g if pick.portion_g is not None else recipe.serving_g
    calories = pick.calories if pick.calories is not None else recipe.calories
    protein_g = pick.protein_g if pick.protein_g is not None else recipe.protein_g
    carbs_g = pick.carbs_g if pick.carbs_g is not None else recipe.carbs_g
    fat_g = pick.fat_g if pick.fat_g is not None else recipe.fat_g

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
            continue
        db.add(autofill.build_diet_log_from_entry(entry))
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
