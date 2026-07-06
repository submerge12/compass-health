import json
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import or_

import models
from auth import get_current_user
from database import get_db
from services import recipe_access, recipe_assessor

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_json(raw: Optional[str], fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback


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
        "community_status": r.community_status,
        "low_fat_score": r.low_fat_score,
        "low_fat_grade": r.low_fat_grade,
        "low_fat_assessment": _safe_json(r.low_fat_assessment_json, None),
        "low_fat_assessed_at": r.low_fat_assessed_at.isoformat() if r.low_fat_assessed_at else None,
        "community_rating_avg": r.community_rating_avg,
        "community_rating_count": r.community_rating_count or 0,
    }


def _rating_to_dict(row: Optional[models.RecipeTrialRating]) -> Optional[dict]:
    if not row:
        return None
    return {
        "rating": row.rating,
        "satiety_score": row.satiety_score,
        "difficulty_score": row.difficulty_score,
        "would_cook_again": row.would_cook_again,
        "feedback": row.feedback,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _community_recipe_to_dict(
    r: models.Recipe,
    *,
    my_rating: Optional[models.RecipeTrialRating] = None,
) -> dict:
    data = _recipe_to_dict(r)
    data["my_trial_rating"] = _rating_to_dict(my_rating)
    return data


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
    name: str = Field(..., min_length=1, max_length=120)
    ingredients: Optional[str] = Field(default=None, max_length=4000)
    steps: Optional[str] = Field(default=None, max_length=4000)
    video_url: Optional[str] = Field(default=None, max_length=500)
    category: Optional[str] = Field(default=None, max_length=80)


class IngredientMatchRequest(BaseModel):
    ingredients: str = Field(..., min_length=1, max_length=4000)


class CommunityRecipeInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    ingredients: str = Field(..., min_length=1, max_length=5000)
    steps: str = Field(..., min_length=1, max_length=5000)
    servings: int = Field(default=1, ge=1, le=20)
    video_url: Optional[str] = Field(default=None, max_length=500)
    category: Optional[str] = Field(default=None, max_length=80)


class TrialRatingInput(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    satiety_score: Optional[int] = Field(default=None, ge=1, le=5)
    difficulty_score: Optional[int] = Field(default=None, ge=1, le=5)
    would_cook_again: Optional[bool] = None
    feedback: Optional[str] = Field(default=None, max_length=1000)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
def list_recipes(
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.Recipe).filter(
        or_(
            models.Recipe.is_approved == True,  # noqa: E712
            models.Recipe.submitted_by == current_user.id,
        )
    )
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


@router.get("/community")
def list_community_recipes(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    recipes = (
        db.query(models.Recipe)
        .filter(
            models.Recipe.community_status == "published",
            models.Recipe.is_approved == True,  # noqa: E712
        )
        .order_by(
            models.Recipe.community_rating_count.desc(),
            models.Recipe.low_fat_score.desc(),
            models.Recipe.created_at.desc(),
        )
        .all()
    )
    ratings = {
        row.recipe_id: row
        for row in db.query(models.RecipeTrialRating)
        .filter(
            models.RecipeTrialRating.user_id == current_user.id,
            models.RecipeTrialRating.recipe_id.in_([r.id for r in recipes] or [-1]),
        )
        .all()
    }
    return [_community_recipe_to_dict(r, my_rating=ratings.get(r.id)) for r in recipes]


@router.post("/community/analyze")
def analyze_community_recipe(
    body: CommunityRecipeInput,
    current_user: models.User = Depends(get_current_user),
):
    del current_user
    return recipe_assessor.assess_low_fat_recipe(
        name=body.name,
        ingredients=body.ingredients,
        steps=body.steps,
        servings=body.servings,
    )


@router.post("/community")
def create_community_recipe(
    body: CommunityRecipeInput,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    try:
        video_url = recipe_access.normalize_video_url(body.video_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    assessment = recipe_assessor.assess_low_fat_recipe(
        name=body.name,
        ingredients=body.ingredients,
        steps=body.steps,
        servings=body.servings,
    )
    per = assessment.get("estimated_nutrition_per_serving") or {}
    matched = assessment.get("matched_ingredients") or []
    total_known_grams = sum(float(item.get("grams") or 0) for item in matched)
    recipe = models.Recipe(
        name=body.name,
        ingredients=body.ingredients,
        steps=body.steps,
        video_url=video_url,
        category=body.category or "community_low_fat",
        is_builtin=False,
        submitted_by=current_user.id,
        is_approved=False,
        meal_types="lunch,dinner",
        calories=int(round(per.get("kcal") or 0)) or None,
        protein_g=per.get("protein_g") if per.get("coverage") == "estimated" else None,
        carbs_g=per.get("carbs_g") if per.get("coverage") == "estimated" else None,
        fat_g=per.get("fat_g") if per.get("coverage") == "estimated" else None,
        serving_g=round(total_known_grams / max(1, body.servings), 1) if total_known_grams else None,
        ingredient_slugs=json.dumps(
            sorted({item["slug"] for item in matched if item.get("slug")}),
            ensure_ascii=False,
        ) if matched else None,
        community_status="pending",
        low_fat_score=assessment["score"],
        low_fat_grade=assessment["grade"],
        low_fat_assessment_json=json.dumps(assessment, ensure_ascii=False),
        low_fat_assessed_at=models.utcnow(),
        community_rating_count=0,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return _community_recipe_to_dict(recipe)


@router.post("/community/{recipe_id}/trial-rating")
def rate_community_recipe_after_trial(
    recipe_id: int,
    body: TrialRatingInput,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    recipe = (
        db.query(models.Recipe)
        .filter(
            models.Recipe.id == recipe_id,
            models.Recipe.community_status == "published",
            models.Recipe.is_approved == True,  # noqa: E712
        )
        .first()
    )
    if not recipe:
        raise HTTPException(status_code=404, detail="Community recipe not found")

    rating = (
        db.query(models.RecipeTrialRating)
        .filter(
            models.RecipeTrialRating.recipe_id == recipe_id,
            models.RecipeTrialRating.user_id == current_user.id,
        )
        .first()
    )
    if not rating:
        rating = models.RecipeTrialRating(recipe_id=recipe_id, user_id=current_user.id)
        db.add(rating)

    rating.rating = body.rating
    rating.satiety_score = body.satiety_score
    rating.difficulty_score = body.difficulty_score
    rating.would_cook_again = body.would_cook_again
    rating.feedback = body.feedback

    db.flush()
    rows = db.query(models.RecipeTrialRating.rating).filter(
        models.RecipeTrialRating.recipe_id == recipe_id
    ).all()
    values = [int(row[0]) for row in rows]
    recipe.community_rating_count = len(values)
    recipe.community_rating_avg = round(sum(values) / len(values), 2) if values else None
    db.commit()
    db.refresh(recipe)
    db.refresh(rating)
    return _community_recipe_to_dict(recipe, my_rating=rating)


@router.get("/{recipe_id}")
def get_recipe(
    recipe_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    r = recipe_access.get_visible_recipe(db, recipe_id, current_user.id)
    if not r:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return _recipe_to_dict(r)


@router.post("")
def create_recipe(
    body: RecipeCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    try:
        video_url = recipe_access.normalize_video_url(body.video_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    recipe = models.Recipe(
        name=body.name,
        ingredients=body.ingredients,
        steps=body.steps,
        video_url=video_url,
        category=body.category,
        is_builtin=False,
        submitted_by=current_user.id,
        is_approved=False,
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
