"""Phase 5 smoke — /api/fixed-meals CRUD + DietLog → MealPlanEntry.status flip.

Seeds a dedicated test user + recipe on the dev DB, exercises every route
via TestClient with a dependency-override for auth, then tears down.
Run: `python scripts/smoke_phase5.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _seed(db):
    """Create a unique test user + recipe. Returns (user_id, recipe_id)."""
    import models
    from services import calorie as calorie_svc

    u = models.User(
        username="test_phase5_smoke",
        email="test_phase5_smoke@example.invalid",
        hashed_password="pbkdf2:sha256:test",
        is_admin=False,
    )
    db.add(u)
    db.flush()

    # BMR profile so daily_target_for_date doesn't zero out.
    bmr = calorie_svc.compute_bmr(30, "female", 165.0, 60.0)
    tdee = calorie_svc.compute_tdee(bmr, "moderate")
    prof = models.BMRProfile(
        user_id=u.id,
        age=30,
        gender="female",
        height_cm=165.0,
        weight_kg=60.0,
        goal="maintain",
        activity_level="moderate",
        bmr_value=bmr,
        tdee_value=tdee,
    )
    db.add(prof)

    # Recipe with structured ingredients_json so procurement can expand it.
    r = models.Recipe(
        name="TEST Phase5 Chicken & Rice",
        ingredients="Chicken breast, brown rice",
        ingredients_json='[{"slug":"chicken_breast","grams":120,"required":true},'
                         '{"slug":"brown_rice","grams":80,"required":true}]',
        meal_types="lunch,dinner",
        calories=400,
        protein_g=35.0,
        carbs_g=50.0,
        fat_g=5.0,
        serving_g=200.0,
        is_builtin=False,
        submitted_by=u.id,
        is_approved=True,
    )
    db.add(r)
    db.commit()
    return u.id, r.id


def _teardown(db, user_id: int, recipe_id: int):
    import models
    db.query(models.DietLog).filter_by(user_id=user_id).delete()
    db.query(models.UserFixedMeal).filter_by(user_id=user_id).delete()
    db.query(models.MealPlanEntry).filter_by(user_id=user_id).delete()
    db.query(models.FoodPreference).filter_by(user_id=user_id).delete()
    db.query(models.BMRProfile).filter_by(user_id=user_id).delete()
    db.query(models.Recipe).filter_by(id=recipe_id).delete()
    db.query(models.User).filter_by(id=user_id).delete()
    db.commit()


def main():
    from fastapi import Depends
    from fastapi.testclient import TestClient

    import main as app_main
    import models
    from auth import get_current_user
    from database import SessionLocal, get_db

    db = SessionLocal()
    user_id, recipe_id = _seed(db)
    db.close()
    print(f"seeded user_id={user_id} recipe_id={recipe_id}")

    def _user_override(db=Depends(get_db)):
        return db.query(models.User).filter_by(id=user_id).one()

    app_main.app.dependency_overrides[get_current_user] = _user_override

    try:
        with TestClient(app_main.app) as c:
            # ── Part A — /api/fixed-meals CRUD ──────────────────────────────
            print("\n── Part A: fixed-meals CRUD ──")

            # 1. List empty
            r = c.get("/api/fixed-meals")
            assert r.status_code == 200, r.text
            assert r.json()["items"] == []
            print("GET empty: [] ✓")

            # 2. Create — recipe + portion, portion smaller than serving
            r = c.post("/api/fixed-meals", json={
                "meal_type": "breakfast",
                "weekday":   None,             # every day
                "recipe_id": recipe_id,
                "portion_g": 100.0,            # half of serving_g=200
            })
            assert r.status_code == 200, r.text
            item = r.json()
            fm_id = item["id"]
            assert item["recipe_id"] == recipe_id
            assert item["portion_g"] == 100.0
            # 400 kcal × (100/200) = 200 kcal
            assert item["calories"] == 200, f"expected 200 kcal, got {item['calories']}"
            assert item["protein_g"] == 17.5
            assert item["carbs_g"] == 25.0
            assert item["fat_g"] == 2.5
            print(f"POST created id={fm_id} with half-portion macros ✓")

            # 3. List — should contain 1
            r = c.get("/api/fixed-meals")
            assert r.status_code == 200
            assert len(r.json()["items"]) == 1
            print("GET after create: 1 item ✓")

            # 4. PATCH portion to full serving — macros should double
            r = c.patch(f"/api/fixed-meals/{fm_id}", json={"portion_g": 200.0})
            assert r.status_code == 200, r.text
            updated = r.json()
            assert updated["portion_g"] == 200.0
            assert updated["calories"] == 400, f"expected 400 kcal, got {updated['calories']}"
            assert updated["protein_g"] == 35.0
            print("PATCH portion→full: macros re-scaled ✓")

            # 5. PATCH to a different weekday + meal_type
            r = c.patch(f"/api/fixed-meals/{fm_id}", json={
                "weekday": 2, "meal_type": "lunch",
            })
            assert r.status_code == 200
            assert r.json()["weekday"] == 2
            assert r.json()["meal_type"] == "lunch"
            print("PATCH weekday+meal_type ✓")

            # 6. Uniqueness — create a second fixed meal with the SAME
            # (weekday, meal_type) should 409
            r = c.post("/api/fixed-meals", json={
                "meal_type": "lunch", "weekday": 2,
                "recipe_id": recipe_id, "portion_g": 150.0,
            })
            assert r.status_code == 409, f"expected 409 on dup, got {r.status_code}: {r.text}"
            print("POST duplicate → 409 ✓")

            # 7. Validation — no recipe_id and no custom_name → 422
            r = c.post("/api/fixed-meals", json={"meal_type": "dinner"})
            assert r.status_code == 422, r.text
            print("POST missing recipe_id+custom_name → 422 ✓")

            # 8. Validation — bad meal_type
            r = c.post("/api/fixed-meals", json={
                "meal_type": "brunch", "recipe_id": recipe_id,
            })
            assert r.status_code == 422
            print("POST bad meal_type → 422 ✓")

            # 9. DELETE
            r = c.delete(f"/api/fixed-meals/{fm_id}")
            assert r.status_code == 200, r.text
            assert r.json() == {"deleted": fm_id}
            r = c.get("/api/fixed-meals")
            assert r.json()["items"] == []
            print("DELETE: list empty again ✓")

            # 10. DELETE 404 after gone
            r = c.delete(f"/api/fixed-meals/{fm_id}")
            assert r.status_code == 404
            print("DELETE nonexistent → 404 ✓")

            # ── Part B — DietLog flip on MealPlanEntry.status ───────────────
            print("\n── Part B: DietLog → MealPlanEntry.status flip ──")

            # Seed a plan entry directly (bypass /select to keep the test focused)
            db2 = SessionLocal()
            plan = models.MealPlanEntry(
                user_id=user_id,
                date="2026-04-22",
                meal_type="lunch",
                recipe_id=recipe_id,
                portion_g=200.0,
                calories=400, protein_g=35.0, carbs_g=50.0, fat_g=5.0,
                status="recipe",
            )
            db2.add(plan)
            db2.commit()
            plan_id = plan.id
            db2.close()
            print(f"seeded MealPlanEntry id={plan_id} status=recipe")

            # Log a diet entry for the SAME slot → status should flip to recorded
            r = c.post("/api/diet/log", json={
                "date": "2026-04-22",
                "meal_type": "lunch",
                "food_name": "TEST lunch",
                "calories": 420,
                "protein_g": 30.0, "carbs_g": 50.0, "fat_g": 5.0,
            })
            assert r.status_code == 200, r.text
            log_id = r.json()["id"]

            db2 = SessionLocal()
            after = db2.query(models.MealPlanEntry).filter_by(id=plan_id).one()
            assert after.status == "recorded", f"expected recorded, got {after.status}"
            db2.close()
            print(f"POST /api/diet/log → MealPlanEntry.status = recorded ✓")

            # Log a SECOND diet entry for the same slot — status stays recorded
            r = c.post("/api/diet/log", json={
                "date": "2026-04-22",
                "meal_type": "lunch",
                "food_name": "TEST lunch #2",
                "calories": 100, "protein_g": 5.0, "carbs_g": 10.0, "fat_g": 2.0,
            })
            assert r.status_code == 200
            second_log_id = r.json()["id"]

            # Delete the FIRST diet log — second one still present → stays recorded
            r = c.delete(f"/api/diet/log/{log_id}")
            assert r.status_code == 200
            db2 = SessionLocal()
            after = db2.query(models.MealPlanEntry).filter_by(id=plan_id).one()
            assert after.status == "recorded", \
                f"first DietLog gone but second remains — should stay recorded, got {after.status}"
            db2.close()
            print("DELETE first DietLog (second remains) → still recorded ✓")

            # Delete the SECOND — now no log remains → should revert to recipe
            r = c.delete(f"/api/diet/log/{second_log_id}")
            assert r.status_code == 200
            db2 = SessionLocal()
            after = db2.query(models.MealPlanEntry).filter_by(id=plan_id).one()
            assert after.status == "recipe", \
                f"expected revert to recipe (recipe_id is set), got {after.status}"
            db2.close()
            print("DELETE last DietLog → MealPlanEntry.status reverted to recipe ✓")

            # Now test revert for a GENERATED slot (no recipe_id)
            db2 = SessionLocal()
            plan_gen = models.MealPlanEntry(
                user_id=user_id,
                date="2026-04-23",
                meal_type="dinner",
                recipe_id=None,
                portion_g=250.0,
                calories=500, protein_g=40.0, carbs_g=40.0, fat_g=15.0,
                status="generated",
            )
            db2.add(plan_gen)
            db2.commit()
            plan_gen_id = plan_gen.id
            db2.close()

            r = c.post("/api/diet/log", json={
                "date": "2026-04-23",
                "meal_type": "dinner",
                "food_name": "TEST dinner",
                "calories": 520, "protein_g": 35.0, "carbs_g": 45.0, "fat_g": 18.0,
            })
            assert r.status_code == 200
            gen_log_id = r.json()["id"]

            db2 = SessionLocal()
            after = db2.query(models.MealPlanEntry).filter_by(id=plan_gen_id).one()
            assert after.status == "recorded"
            db2.close()

            r = c.delete(f"/api/diet/log/{gen_log_id}")
            assert r.status_code == 200
            db2 = SessionLocal()
            after = db2.query(models.MealPlanEntry).filter_by(id=plan_gen_id).one()
            assert after.status == "generated", \
                f"expected revert to generated (recipe_id is NULL), got {after.status}"
            db2.close()
            print("DELETE DietLog for generated slot → reverted to generated ✓")

            # No-plan-entry edge case: log a DietLog for a slot that has no
            # MealPlanEntry. Should just create the DietLog, no flip, no errors.
            r = c.post("/api/diet/log", json={
                "date": "2026-04-24",
                "meal_type": "breakfast",
                "food_name": "TEST breakfast with no plan",
                "calories": 300, "protein_g": 15.0, "carbs_g": 40.0, "fat_g": 10.0,
            })
            assert r.status_code == 200
            orphan_log_id = r.json()["id"]
            r = c.delete(f"/api/diet/log/{orphan_log_id}")
            assert r.status_code == 200
            print("log/delete with no MealPlanEntry → no errors ✓")

        print("\n✅ All Phase 5 smoke checks passed.")

    finally:
        app_main.app.dependency_overrides.pop(get_current_user, None)
        db = SessionLocal()
        _teardown(db, user_id, recipe_id)
        db.close()
        print("teardown OK")


if __name__ == "__main__":
    main()
