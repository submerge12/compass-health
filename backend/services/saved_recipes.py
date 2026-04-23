"""
User saved-recipe library operations.

Every dish the user selects for their meal plan gets auto-saved here so
the recipe (ingredients + cooking steps) stays reusable across weeks
without re-spending the LLM budget. Regular-tier users are capped at
SAVED_RECIPE_CAP; when they hit the cap they must delete an old recipe
before a new one can be saved.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

import models


SAVED_RECIPE_CAP = 20
REGULAR_TIERS = frozenset({"free", "normal"})


class SavedRecipeCapReached(Exception):
    """Raised when the user already has SAVED_RECIPE_CAP recipes saved."""


def cap_for_user(user: models.User) -> int | None:
    """Return the library cap for this user, or None for unlimited tiers."""
    level = user.membership.level if user.membership else "free"
    return SAVED_RECIPE_CAP if level in REGULAR_TIERS else None


def count_for_user(db: Session, user_id: int) -> int:
    return (
        db.query(models.UserSavedRecipe)
        .filter(models.UserSavedRecipe.user_id == user_id)
        .count()
    )


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
        .filter(
            models.UserSavedRecipe.user_id == user_id,
            models.UserSavedRecipe.recipe_id == recipe_id,
        )
        .first()
    )
    if not row:
        return False
    db.delete(row)
    return True


def list_for_user(db: Session, user_id: int) -> list[models.UserSavedRecipe]:
    return (
        db.query(models.UserSavedRecipe)
        .filter(models.UserSavedRecipe.user_id == user_id)
        .order_by(models.UserSavedRecipe.saved_at.desc())
        .all()
    )
