"""
Shared pytest fixtures.

Everything here runs *before* we import the app, so we can control:
  - SECRET_KEY (auth.py refuses to load without a strong one)
  - DATABASE_URL (point at a throwaway sqlite file so tests never touch dev DB)
  - LOG_DIR (keep test logs out of the real logs/ directory)

load_dotenv in app modules only sets values that aren't already in the
environment, so setting these here wins.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# --- Environment setup — MUST run before importing anything from the app ----

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Strong, unique SECRET_KEY so auth.py validation is happy.
os.environ["SECRET_KEY"] = (
    "pytest-strong-key-a7f3e2c8b4d9f1e6a5b3c7d9e2f4a6b8c0d2e4f6a8b0c2d4e6f8a0b2c4d6e8f0"
)

# Point at a throwaway DB file — unique per test session.
_tmp_db = Path(tempfile.gettempdir()) / "compass_test.db"
if _tmp_db.exists():
    _tmp_db.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.as_posix()}"

_tmp_logs = Path(tempfile.gettempdir()) / "compass_test_logs"
_tmp_logs.mkdir(exist_ok=True)
os.environ["LOG_DIR"] = str(_tmp_logs)

# --- Fixtures --------------------------------------------------------------


@pytest.fixture(scope="session")
def app():
    """Import the app only after env is set, so imports pick up our config."""
    import main
    return main.app


@pytest.fixture()
def client(app):
    """Fresh TestClient per test. Entering the context runs the app lifespan
    (which creates the tables)."""
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_state():
    """Clear rate-limit counters and wipe DB rows between tests so each test
    starts from a known empty slate. Runs *after* the client fixture's
    lifespan has created the tables on first use."""
    from services import rate_limit
    rate_limit.reset()
    yield
    rate_limit.reset()


@pytest.fixture()
def clean_db(app):
    """Truncate user-visible tables. Use in tests that need an empty DB; the
    app fixture is requested so tables exist before we touch them."""
    from database import SessionLocal
    import models
    db = SessionLocal()
    # Order matters — children first.
    for table in (
        models.AdminAuditLog,
        models.AssistantPendingAction,
        models.UserNutritionMemory,
        models.LLMCallLog,
        models.DailyMealPlanConfirmation,
        models.RecipeTrialRating,
        models.UserSavedRecipe,
        models.UserFixedMeal,
        models.MealPlanEntry,
        models.MissingRecipeReport,
        models.DailyActivityPlan,
        models.DietLog,
        models.ExerciseLog,
        models.WaterLog,
        models.PhysicalCondition,
        models.RefreshToken,
        models.FoodPreference,
        models.Recipe,
        models.Membership,
        models.UserSettings,
        models.BMRProfile,
        models.User,
    ):
        db.query(table).delete()
    db.commit()
    db.close()
    yield


# --- Helpers --------------------------------------------------------------


def register(client, username: str, password: str = "pw12345") -> dict:
    """POST /register and return the parsed token-response dict."""
    r = client.post("/api/auth/register", json={"username": username, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def promote_to_admin(username: str) -> None:
    """Force-promote a user via DB (bypasses the first-user-is-admin rule so
    tests don't depend on ordering)."""
    from database import SessionLocal
    import models
    db = SessionLocal()
    u = db.query(models.User).filter(models.User.username == username).first()
    assert u is not None, f"user {username} not found"
    u.is_admin = True
    db.commit()
    db.close()
