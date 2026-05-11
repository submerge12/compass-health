import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from routers.preferences_routes import CATEGORY_ITEMS
from services import audit, calorie, engagement, food_library as FL, llm_quota, local_dates, nutrition_audit, recipe_access

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Auth helper ───────────────────────────────────────────────────────────────

def require_admin(
    current_user: models.User = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


# ── Schemas ───────────────────────────────────────────────────────────────────

class RecipeUpsert(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    ingredients: Optional[str] = Field(default=None, max_length=4000)
    steps: Optional[str] = Field(default=None, max_length=4000)
    video_url: Optional[str] = Field(default=None, max_length=500)
    category: Optional[str] = Field(default=None, max_length=80)
    meal_types: Optional[str] = Field(default=None, max_length=80)   # CSV: "breakfast,lunch,dinner"
    calories: Optional[int] = Field(default=None, ge=0, le=5000)
    protein_g: Optional[float] = Field(default=None, ge=0, le=500)
    carbs_g: Optional[float] = Field(default=None, ge=0, le=1000)
    fat_g: Optional[float] = Field(default=None, ge=0, le=500)
    serving_g: Optional[float] = Field(default=None, gt=0, le=3000)


class ReportStatusUpdate(BaseModel):
    status: str = Field(..., min_length=1, max_length=20)   # pending / reviewed


class UserPatch(BaseModel):
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None
    membership_level: Optional[str] = Field(default=None, max_length=20)   # free / normal / pro / pro_max


class AdminPreferenceItem(BaseModel):
    category: str = Field(..., min_length=1, max_length=50)
    item_key: str = Field(..., min_length=1, max_length=80)


class AdminPreferenceUpdate(BaseModel):
    items: list[AdminPreferenceItem] = Field(default_factory=list, max_length=300)
    replace: bool = True
    reason: Optional[str] = Field(default=None, max_length=500)


class AdminQuotaReset(BaseModel):
    kind: Optional[str] = Field(default=None, max_length=80)
    reason: Optional[str] = Field(default=None, max_length=500)


# ── Missing-recipe reports ────────────────────────────────────────────────────

@router.get("/missing-recipes")
def list_missing_recipes(
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    reports = (
        db.query(models.MissingRecipeReport)
        .order_by(models.MissingRecipeReport.reported_at.desc())
        .all()
    )
    result = []
    for r in reports:
        user = db.query(models.User).filter(models.User.id == r.user_id).first()
        result.append({
            "id": r.id,
            "user_id": r.user_id,
            "username": user.username if user else "Unknown",
            "ingredients_query": r.ingredients_query,
            "suggested_name": r.suggested_name,
            "status": r.status,
            "reported_at": r.reported_at.isoformat() if r.reported_at else None,
        })
    return result


@router.put("/missing-recipes/{report_id}")
def update_report(
    report_id: int,
    body: ReportStatusUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    report = db.query(models.MissingRecipeReport).filter(
        models.MissingRecipeReport.id == report_id
    ).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if body.status not in {"pending", "reviewed"}:
        raise HTTPException(status_code=422, detail="Invalid report status")
    status_before = report.status
    report.status = body.status
    audit.record(
        db, admin, "report.update",
        target_type="report", target_id=report.id,
        details={"status_before": status_before, "status_after": body.status},
    )
    db.commit()
    return {"message": "Updated"}


# ── Recipe management ─────────────────────────────────────────────────────────

@router.get("/recipes")
def admin_list_recipes(
    pending: bool = False,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    q = db.query(models.Recipe)
    if pending:
        q = q.filter(models.Recipe.is_approved == False)  # noqa: E712
    recipes = q.order_by(models.Recipe.created_at.desc()).all()
    return [_recipe_dict(r) for r in recipes]


@router.post("/recipes")
def admin_create_recipe(
    body: RecipeUpsert,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
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
        meal_types=body.meal_types,
        calories=body.calories,
        protein_g=body.protein_g,
        carbs_g=body.carbs_g,
        fat_g=body.fat_g,
        serving_g=body.serving_g,
        is_builtin=False,
        submitted_by=admin.id,
        is_approved=True,
    )
    db.add(recipe)
    db.flush()
    audit.record(
        db, admin, "recipe.create",
        target_type="recipe", target_id=recipe.id,
        details={"name": recipe.name, "category": recipe.category},
    )
    db.commit()
    db.refresh(recipe)
    return _recipe_dict(recipe)


@router.put("/recipes/{recipe_id}")
def admin_update_recipe(
    recipe_id: int,
    body: RecipeUpsert,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    recipe = db.query(models.Recipe).filter(models.Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    changed: list[str] = []
    try:
        video_url = recipe_access.normalize_video_url(body.video_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if recipe.name != body.name:
        changed.append("name")
    recipe.name = body.name
    if recipe.video_url != video_url:
        recipe.video_url = video_url
        changed.append("video_url")
    for field in (
        "ingredients", "steps", "category",
        "meal_types", "calories", "protein_g", "carbs_g", "fat_g", "serving_g",
    ):
        val = getattr(body, field)
        if val is not None and getattr(recipe, field) != val:
            setattr(recipe, field, val)
            changed.append(field)
    audit.record(
        db, admin, "recipe.update",
        target_type="recipe", target_id=recipe.id,
        details={"name": recipe.name, "changed": changed},
    )
    db.commit()
    db.refresh(recipe)
    return _recipe_dict(recipe)


@router.put("/recipes/{recipe_id}/approve")
def admin_approve_recipe(
    recipe_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    recipe = db.query(models.Recipe).filter(models.Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    recipe.is_approved = True
    audit.record(
        db, admin, "recipe.approve",
        target_type="recipe", target_id=recipe.id,
        details={"name": recipe.name},
    )
    db.commit()
    db.refresh(recipe)
    return _recipe_dict(recipe)


@router.delete("/recipes/{recipe_id}")
def admin_delete_recipe(
    recipe_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    recipe = db.query(models.Recipe).filter(models.Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    reference_count = (
        db.query(models.MealPlanEntry).filter(models.MealPlanEntry.recipe_id == recipe_id).count()
        + db.query(models.UserFixedMeal).filter(models.UserFixedMeal.recipe_id == recipe_id).count()
        + db.query(models.UserSavedRecipe).filter(models.UserSavedRecipe.recipe_id == recipe_id).count()
    )
    if reference_count:
        raise HTTPException(
            status_code=409,
            detail="Recipe is still referenced by meal plans, fixed meals, or saved recipes.",
        )
    audit.record(
        db, admin, "recipe.delete",
        target_type="recipe", target_id=recipe.id,
        details={"name": recipe.name, "category": recipe.category},
    )
    db.delete(recipe)
    db.commit()
    return {"message": "Deleted"}


# ── System stats ──────────────────────────────────────────────────────────────

@router.get("/stats")
def admin_stats(
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    total_users = db.query(models.User).count()
    active_users = db.query(models.User).filter(models.User.is_active == True).count()  # noqa: E712
    admin_users = db.query(models.User).filter(models.User.is_admin == True).count()    # noqa: E712
    total_recipes = db.query(models.Recipe).count()
    builtin_recipes = db.query(models.Recipe).filter(models.Recipe.is_builtin == True).count()  # noqa: E712
    pending_reports = (
        db.query(models.MissingRecipeReport)
        .filter(models.MissingRecipeReport.status == "pending")
        .count()
    )
    total_reports = db.query(models.MissingRecipeReport).count()
    return {
        "total_users": total_users,
        "active_users": active_users,
        "admin_users": admin_users,
        "total_recipes": total_recipes,
        "builtin_recipes": builtin_recipes,
        "user_submitted_recipes": total_recipes - builtin_recipes,
        "pending_reports": pending_reports,
        "total_reports": total_reports,
    }


# ── User management ───────────────────────────────────────────────────────────

VALID_MEMBERSHIP_LEVELS = {"free", "normal", "pro", "pro_max"}


@router.get("/users")
def admin_list_users(
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    users = db.query(models.User).order_by(models.User.created_at.desc()).all()
    return [_user_dict(u) for u in users]


@router.patch("/users/{user_id}")
def admin_update_user(
    user_id: int,
    body: UserPatch,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Guard: don't allow admin to strip their own admin or disable themselves
    # (prevents locking out the last admin via the UI)
    if user.id == admin.id:
        if body.is_admin is False or body.is_active is False:
            raise HTTPException(
                status_code=400,
                detail="You cannot revoke admin or deactivate your own account",
            )

    diff: dict[str, dict] = {}

    if body.is_admin is not None and user.is_admin != body.is_admin:
        diff["is_admin"] = {"before": bool(user.is_admin), "after": bool(body.is_admin)}
        user.is_admin = body.is_admin
    if body.is_active is not None and user.is_active != body.is_active:
        diff["is_active"] = {"before": bool(user.is_active), "after": bool(body.is_active)}
        user.is_active = body.is_active
    if body.membership_level is not None:
        if body.membership_level not in VALID_MEMBERSHIP_LEVELS:
            raise HTTPException(status_code=422, detail="Invalid membership level")
        mem = user.membership
        before_level = mem.level if mem else None
        if before_level != body.membership_level:
            diff["membership_level"] = {"before": before_level, "after": body.membership_level}
        if not mem:
            mem = models.Membership(user_id=user.id, level=body.membership_level)
            db.add(mem)
        else:
            mem.level = body.membership_level

    if diff:
        audit.record(
            db, admin, "user.update",
            target_type="user", target_id=user.id,
            details={"username": user.username, "diff": diff},
        )
    db.commit()
    db.refresh(user)
    return _user_dict(user)


@router.delete("/users/{user_id}")
def admin_delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Clean up dependent rows that have no cascade configured
    db.query(models.RefreshToken).filter(models.RefreshToken.user_id == user_id).delete()
    db.query(models.WaterLog).filter(models.WaterLog.user_id == user_id).delete()
    db.query(models.ExerciseLog).filter(models.ExerciseLog.user_id == user_id).delete()
    db.query(models.DietLog).filter(models.DietLog.user_id == user_id).delete()
    db.query(models.PhysicalCondition).filter(models.PhysicalCondition.user_id == user_id).delete()
    db.query(models.CheckIn).filter(models.CheckIn.user_id == user_id).delete()
    db.query(models.LLMCallLog).filter(models.LLMCallLog.user_id == user_id).delete()
    db.query(models.DailyActivityPlan).filter(models.DailyActivityPlan.user_id == user_id).delete()
    db.query(models.MealPlanEntry).filter(models.MealPlanEntry.user_id == user_id).delete()
    db.query(models.UserSavedRecipe).filter(models.UserSavedRecipe.user_id == user_id).delete()
    db.query(models.UserFixedMeal).filter(models.UserFixedMeal.user_id == user_id).delete()
    db.query(models.DailyMealPlanConfirmation).filter(
        models.DailyMealPlanConfirmation.user_id == user_id
    ).delete()
    db.query(models.MissingRecipeReport).filter(
        models.MissingRecipeReport.user_id == user_id
    ).delete()
    db.query(models.FoodPreference).filter(models.FoodPreference.user_id == user_id).delete()
    db.query(models.Recipe).filter(models.Recipe.submitted_by == user_id).update(
        {"submitted_by": None},
        synchronize_session=False,
    )
    if user.bmr_profile:
        db.delete(user.bmr_profile)
    if user.membership:
        db.delete(user.membership)
    if user.settings:
        db.delete(user.settings)

    audit.record(
        db, admin, "user.delete",
        target_type="user", target_id=user.id,
        details={"username": user.username, "email": user.email},
    )
    db.delete(user)
    db.commit()
    return {"message": "Deleted"}


# ── User detail (read-only profile drawer) ───────────────────────────────────

@router.get("/users/{user_id}/detail")
def admin_get_user_detail(
    user_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    """Full read-only profile for one user.

    Bundles everything the admin might want to see about a user without
    editing: BMR profile, today's activity / calorie target, settings,
    food-preference counts, 7-day log activity, check-in streak.
    """
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    now = local_dates.app_now()
    today = now.strftime("%Y-%m-%d")
    cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    # BMR + today's targets (best-effort; returns has_bmr_profile=False if missing).
    targets = calorie.build_daily_targets(db, user)

    profile = user.bmr_profile
    bmr_block = None
    if profile:
        bmr_block = {
            "age": profile.age,
            "gender": profile.gender,
            "height_cm": profile.height_cm,
            "weight_kg": profile.weight_kg,
            "goal": calorie.normalize_goal(profile.goal),
            "bmr_value": profile.bmr_value,
            "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        }

    settings = user.settings
    settings_block = {
        "daily_water_goal_ml": settings.daily_water_goal_ml if settings else 2000,
        "water_reminder_min": settings.water_reminder_min if settings else 60,
        "language": settings.language if settings else (user.language or "zh"),
    }

    # Food-preference breakdown by category
    pref_rows = (
        db.query(models.FoodPreference)
        .filter(models.FoodPreference.user_id == user.id)
        .all()
    )
    prefs_by_category: dict[str, int] = {}
    for r in pref_rows:
        prefs_by_category[r.category] = prefs_by_category.get(r.category, 0) + 1

    # 7-day activity rollup
    def _count(model) -> int:
        return (
            db.query(model)
            .filter(model.user_id == user.id, model.date >= cutoff)
            .count()
        )
    activity_7d = {
        "water_logs": _count(models.WaterLog),
        "exercise_logs": _count(models.ExerciseLog),
        "diet_logs": _count(models.DietLog),
        "condition_logs": _count(models.PhysicalCondition),
    }

    streak = engagement.calc_checkin_streak(db, user.id)
    last_condition = (
        db.query(models.PhysicalCondition)
        .filter(models.PhysicalCondition.user_id == user.id)
        .order_by(models.PhysicalCondition.date.desc())
        .first()
    )

    return {
        "summary": _user_dict(user),
        "bmr_profile": bmr_block,
        "target_weight_kg": user.target_weight_kg,
        "today": {
            "date": today,
            "activity_level": targets.get("activity_level"),
            "activity_is_default": targets.get("activity_is_default"),
            "calorie_target": targets.get("calorie_target"),
            "protein_g": targets.get("protein_g"),
            "carbs_g": targets.get("carbs_g"),
            "fat_g": targets.get("fat_g"),
            "tdee": targets.get("tdee"),
        } if profile else None,
        "settings": settings_block,
        "food_preferences": {
            "total": len(pref_rows),
            "by_category": prefs_by_category,
        },
        "activity_7d": activity_7d,
        "checkin": {
            "streak": streak,
            "checked_in_today": engagement.is_checked_in_today(db, user.id),
        },
        "last_condition": {
            "date": last_condition.date,
            "weight_kg": last_condition.weight_kg,
        } if last_condition else None,
    }


# ── Audit log ─────────────────────────────────────────────────────────────────

@router.get("/users/{user_id}/preferences")
def admin_get_user_preferences(
    user_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    user = _get_user_or_404(db, user_id)
    return {
        "user": _user_dict(user),
        "known": CATEGORY_ITEMS,
        "known_labels": _known_preference_labels(),
        "categories": _group_food_preferences(db, user.id),
        "nutrition_audit": nutrition_audit.run_audit(db, user),
    }


@router.put("/users/{user_id}/preferences")
def admin_update_user_preferences(
    user_id: int,
    body: AdminPreferenceUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    user = _get_user_or_404(db, user_id)
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="Admin preference changes require a reason")

    before = _group_food_preferences(db, user.id)
    to_insert = _validate_preference_items(body.items)

    if body.replace:
        db.query(models.FoodPreference).filter(
            models.FoodPreference.user_id == user.id
        ).delete(synchronize_session=False)

    existing = {
        (r.category, r.item_key)
        for r in db.query(models.FoodPreference)
        .filter(models.FoodPreference.user_id == user.id)
        .all()
    }
    seen: set[tuple[str, str]] = set()
    for category, item_key in to_insert:
        if (category, item_key) in existing or (category, item_key) in seen:
            continue
        seen.add((category, item_key))
        db.add(models.FoodPreference(
            user_id=user.id,
            category=category,
            item_key=item_key,
        ))

    db.flush()
    after = _group_food_preferences(db, user.id)
    audit.record(
        db, admin, "user.preferences.update",
        target_type="user", target_id=user.id,
        details={
            "username": user.username,
            "reason": reason,
            "replace": body.replace,
            "before_count": sum(len(v) for v in before.values()),
            "after_count": sum(len(v) for v in after.values()),
            "changed_categories": _changed_preference_categories(before, after),
        },
    )
    db.commit()
    return {
        "user": _user_dict(user),
        "known": CATEGORY_ITEMS,
        "known_labels": _known_preference_labels(),
        "categories": after,
        "nutrition_audit": nutrition_audit.run_audit(db, user),
    }


@router.get("/llm-quotas")
def admin_list_llm_quotas(
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    q = db.query(models.User)
    if user_id is not None:
        q = q.filter(models.User.id == user_id)
    users = q.order_by(models.User.created_at.desc()).all()
    kinds = list(llm_quota.QUOTAS.keys())
    return {
        "kinds": {
            kind: {
                "limit": rule.limit,
                "window_days": rule.window_days,
            }
            for kind, rule in llm_quota.QUOTAS.items()
        },
        "users": [
            {
                "user": _user_dict(user),
                "quotas": {
                    kind: llm_quota.usage(db, user.id, kind)
                    for kind in kinds
                },
            }
            for user in users
        ],
    }


@router.post("/llm-quotas/reset")
def admin_reset_all_llm_quota(
    body: AdminQuotaReset,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="Quota resets require a reason")

    kind = body.kind or llm_quota.POOL_NAME
    if kind not in llm_quota.QUOTAS:
        raise HTTPException(status_code=422, detail="Unknown quota kind")

    base_query = db.query(models.LLMCallLog).filter(models.LLMCallLog.kind == kind)
    affected_user_count = (
        db.query(models.LLMCallLog.user_id)
        .filter(models.LLMCallLog.kind == kind)
        .distinct()
        .count()
    )
    deleted = base_query.delete(synchronize_session=False)
    db.flush()
    audit.record(
        db, admin, "system.llm_quota.reset",
        target_type="llm_quota", target_id=None,
        details={
            "kind": kind,
            "reason": reason,
            "scope": "all_users",
            "deleted_rows": deleted,
            "affected_user_count": affected_user_count,
        },
    )
    db.commit()
    return {
        "kind": kind,
        "scope": "all_users",
        "deleted_rows": deleted,
        "affected_user_count": affected_user_count,
    }


@router.post("/users/{user_id}/llm-quota/reset")
def admin_reset_llm_quota(
    user_id: int,
    body: AdminQuotaReset,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    user = _get_user_or_404(db, user_id)
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="Quota resets require a reason")

    if body.kind is not None and body.kind not in llm_quota.QUOTAS:
        raise HTTPException(status_code=422, detail="Unknown quota kind")

    kinds = [body.kind] if body.kind else list(llm_quota.QUOTAS.keys())
    before = {kind: llm_quota.usage(db, user.id, kind) for kind in kinds}
    query = db.query(models.LLMCallLog).filter(models.LLMCallLog.user_id == user.id)
    if body.kind:
        query = query.filter(models.LLMCallLog.kind == body.kind)
    deleted = query.delete(synchronize_session=False)
    db.flush()
    after = {kind: llm_quota.usage(db, user.id, kind) for kind in kinds}
    audit.record(
        db, admin, "user.llm_quota.reset",
        target_type="user", target_id=user.id,
        details={
            "username": user.username,
            "kind": body.kind or "all",
            "reason": reason,
            "deleted_rows": deleted,
            "before": before,
            "after": after,
        },
    )
    db.commit()
    return {
        "user": _user_dict(user),
        "kind": body.kind or "all",
        "deleted_rows": deleted,
        "quotas": after,
    }


@router.get("/food-library")
def admin_food_library(
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    return _food_library_payload()


@router.get("/observability/events")
def admin_observability_events(
    limit: int = Query(80, ge=1, le=300),
    event: Optional[str] = None,
    user_id: Optional[int] = None,
    logger: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    path = _app_log_path()
    if not path.exists():
        return {"source": str(path), "items": []}

    items: list[dict] = []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        if len(items) >= limit:
            break
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if event and record.get("event") != event:
            continue
        if logger and record.get("logger") != logger:
            continue
        if user_id is not None and str(record.get("user_id")) != str(user_id):
            continue
        items.append(_sanitize_log_record(record))

    return {"source": str(path), "items": items}


@router.get("/audit")
def admin_list_audit(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: Optional[str] = None,
    actor_id: Optional[int] = None,
    target_type: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    import json as _json
    q = db.query(models.AdminAuditLog)
    if action:
        q = q.filter(models.AdminAuditLog.action == action)
    if actor_id is not None:
        q = q.filter(models.AdminAuditLog.actor_user_id == actor_id)
    if target_type:
        q = q.filter(models.AdminAuditLog.target_type == target_type)

    total = q.count()
    rows = (
        q.order_by(models.AdminAuditLog.timestamp.desc())
        .offset(offset).limit(limit).all()
    )

    items = []
    for r in rows:
        details = None
        if r.details:
            try:
                details = _json.loads(r.details)
            except ValueError:
                details = {"_raw": r.details}
        items.append({
            "id": r.id,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "actor_user_id": r.actor_user_id,
            "actor_username": r.actor_username,
            "action": r.action,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "details": details,
            "request_id": r.request_id,
        })
    return {"total": total, "items": items}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_user_or_404(db: Session, user_id: int) -> models.User:
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _group_food_preferences(db: Session, user_id: int) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {category: [] for category in CATEGORY_ITEMS}
    rows = (
        db.query(models.FoodPreference)
        .filter(models.FoodPreference.user_id == user_id)
        .order_by(models.FoodPreference.category.asc(), models.FoodPreference.item_key.asc())
        .all()
    )
    for row in rows:
        if row.category not in CATEGORY_ITEMS:
            continue
        if row.item_key not in CATEGORY_ITEMS[row.category]:
            continue
        grouped.setdefault(row.category, []).append(row.item_key)
    return grouped


def _validate_preference_items(items: list[AdminPreferenceItem]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for item in items:
        category = item.category.strip()
        item_key = item.item_key.strip().lower()
        if category not in CATEGORY_ITEMS:
            raise HTTPException(status_code=422, detail=f"Unknown category '{category}'")
        if item_key not in CATEGORY_ITEMS[category]:
            raise HTTPException(status_code=422, detail=f"Unknown item_key '{item_key}' for category '{category}'")
        result.append((category, item_key))
    return result


def _changed_preference_categories(
    before: dict[str, list[str]],
    after: dict[str, list[str]],
) -> list[str]:
    changed: list[str] = []
    for category in sorted(set(before) | set(after)):
        if sorted(before.get(category, [])) != sorted(after.get(category, [])):
            changed.append(category)
    return changed


def _known_preference_labels() -> dict[str, dict[str, dict[str, str]]]:
    return {
        category: {
            slug: {
                "zh": FL.display_name(slug, "zh"),
                "en": FL.display_name(slug, "en"),
            }
            for slug in slugs
        }
        for category, slugs in CATEGORY_ITEMS.items()
    }


def _food_library_payload() -> dict:
    validation = {
        bucket: {
            "label_zh": FL.VALIDATION_BUCKET_LABELS[bucket]["zh"],
            "label_en": FL.VALIDATION_BUCKET_LABELS[bucket]["en"],
            "count": len(FL.slugs_by_validation_bucket(bucket)),
            "is_blocking": bucket in getattr(nutrition_audit, "_BLOCKING_BUCKETS", set()),
            "slugs": FL.slugs_by_validation_bucket(bucket),
        }
        for bucket in FL.VALIDATION_BUCKETS
    }
    execution = {
        bucket: {
            "label_zh": FL.EXECUTION_BUCKET_LABELS[bucket]["zh"],
            "label_en": FL.EXECUTION_BUCKET_LABELS[bucket]["en"],
            "count": len(FL.slugs_by_execution_bucket(bucket)),
            "slugs": FL.slugs_by_execution_bucket(bucket),
        }
        for bucket in FL.EXECUTION_BUCKETS
    }
    foods = []
    for slug, entry in sorted(FL.FOOD_LIBRARY.items()):
        foods.append({
            "slug": slug,
            "name_zh": entry["zh"],
            "name_en": entry["en"],
            "primary_macro": entry["primary_macro"],
            "kcal_per_100g": entry["kcal_per_100g"],
            "protein_per_100g": entry["protein_per_100g"],
            "carbs_per_100g": entry["carbs_per_100g"],
            "fat_per_100g": entry["fat_per_100g"],
            "validation_buckets": list(entry["validation_buckets"]),
            "execution_buckets": list(entry["execution_buckets"]),
            "micronutrient_roles": list(entry["micronutrient_roles"]),
        })
    return {
        "total_foods": len(foods),
        "validation_buckets": validation,
        "execution_buckets": execution,
        "foods": foods,
    }


def _app_log_path() -> Path:
    backend_root = Path(__file__).resolve().parents[1]
    candidates = [
        Path(os.getenv("LOG_DIR", "")) / "app.log" if os.getenv("LOG_DIR") else None,
        backend_root / "logs" / "app.log",
        Path.cwd() / "logs" / "app.log",
        Path.cwd() / "backend" / "logs" / "app.log",
    ]
    for path in candidates:
        if path and path.exists():
            return path
    return backend_root / "logs" / "app.log"


def _sanitize_log_record(record: dict) -> dict:
    allowed_keys = {
        "ts", "lvl", "logger", "request_id", "journey_id", "ui_action",
        "user_id", "event", "domain", "method", "path", "status",
        "duration_ms", "kind", "action", "target_type", "target_id",
        "error", "reason", "exc_class", "classified_count", "warning_count",
        "feasibility", "variant",
    }
    out = {key: record.get(key) for key in allowed_keys if key in record}
    msg = str(record.get("msg") or "")
    lowered = msg.lower()
    if any(token in lowered for token in ("raw response", "prompt", "password", "token", "authorization")):
        msg = "Sensitive or raw payload hidden. Use request_id for backend debugging."
    elif len(msg) > 220:
        msg = msg[:220] + "..."
    out["msg"] = msg
    return out


def _user_dict(u: models.User) -> dict:
    mem_level = u.membership.level if u.membership else "free"
    profile = u.bmr_profile
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "is_active": bool(u.is_active),
        "is_admin": bool(u.is_admin),
        "membership_level": mem_level,
        "language": u.language,
        "has_bmr_profile": profile is not None,
        "goal": calorie.normalize_goal(profile.goal) if profile else None,
        "target_weight_kg": u.target_weight_kg,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def _recipe_dict(r: models.Recipe) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "ingredients": r.ingredients,
        "steps": r.steps,
        "video_url": r.video_url,
        "category": r.category,
        "meal_types": r.meal_types,
        "calories": r.calories,
        "protein_g": r.protein_g,
        "carbs_g": r.carbs_g,
        "fat_g": r.fat_g,
        "serving_g": r.serving_g,
        "is_builtin": r.is_builtin,
        "is_approved": r.is_approved,
        "submitted_by": r.submitted_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
