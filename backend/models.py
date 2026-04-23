from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime,
    ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import relationship
from database import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    language = Column(String, default="zh")
    target_weight_kg = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    bmr_profile = relationship("BMRProfile", back_populates="user", uselist=False)
    refresh_tokens = relationship("RefreshToken", back_populates="user")
    membership = relationship("Membership", back_populates="user", uselist=False)
    settings = relationship("UserSettings", back_populates="user", uselist=False)
    checkins = relationship("CheckIn", back_populates="user")


class BMRProfile(Base):
    __tablename__ = "bmr_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    age = Column(Integer, nullable=False)
    gender = Column(String, nullable=False)           # "male" / "female"
    height_cm = Column(Float, nullable=False)
    weight_kg = Column(Float, nullable=False)
    # Legacy — activity lives in DailyActivityPlan now. Kept nullable for
    # legacy rows; new rows write a placeholder so the NOT NULL on old DBs
    # still accepts them.
    activity_level = Column(String, nullable=True)
    goal = Column(String, nullable=False)             # see services/calorie.py GOALS
    bmr_value = Column(Float, nullable=False)
    # Legacy — TDEE is computed dynamically from today's DailyActivityPlan.
    tdee_value = Column(Float, nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="bmr_profile")


class DailyActivityPlan(Base):
    __tablename__ = "daily_activity_plans"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(String, nullable=False, index=True)  # "YYYY-MM-DD" (UTC)
    activity_level = Column(String, nullable=False)    # sedentary / lightly_active / ...
    logged_at = Column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_daily_activity"),)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=utcnow)

    user = relationship("User", back_populates="refresh_tokens")


class WaterLog(Base):
    __tablename__ = "water_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(String, nullable=False, index=True)   # "YYYY-MM-DD"
    amount_ml = Column(Integer, nullable=False)
    logged_at = Column(DateTime, default=utcnow)


class ExerciseLog(Base):
    __tablename__ = "exercise_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(String, nullable=False, index=True)
    exercise_type = Column(String, nullable=False)
    duration_min = Column(Integer, nullable=False)
    calories_burned = Column(Integer, nullable=False)
    notes = Column(String, nullable=True)
    logged_at = Column(DateTime, default=utcnow)


class DietLog(Base):
    __tablename__ = "diet_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(String, nullable=False, index=True)
    meal_type = Column(String, nullable=False)   # breakfast/lunch/dinner/snack
    food_name = Column(String, nullable=False)
    ingredients = Column(Text, nullable=True)       # raw ingredient list for AI-based entries
    calories = Column(Integer, nullable=False, default=0)
    protein_g = Column(Float, default=0.0)
    carbs_g = Column(Float, default=0.0)
    fat_g = Column(Float, default=0.0)
    logged_at = Column(DateTime, default=utcnow)


class PhysicalCondition(Base):
    __tablename__ = "physical_conditions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(String, nullable=False, index=True)
    weight_kg = Column(Float, nullable=True)
    bp_systolic = Column(Integer, nullable=True)
    bp_diastolic = Column(Integer, nullable=True)
    heart_rate = Column(Integer, nullable=True)
    sleep_hours = Column(Float, nullable=True)
    mood = Column(Integer, nullable=True)    # 1-5
    notes = Column(String, nullable=True)
    logged_at = Column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_condition_user_date"),)


class CheckIn(Base):
    __tablename__ = "checkins"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(String, nullable=False)    # "YYYY-MM-DD"
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_checkin_user_date"),)

    user = relationship("User", back_populates="checkins")


class Membership(Base):
    __tablename__ = "memberships"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    level = Column(String, default="free")   # free / normal / pro / pro_max
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="membership")


class UserSettings(Base):
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    daily_water_goal_ml = Column(Integer, default=2000)
    water_reminder_min = Column(Integer, default=60)
    language = Column(String, default="zh")
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="settings")


class Recipe(Base):
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    ingredients = Column(Text, nullable=True)
    steps = Column(Text, nullable=True)
    video_url = Column(String, nullable=True)
    category = Column(String, nullable=True)
    is_builtin = Column(Boolean, default=False)
    submitted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_approved = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)

    # CSV of "breakfast,lunch,dinner" — which slots this recipe fits.
    meal_types = Column(String, nullable=True)
    # Per-serving nutrition. Populated for LLM-generated or admin-curated dishes.
    calories = Column(Integer, nullable=True)
    protein_g = Column(Float, nullable=True)
    carbs_g = Column(Float, nullable=True)
    fat_g = Column(Float, nullable=True)
    serving_g = Column(Float, nullable=True)
    # JSON array of food_library slugs for pool-derived dishes; NULL for others.
    # Used by the ingredient-distribution validator in services/meal_scheduler.py.
    ingredient_slugs = Column(Text, nullable=True)
    # Spec-v1 structured ingredients: JSON array of
    # `{slug: str, grams: float | null, required: bool}`.
    # `services/recipe_matcher.is_available` consults this; `ingredient_slugs`
    # remains populated during the transition and is dropped once all call
    # sites read `ingredients_json` (planned for a later phase).
    ingredients_json = Column(Text, nullable=True)


class MealPlanEntry(Base):
    __tablename__ = "meal_plan_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(String, nullable=False, index=True)     # "YYYY-MM-DD"
    meal_type = Column(String, nullable=False)            # breakfast/lunch/dinner/snack
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=True)
    custom_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    # Pre-computed so the midnight auto-fill can copy into DietLog without
    # re-scaling. LLM proposes portion_g; the other fields scale from Recipe.
    portion_g = Column(Float, nullable=True)
    calories = Column(Integer, nullable=True)
    protein_g = Column(Float, nullable=True)
    carbs_g = Column(Float, nullable=True)
    fat_g = Column(Float, nullable=True)

    # Spec-v1 slot status. One of the SLOT_STATUS_* constants in
    # services/planning_context.py: fixed / recipe / generated / recorded.
    # Drives the priority chain (recorded > fixed > recipe > generated) and
    # tells the planner which slots to skip when filling empty ones.
    status = Column(String, nullable=False, default="recipe", server_default="recipe")

    recipe = relationship("Recipe")
    __table_args__ = (
        UniqueConstraint("user_id", "date", "meal_type", name="uq_meal_plan_entry"),
    )


class LLMCallLog(Base):
    """One row per LLM invocation that counts against a user-facing quota.

    `kind` namespaces the counter so future LLM uses (e.g. meal-image parsing)
    don't interfere with the recipe-suggester budget. The quota window is
    evaluated at read time — we just append here.
    """

    __tablename__ = "llm_call_log"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String, nullable=False, index=True)
    called_at = Column(DateTime, default=utcnow, nullable=False, index=True)


class UserSavedRecipe(Base):
    """User's personal saved-recipe library.

    Populated when the user selects a dish for their meal plan; the recipe
    stays available for reuse across weeks until the user explicitly deletes
    it. Regular-tier users (free / normal) are capped at 20 saved recipes;
    the cap is enforced at the application layer — see
    `services.saved_recipes.SAVED_RECIPE_CAP`.
    """

    __tablename__ = "user_saved_recipes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    saved_at = Column(DateTime, default=utcnow)

    recipe = relationship("Recipe")

    __table_args__ = (
        UniqueConstraint("user_id", "recipe_id", name="uq_user_saved_recipe"),
    )


class UserFixedMeal(Base):
    """A meal slot the user wants auto-filled every week.

    Spec-v1 "fixed meals" layer: evaluated before the recipe matcher so its
    nutrition is subtracted from the daily target before empty slots are
    planned. `weekday` is 0–6 (Monday=0, Sunday=6); `NULL` means every day.
    """

    __tablename__ = "user_fixed_meals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    weekday = Column(Integer, nullable=True)              # 0=Mon..6=Sun, NULL=every day
    meal_type = Column(String, nullable=False)            # breakfast/lunch/dinner/snack
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=True)
    custom_name = Column(String, nullable=True)
    portion_g = Column(Float, nullable=True)
    # Cached macros so the daily-target deduction does not re-scale on every
    # plan request. Refreshed when the user edits the fixed meal.
    calories = Column(Integer, nullable=True)
    protein_g = Column(Float, nullable=True)
    carbs_g = Column(Float, nullable=True)
    fat_g = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    recipe = relationship("Recipe")

    __table_args__ = (
        UniqueConstraint("user_id", "weekday", "meal_type", name="uq_user_fixed_meal"),
    )


class DailyMealPlanConfirmation(Base):
    __tablename__ = "daily_meal_plan_confirmations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(String, nullable=False, index=True)     # "YYYY-MM-DD" (UTC)
    confirmed_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_meal_plan_confirm"),
    )


class MissingRecipeReport(Base):
    __tablename__ = "missing_recipe_reports"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ingredients_query = Column(Text, nullable=False)
    suggested_name = Column(String, nullable=True)
    status = Column(String, default="pending")            # pending / reviewed
    reported_at = Column(DateTime, default=utcnow)


class FoodPreference(Base):
    __tablename__ = "food_preferences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    category = Column(String, nullable=False)
    # Canonical slug, e.g. "rice", "spinach", "tofu_firm".
    item_key = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "category", "item_key", name="uq_food_pref"),
    )


class AdminAuditLog(Base):
    """Immutable record of every admin mutation. Written in the same
    transaction as the action itself, so the audit trail can never diverge
    from reality. `actor_username` is stored as a snapshot: if the admin
    account is later deleted, the history still reads correctly."""
    __tablename__ = "admin_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=utcnow, nullable=False, index=True)
    # Nullable FK so a deleted admin's rows don't violate integrity; the
    # username snapshot is what the UI displays.
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    actor_username = Column(String, nullable=False)
    action = Column(String, nullable=False, index=True)   # e.g. "user.delete"
    target_type = Column(String, nullable=True)           # "user" / "recipe" / "report"
    target_id = Column(Integer, nullable=True)
    # JSON-encoded body describing what changed. Never contains secrets.
    details = Column(Text, nullable=True)
    # Correlates to the request_id in compass.access / compass.audit logs.
    request_id = Column(String, nullable=True, index=True)
