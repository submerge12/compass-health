from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

import models


def normalize_video_url(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("video_url must be an http or https URL")
    return value


def is_visible_to_user(recipe: models.Recipe, user_id: int) -> bool:
    return bool(recipe.is_approved) or recipe.submitted_by == user_id


def get_visible_recipe(db: Session, recipe_id: int, user_id: int) -> Optional[models.Recipe]:
    recipe = db.query(models.Recipe).filter(models.Recipe.id == recipe_id).first()
    if recipe is None or not is_visible_to_user(recipe, user_id):
        return None
    return recipe
