"""
Fixed-meals HTTP surface (spec-v1).

A "fixed meal" is a slot the user wants auto-filled every week — e.g.
"oatmeal with milk for breakfast, every day" or "salmon for dinner, every
Wednesday". These are evaluated before the recipe matcher: their nutrition
is subtracted from the daily target, so empty slots are planned around
them.

Endpoints:

  GET    /api/fixed-meals            List the user's fixed meals
  POST   /api/fixed-meals            Create one
  PATCH  /api/fixed-meals/{id}       Update (partial; re-scales macros)
  DELETE /api/fixed-meals/{id}       Remove one

Macros are cached on write (scaled from `Recipe` × `portion_g / serving_g`)
so the per-day deduction in `planning_context.build_context` doesn't have
to re-compute them on every request.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from services import recipe_access


router = APIRouter(prefix="/api/fixed-meals", tags=["fixed-meals"])
log = logging.getLogger("compass.app")


VALID_MEAL_TYPES = {"breakfast", "lunch", "dinner", "snack"}


# ── Request / response models ────────────────────────────────────────────────

class FixedMealCreate(BaseModel):
    meal_type: str                              # breakfast/lunch/dinner/snack
    weekday: Optional[int] = None               # 0=Mon..6=Sun, None=every day
    recipe_id: Optional[int] = None
    custom_name: Optional[str] = None
    portion_g: Optional[float] = Field(default=None, gt=0)


class FixedMealUpdate(BaseModel):
    # All fields optional — PATCH semantics. `None` sent explicitly for
    # `weekday` means "every day"; to leave `weekday` unchanged, omit it.
    meal_type:   Optional[str]   = None
    weekday:     Optional[int]   = Field(default=None, ge=0, le=6)
    recipe_id:   Optional[int]   = None
    custom_name: Optional[str]   = None
    portion_g:   Optional[float] = Field(default=None, gt=0)


def _serialize(row: models.UserFixedMeal) -> dict:
    return {
        "id":           row.id,
        "weekday":      row.weekday,
        "meal_type":    row.meal_type,
        "recipe_id":    row.recipe_id,
        "recipe_name":  row.recipe.name if row.recipe_id and row.recipe else None,
        "custom_name":  row.custom_name,
        "portion_g":    row.portion_g,
        "calories":     row.calories,
        "protein_g":    row.protein_g,
        "carbs_g":      row.carbs_g,
        "fat_g":        row.fat_g,
        "created_at":   row.created_at.isoformat() if row.created_at else None,
        "updated_at":   row.updated_at.isoformat() if row.updated_at else None,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _require_meal_type(meal_type: str) -> None:
    if meal_type not in VALID_MEAL_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"meal_type must be one of {sorted(VALID_MEAL_TYPES)}",
        )


def _require_weekday(weekday: Optional[int]) -> None:
    if weekday is None:
        return
    if not (0 <= weekday <= 6):
        raise HTTPException(
            status_code=422,
            detail="weekday must be between 0 (Monday) and 6 (Sunday), or null for every day",
        )


def _load_recipe(db: Session, recipe_id: int, user_id: int) -> models.Recipe:
    recipe = recipe_access.get_visible_recipe(db, recipe_id, user_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail=f"Recipe {recipe_id} not found")
    return recipe


def _scaled_macros(
    recipe: Optional[models.Recipe], portion_g: Optional[float]
) -> dict:
    """Return `{calories, protein_g, carbs_g, fat_g}` for the fixed meal.

    If a recipe is linked, scale its per-serving macros by
    `portion_g / serving_g`; fall back to 1.0 if either is missing.
    With no recipe, the fixed meal is "placeholder" — macros are zeroed so
    the daily-target deduction doesn't subtract ghost calories. Frontend
    should encourage the user to link a recipe.
    """
    if recipe is None:
        return {"calories": 0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}

    serving = recipe.serving_g
    multiplier = (portion_g / serving) if (portion_g and serving) else 1.0
    return {
        "calories":  int(round((recipe.calories  or 0) * multiplier)),
        "protein_g": round((recipe.protein_g or 0.0) * multiplier, 1),
        "carbs_g":   round((recipe.carbs_g   or 0.0) * multiplier, 1),
        "fat_g":     round((recipe.fat_g     or 0.0) * multiplier, 1),
    }


def _get_owned(
    db: Session, user_id: int, fixed_meal_id: int
) -> models.UserFixedMeal:
    row = (
        db.query(models.UserFixedMeal)
        .filter_by(id=fixed_meal_id, user_id=user_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Fixed meal not found")
    return row


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("")
def list_fixed_meals(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    rows = (
        db.query(models.UserFixedMeal)
        .filter_by(user_id=current_user.id)
        .order_by(
            # NULL weekday (every day) first, then Mon..Sun; ties by meal order
            models.UserFixedMeal.weekday.asc().nullsfirst(),
            models.UserFixedMeal.meal_type.asc(),
            models.UserFixedMeal.id.asc(),
        )
        .all()
    )
    return {"items": [_serialize(r) for r in rows]}


@router.post("")
def create_fixed_meal(
    body: FixedMealCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_meal_type(body.meal_type)
    _require_weekday(body.weekday)

    if body.recipe_id is None and not (body.custom_name and body.custom_name.strip()):
        raise HTTPException(
            status_code=422,
            detail="Provide recipe_id or custom_name (recipe_id is preferred; "
                   "custom_name alone won't appear in shopping lists).",
        )

    recipe = _load_recipe(db, body.recipe_id, current_user.id) if body.recipe_id else None
    macros = _scaled_macros(recipe, body.portion_g)

    row = models.UserFixedMeal(
        user_id=current_user.id,
        weekday=body.weekday,
        meal_type=body.meal_type,
        recipe_id=body.recipe_id,
        custom_name=body.custom_name.strip() if body.custom_name else None,
        portion_g=body.portion_g,
        **macros,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A fixed meal already exists for this weekday + meal_type. "
                   "Edit that one instead, or pick a different slot.",
        )
    db.refresh(row)
    log.info(
        "fixed meal created",
        extra={
            "event": "fixed_meal_created",
            "domain": "fixed_meals",
            "fixed_meal_id": row.id,
            "meal_type": row.meal_type,
            "weekday": row.weekday,
            "has_recipe": row.recipe_id is not None,
            "has_custom_name": bool(row.custom_name),
            "portion_g": row.portion_g,
        },
    )
    return _serialize(row)


@router.patch("/{fixed_meal_id}")
def update_fixed_meal(
    fixed_meal_id: int,
    body: FixedMealUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    row = _get_owned(db, current_user.id, fixed_meal_id)
    payload = body.model_dump(exclude_unset=True)

    if "meal_type" in payload:
        _require_meal_type(payload["meal_type"])
        row.meal_type = payload["meal_type"]
    if "weekday" in payload:
        _require_weekday(payload["weekday"])
        row.weekday = payload["weekday"]
    if "custom_name" in payload:
        row.custom_name = (
            payload["custom_name"].strip() if payload["custom_name"] else None
        )

    # Recipe / portion changes force macro recalculation. We also recalc
    # when only one of them changes — portion without recipe is still a
    # meaningful scaling factor if a recipe was already linked.
    recipe_changed  = "recipe_id" in payload
    portion_changed = "portion_g" in payload

    if recipe_changed:
        new_recipe_id = payload["recipe_id"]
        row.recipe_id = new_recipe_id
        recipe = _load_recipe(db, new_recipe_id, current_user.id) if new_recipe_id else None
    elif portion_changed and row.recipe_id:
        recipe = _load_recipe(db, row.recipe_id, current_user.id)
    else:
        recipe = None

    if portion_changed:
        row.portion_g = payload["portion_g"]

    # If either the recipe or portion was touched, re-scale macros.
    if recipe_changed or portion_changed:
        if recipe is None and row.recipe_id:
            # Recipe wasn't in this payload but is still linked — load it
            # so the new portion scales correctly.
            recipe = _load_recipe(db, row.recipe_id, current_user.id)
        macros = _scaled_macros(recipe, row.portion_g)
        row.calories  = macros["calories"]
        row.protein_g = macros["protein_g"]
        row.carbs_g   = macros["carbs_g"]
        row.fat_g     = macros["fat_g"]

    # The create path already validates "recipe_id or custom_name"; enforce
    # it here too so updates can't erase both.
    if row.recipe_id is None and not (row.custom_name and row.custom_name.strip()):
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail="Fixed meal must keep either recipe_id or custom_name.",
        )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This change would collide with another fixed meal on the "
                   "same weekday + meal_type.",
        )
    db.refresh(row)
    log.info(
        "fixed meal updated",
        extra={
            "event": "fixed_meal_updated",
            "domain": "fixed_meals",
            "fixed_meal_id": row.id,
            "meal_type": row.meal_type,
            "weekday": row.weekday,
            "changed_fields": sorted(payload.keys()),
            "has_recipe": row.recipe_id is not None,
            "has_custom_name": bool(row.custom_name),
            "portion_g": row.portion_g,
        },
    )
    return _serialize(row)


@router.delete("/{fixed_meal_id}")
def delete_fixed_meal(
    fixed_meal_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    row = _get_owned(db, current_user.id, fixed_meal_id)
    log.info(
        "fixed meal deleted",
        extra={
            "event": "fixed_meal_deleted",
            "domain": "fixed_meals",
            "fixed_meal_id": row.id,
            "meal_type": row.meal_type,
            "weekday": row.weekday,
            "has_recipe": row.recipe_id is not None,
            "has_custom_name": bool(row.custom_name),
        },
    )
    db.delete(row)
    db.commit()
    return {"deleted": fixed_meal_id}
