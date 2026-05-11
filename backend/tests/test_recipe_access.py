from __future__ import annotations

from tests.conftest import register


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_user_submitted_recipe_stays_pending_and_private(client, clean_db):
    owner = register(client, "recipe_owner")
    other = register(client, "recipe_other")

    created = client.post(
        "/api/recipes",
        headers=_headers(owner["access_token"]),
        json={
            "name": "Private draft soup",
            "ingredients": "tomato\negg",
            "steps": "cook gently",
        },
    )
    assert created.status_code == 200, created.text
    recipe = created.json()
    assert recipe["is_approved"] is False

    own_get = client.get(
        f"/api/recipes/{recipe['id']}",
        headers=_headers(owner["access_token"]),
    )
    assert own_get.status_code == 200, own_get.text

    other_get = client.get(
        f"/api/recipes/{recipe['id']}",
        headers=_headers(other["access_token"]),
    )
    assert other_get.status_code == 404

    other_list = client.get("/api/recipes", headers=_headers(other["access_token"]))
    assert other_list.status_code == 200, other_list.text
    assert recipe["id"] not in {row["id"] for row in other_list.json()}

    other_plan = client.post(
        "/api/meal-plan/entry",
        headers=_headers(other["access_token"]),
        json={
            "date": "2026-04-26",
            "meal_type": "lunch",
            "recipe_id": recipe["id"],
        },
    )
    assert other_plan.status_code == 404


def test_confirm_day_marks_copied_plan_entries_recorded(client, clean_db):
    from database import SessionLocal
    import models

    auth = register(client, "confirm_owner")
    headers = _headers(auth["access_token"])
    date = "2026-04-26"

    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(username="confirm_owner").one()
        recipe = models.Recipe(
            name="Confirmable lunch",
            ingredients="rice\nchicken",
            steps="cook",
            is_approved=True,
        )
        db.add(recipe)
        db.flush()
        entry = models.MealPlanEntry(
            user_id=user.id,
            date=date,
            meal_type="lunch",
            recipe_id=recipe.id,
            calories=500,
            protein_g=30,
            carbs_g=60,
            fat_g=12,
        )
        db.add(entry)
        db.commit()
        entry_id = entry.id
    finally:
        db.close()

    response = client.post(f"/api/meal-plan/confirm?date={date}", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["filled"] == ["lunch"]

    db = SessionLocal()
    try:
        entry = db.query(models.MealPlanEntry).filter_by(id=entry_id).one()
        assert entry.status == "recorded"
        log = db.query(models.DietLog).filter_by(
            user_id=entry.user_id,
            date=date,
            meal_type="lunch",
        ).one()
        assert log.food_name == "Confirmable lunch"
    finally:
        db.close()


def test_confirm_day_marks_existing_logged_slots_recorded(client, clean_db):
    from database import SessionLocal
    import models

    auth = register(client, "confirm_existing_owner")
    headers = _headers(auth["access_token"])
    date = "2026-04-27"

    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(username="confirm_existing_owner").one()
        recipe = models.Recipe(
            name="Already logged lunch",
            ingredients="rice\nfish",
            steps="cook",
            is_approved=True,
        )
        db.add(recipe)
        db.flush()
        entry = models.MealPlanEntry(
            user_id=user.id,
            date=date,
            meal_type="lunch",
            recipe_id=recipe.id,
            calories=520,
            protein_g=32,
            carbs_g=58,
            fat_g=14,
        )
        db.add(entry)
        db.add(models.DietLog(
            user_id=user.id,
            date=date,
            meal_type="lunch",
            food_name="Manual lunch",
            calories=510,
            protein_g=30,
            carbs_g=55,
            fat_g=16,
        ))
        db.commit()
        entry_id = entry.id
    finally:
        db.close()

    response = client.post(f"/api/meal-plan/confirm?date={date}", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["filled"] == []

    db = SessionLocal()
    try:
        entry = db.query(models.MealPlanEntry).filter_by(id=entry_id).one()
        assert entry.status == "recorded"
        assert db.query(models.DietLog).filter_by(
            user_id=entry.user_id,
            date=date,
            meal_type="lunch",
        ).count() == 1
    finally:
        db.close()


def test_autofill_marks_existing_logged_slots_recorded(client, clean_db):
    from database import SessionLocal
    import models
    from services import autofill

    register(client, "autofill_existing_owner")
    date = "2026-04-28"

    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(username="autofill_existing_owner").one()
        recipe = models.Recipe(
            name="Autofill logged dinner",
            ingredients="tofu\nspinach",
            steps="cook",
            is_approved=True,
        )
        db.add(recipe)
        db.flush()
        entry = models.MealPlanEntry(
            user_id=user.id,
            date=date,
            meal_type="dinner",
            recipe_id=recipe.id,
            calories=430,
            protein_g=24,
            carbs_g=38,
            fat_g=18,
        )
        db.add(entry)
        db.add(models.DietLog(
            user_id=user.id,
            date=date,
            meal_type="dinner",
            food_name="Manual dinner",
            calories=440,
            protein_g=22,
            carbs_g=36,
            fat_g=20,
        ))
        db.commit()
        entry_id = entry.id

        result = autofill.run_autofill_for_date(db, date)
        assert result["filled"] == 0
        assert result["skipped_already_logged"] == 1

        entry = db.query(models.MealPlanEntry).filter_by(id=entry_id).one()
        assert entry.status == "recorded"
        assert db.query(models.DietLog).filter_by(
            user_id=user.id,
            date=date,
            meal_type="dinner",
        ).count() == 1
    finally:
        db.close()


def test_saved_recipes_dedupe_same_dish_with_different_recipe_ids(client, clean_db):
    from datetime import datetime

    from database import SessionLocal
    import models
    from services import saved_recipes

    auth = register(client, "saved_duplicate_owner")
    headers = _headers(auth["access_token"])

    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(username="saved_duplicate_owner").one()
        recipe_one = models.Recipe(
            name="Tomato egg rice",
            ingredients="tomato\negg\nrice",
            steps="cook",
            is_approved=False,
            submitted_by=user.id,
        )
        recipe_two = models.Recipe(
            name="  tomato   egg rice ",
            ingredients="tomato  \n egg\nrice",
            steps="cook again",
            is_approved=False,
            submitted_by=user.id,
        )
        recipe_three = models.Recipe(
            name="Tomato egg rice",
            ingredients="tomato\negg\nrice",
            steps="cook a third time",
            is_approved=False,
            submitted_by=user.id,
        )
        db.add_all([recipe_one, recipe_two, recipe_three])
        db.flush()
        db.add(models.UserSavedRecipe(
            user_id=user.id,
            recipe_id=recipe_one.id,
            saved_at=datetime(2026, 4, 25, 8, 0, 0),
        ))
        db.add(models.UserSavedRecipe(
            user_id=user.id,
            recipe_id=recipe_two.id,
            saved_at=datetime(2026, 4, 26, 8, 0, 0),
        ))
        db.commit()

        assert saved_recipes.count_for_user(db, user.id) == 1
        assert len(saved_recipes.list_for_user(db, user.id)) == 1

        existing = saved_recipes.save_on_select(db, user, recipe_three.id)
        db.flush()
        assert existing.recipe_id in {recipe_one.id, recipe_two.id}
        raw_saved_rows = (
            db.query(models.UserSavedRecipe)
            .filter(models.UserSavedRecipe.user_id == user.id)
            .count()
        )
        assert raw_saved_rows == 2
        db.commit()
    finally:
        db.close()

    response = client.get("/api/meal-plan/saved-recipes", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 1
    assert len(body["items"]) == 1

    visible_recipe_id = body["items"][0]["recipe"]["id"]
    delete_response = client.delete(
        f"/api/meal-plan/saved-recipes/{visible_recipe_id}",
        headers=headers,
    )
    assert delete_response.status_code == 200, delete_response.text
    assert delete_response.json()["count"] == 0

    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(username="saved_duplicate_owner").one()
        assert db.query(models.UserSavedRecipe).filter(
            models.UserSavedRecipe.user_id == user.id,
        ).count() == 0
    finally:
        db.close()
