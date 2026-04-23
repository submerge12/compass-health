import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_

import models
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _recipe_to_dict(r: models.Recipe) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "ingredients": r.ingredients,
        "steps": r.steps,
        "video_url": r.video_url,
        "category": r.category,
        "is_builtin": r.is_builtin,
        "is_approved": r.is_approved,
        "submitted_by": r.submitted_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _extract_keywords(ingredients_text: str) -> list[str]:
    """Extract ingredient name keywords from free-form ingredient text."""
    keywords = []
    for line in ingredients_text.splitlines():
        line = line.strip().lstrip("•").lstrip("-").lstrip("·").strip()
        if not line:
            continue
        # Strip amounts: take text before first digit, colon, or Chinese colon
        word = line.split(":")[0].split("：")[0].split(" ")[0].strip()
        # Remove trailing numbers/units
        word = re.sub(r"[\d]+.*$", "", word).strip()
        if word and len(word) >= 1:
            keywords.append(word)
    return keywords


# ── Schemas ───────────────────────────────────────────────────────────────────

class RecipeCreate(BaseModel):
    name: str
    ingredients: Optional[str] = None
    steps: Optional[str] = None
    video_url: Optional[str] = None
    category: Optional[str] = None


class IngredientMatchRequest(BaseModel):
    ingredients: str


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
def list_recipes(
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.Recipe).filter(models.Recipe.is_approved == True)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                models.Recipe.name.ilike(like),
                models.Recipe.ingredients.ilike(like),
            )
        )
    recipes = query.order_by(models.Recipe.is_builtin.desc(), models.Recipe.name).all()
    return [_recipe_to_dict(r) for r in recipes]


@router.get("/{recipe_id}")
def get_recipe(
    recipe_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    r = db.query(models.Recipe).filter(models.Recipe.id == recipe_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return _recipe_to_dict(r)


@router.post("")
def create_recipe(
    body: RecipeCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    recipe = models.Recipe(
        name=body.name,
        ingredients=body.ingredients,
        steps=body.steps,
        video_url=body.video_url,
        category=body.category,
        is_builtin=False,
        submitted_by=current_user.id,
        is_approved=True,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return _recipe_to_dict(recipe)


@router.post("/match")
def match_recipes(
    body: IngredientMatchRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Search the recipe DB for dishes that use the supplied ingredients.
    If nothing is found, log a MissingRecipeReport and tell the client.
    """
    text = body.ingredients.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Ingredients cannot be empty")

    keywords = _extract_keywords(text)
    if not keywords:
        keywords = [text[:20]]  # fallback: use raw text

    # Score every approved recipe by how many keywords appear in its ingredients
    scored: list[tuple[int, models.Recipe]] = []
    for recipe in db.query(models.Recipe).filter(models.Recipe.is_approved == True).all():
        ing = (recipe.ingredients or "") + " " + (recipe.name or "")
        count = sum(1 for kw in keywords if kw in ing)
        if count > 0:
            scored.append((count, recipe))

    scored.sort(key=lambda x: x[0], reverse=True)
    matches = [r for _, r in scored[:5]]

    if matches:
        return {"found": True, "recipes": [_recipe_to_dict(r) for r in matches]}

    # Nothing found — record the report
    report = models.MissingRecipeReport(
        user_id=current_user.id,
        ingredients_query=text,
    )
    db.add(report)
    db.commit()

    return {
        "found": False,
        "message": "no_match",
        "report_id": report.id,
    }
