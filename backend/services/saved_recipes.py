"""
User saved-recipe library operations.

Every dish the user selects for their meal plan gets auto-saved here so
the recipe (ingredients + cooking steps) stays reusable across weeks
without re-spending the LLM budget. Regular-tier users are capped at
SAVED_RECIPE_CAP; when they hit the cap they must delete an old recipe
before a new one can be saved.
"""
from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload

import models


SAVED_RECIPE_CAP = 20
REGULAR_TIERS = frozenset({"free", "normal"})


class SavedRecipeCapReached(Exception):
    """Raised when the user already has SAVED_RECIPE_CAP recipes saved."""


def _normalise_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().casefold())


def _normalise_ingredients_json(value: str | None) -> tuple[tuple[str, float | None], ...] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, list):
        return None

    ingredients: list[tuple[str, float | None]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        slug = _normalise_text(str(item.get("slug") or ""))
        if not slug:
            continue
        grams_raw = item.get("grams")
        grams: float | None
        if grams_raw is None:
            grams = None
        else:
            try:
                grams = round(float(grams_raw), 1)
            except (TypeError, ValueError):
                grams = None
        ingredients.append((slug, grams))
    return tuple(sorted(ingredients)) or None


def _recipe_signature(recipe: models.Recipe) -> tuple[str, tuple[str, object]]:
    """Stable dish identity for saved-library de-duplication.

    Recipe ids can differ when the same generated dish is selected more than
    once. The saved library should behave like a dish list, so we compare the
    visible dish name plus its ingredient set/text rather than the row id.
    """
    name = _normalise_text(recipe.name)
    ingredients_json = _normalise_ingredients_json(recipe.ingredients_json)
    if ingredients_json is not None:
        return name, ("ingredients_json", ingredients_json)
    return name, ("ingredients", _normalise_text(recipe.ingredients))


def _row_signature(row: models.UserSavedRecipe) -> tuple[str, object]:
    if row.recipe is None:
        return "recipe_id", row.recipe_id
    return "recipe", _recipe_signature(row.recipe)


def _rows_for_user(db: Session, user_id: int) -> list[models.UserSavedRecipe]:
    return (
        db.query(models.UserSavedRecipe)
        .options(joinedload(models.UserSavedRecipe.recipe))
        .filter(models.UserSavedRecipe.user_id == user_id)
        .order_by(
            models.UserSavedRecipe.saved_at.desc(),
            models.UserSavedRecipe.id.desc(),
        )
        .all()
    )


def _dedupe_rows(rows: list[models.UserSavedRecipe]) -> list[models.UserSavedRecipe]:
    seen: set[tuple[str, object]] = set()
    unique: list[models.UserSavedRecipe] = []
    for row in rows:
        signature = _row_signature(row)
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(row)
    return unique


def cap_for_user(user: models.User) -> int | None:
    """Return the library cap for this user, or None for unlimited tiers."""
    level = user.membership.level if user.membership else "free"
    return SAVED_RECIPE_CAP if level in REGULAR_TIERS else None


def count_for_user(db: Session, user_id: int) -> int:
    return len(list_for_user(db, user_id))


def is_saved(db: Session, user_id: int, recipe_id: int) -> bool:
    return (
        db.query(models.UserSavedRecipe)
        .filter(
            models.UserSavedRecipe.user_id == user_id,
            models.UserSavedRecipe.recipe_id == recipe_id,
        )
        .first()
        is not None
    )


def save_on_select(db: Session, user: models.User, recipe_id: int) -> models.UserSavedRecipe:
    """Idempotently add a recipe to the user's library, enforcing the cap.

    Caller is responsible for commit. Raises SavedRecipeCapReached if the
    user already has the maximum number of saved recipes and this recipe is
    not already among them.
    """
    existing = (
        db.query(models.UserSavedRecipe)
        .filter(
            models.UserSavedRecipe.user_id == user.id,
            models.UserSavedRecipe.recipe_id == recipe_id,
        )
        .first()
    )
    if existing:
        return existing

    recipe = db.query(models.Recipe).filter(models.Recipe.id == recipe_id).first()
    if recipe is not None:
        signature = _recipe_signature(recipe)
        for row in _rows_for_user(db, user.id):
            if row.recipe is not None and _recipe_signature(row.recipe) == signature:
                return row

    cap = cap_for_user(user)
    if cap is not None and count_for_user(db, user.id) >= cap:
        raise SavedRecipeCapReached()

    row = models.UserSavedRecipe(user_id=user.id, recipe_id=recipe_id)
    db.add(row)
    db.flush()
    return row


def delete_for_user(db: Session, user_id: int, recipe_id: int) -> bool:
    """Remove the recipe from the user's library. Returns True if deleted."""
    row = (
        db.query(models.UserSavedRecipe)
        .options(joinedload(models.UserSavedRecipe.recipe))
        .filter(
            models.UserSavedRecipe.user_id == user_id,
            models.UserSavedRecipe.recipe_id == recipe_id,
        )
        .first()
    )
    if not row:
        return False
    signature = _row_signature(row)
    for saved in _rows_for_user(db, user_id):
        if _row_signature(saved) == signature:
            db.delete(saved)
    return True


def list_for_user(db: Session, user_id: int) -> list[models.UserSavedRecipe]:
    return _dedupe_rows(_rows_for_user(db, user_id))
