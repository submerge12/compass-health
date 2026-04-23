from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from services import audit, calorie, engagement

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
    name: str
    ingredients: Optional[str] = None
    steps: Optional[str] = None
    video_url: Optional[str] = None
    category: Optional[str] = None
    meal_types: Optional[str] = None   # CSV: "breakfast,lunch,dinner"
    calories: Optional[int] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    serving_g: Optional[float] = None


class ReportStatusUpdate(BaseModel):
    status: str   # pending / reviewed


class UserPatch(BaseModel):
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None
    membership_level: Optional[str] = None   # free / normal / pro / pro_max


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
    recipe = models.Recipe(
        name=body.name,
        ingredients=body.ingredients,
        steps=body.steps,
        video_url=body.video_url,
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
    if recipe.name != body.name:
        changed.append("name")
    recipe.name = body.name
    for field in (
        "ingredients", "steps", "video_url", "category",
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
    db.query(models.DailyActivityPlan).filter(models.DailyActivityPlan.user_id == user_id).delete()
    db.query(models.MealPlanEntry).filter(models.MealPlanEntry.user_id == user_id).delete()
    db.query(models.DailyMealPlanConfirmation).filter(
        models.DailyMealPlanConfirmation.user_id == user_id
    ).delete()
    db.query(models.MissingRecipeReport).filter(
        models.MissingRecipeReport.user_id == user_id
    ).delete()
    db.query(models.FoodPreference).filter(models.FoodPreference.user_id == user_id).delete()
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

    now = datetime.now(timezone.utc)
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
