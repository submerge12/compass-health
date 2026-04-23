from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect

from tests.conftest import register


@pytest.fixture(autouse=True)
def clean_meal_plan_tables(client):
    from database import SessionLocal
    import models

    db = SessionLocal()
    inspector = inspect(db.bind)
    for table in (
        models.AdminAuditLog,
        models.LLMCallLog,
        models.DailyMealPlanConfirmation,
        models.UserSavedRecipe,
        models.UserFixedMeal,
        models.MealPlanEntry,
        models.DietLog,
        models.FoodPreference,
        models.DailyActivityPlan,
        models.BMRProfile,
        models.RefreshToken,
        models.Membership,
        models.UserSettings,
        models.Recipe,
        models.User,
    ):
        if not inspector.has_table(table.__tablename__):
            continue
        db.query(table).delete()
    db.commit()
    db.close()
    yield


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_profile_and_library(username: str) -> None:
    from database import SessionLocal
    import models
    from services import calorie as calorie_svc
    from services import food_library as FL

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.username == username).one()
        bmr = calorie_svc.compute_bmr(30, "female", 165.0, 60.0)
        tdee = calorie_svc.compute_tdee(bmr, "lightly_active")
        db.add(models.BMRProfile(
            user_id=user.id,
            age=30,
            gender="female",
            height_cm=165.0,
            weight_kg=60.0,
            activity_level="lightly_active",
            goal="maintain",
            bmr_value=bmr,
            tdee_value=tdee,
        ))
        for slug in FL.FOOD_LIBRARY.keys():
            db.add(models.FoodPreference(
                user_id=user.id,
                category="all",
                item_key=slug,
            ))
        db.commit()
    finally:
        db.close()


def _seed_everyday_fixed_meal(
    username: str,
    meal_type: str,
    *,
    recipe_name: str,
    calories: int,
    protein_g: float,
    carbs_g: float,
    fat_g: float,
) -> None:
    from database import SessionLocal
    import models
    from services import food_library as FL

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.username == username).one()
        structured_ingredients = [
            {"slug": slug, "grams": 10.0, "required": True}
            for slug in FL.FOOD_LIBRARY.keys()
        ]
        recipe = models.Recipe(
            name=recipe_name,
            ingredients="\n".join(f"{item['slug']} {item['grams']}g" for item in structured_ingredients),
            ingredients_json=json.dumps(structured_ingredients, ensure_ascii=False),
            ingredient_slugs=json.dumps([item["slug"] for item in structured_ingredients], ensure_ascii=False),
            meal_types=meal_type,
            calories=calories,
            protein_g=protein_g,
            carbs_g=carbs_g,
            fat_g=fat_g,
            serving_g=180.0,
            is_builtin=False,
            submitted_by=user.id,
            is_approved=True,
        )
        db.add(recipe)
        db.flush()
        db.add(models.UserFixedMeal(
            user_id=user.id,
            weekday=None,
            meal_type=meal_type,
            recipe_id=recipe.id,
            portion_g=180.0,
            calories=calories,
            protein_g=protein_g,
            carbs_g=carbs_g,
            fat_g=fat_g,
        ))
        db.commit()
    finally:
        db.close()


def _seed_everyday_fixed_breakfast(username: str) -> None:
    _seed_everyday_fixed_meal(
        username,
        "breakfast",
        recipe_name="Fixed breakfast",
        calories=220,
        protein_g=16.0,
        carbs_g=12.0,
        fat_g=10.0,
    )


def _seed_everyday_fixed_main_slots(username: str) -> None:
    _seed_everyday_fixed_meal(
        username,
        "lunch",
        recipe_name="Fixed lunch",
        calories=520,
        protein_g=32.0,
        carbs_g=48.0,
        fat_g=18.0,
    )
    _seed_everyday_fixed_meal(
        username,
        "dinner",
        recipe_name="Fixed dinner",
        calories=560,
        protein_g=34.0,
        carbs_g=42.0,
        fat_g=22.0,
    )


def _pool_body(pool: dict) -> dict:
    return {
        "breakfast_dishes": [
            {
                "dish_id": str(item.get("sketch_id", idx)),
                "meal_type": "breakfast",
                "name": f"Breakfast {idx}",
                "ingredients": [
                    {"slug": ing["slug"], "grams": ing["grams"]}
                    for ing in item.get("parts", [])
                ],
                "totals": item.get("totals", {}),
                "ingredient_slugs": item.get("ingredient_slugs", []),
                "day_type_affinities": item.get("day_type_affinities", []),
                "method_steps": "1. Combine ingredients\n2. Cook and serve",
                "seasonings": [],
            }
            for idx, item in enumerate(pool.get("breakfast_pool", []))
        ],
        "main_dishes": [
            {
                "dish_id": str(item.get("sketch_id", idx)),
                "meal_type": "main",
                "name": f"Main {idx}",
                "ingredients": [
                    {"slug": ing["slug"], "grams": ing["grams"]}
                    for ing in item.get("parts", [])
                ],
                "totals": item.get("totals", {}),
                "ingredient_slugs": item.get("ingredient_slugs", []),
                "day_type_affinities": item.get("day_type_affinities", []),
                "method_steps": "1. Prep ingredients\n2. Cook and serve",
                "seasonings": [],
            }
            for idx, item in enumerate(pool.get("main_pool", []))
        ],
    }


def test_pool_uses_unique_string_sketch_ids(client):
    auth = register(client, "pool_ids_user")
    _seed_profile_and_library("pool_ids_user")
    headers = _auth_headers(auth["access_token"])

    pool_resp = client.get("/api/meal-plan/pool", headers=headers)
    assert pool_resp.status_code == 200, pool_resp.text
    pool = pool_resp.json()

    sketch_ids = [
        item["sketch_id"]
        for item in pool.get("breakfast_pool", []) + pool.get("main_pool", [])
    ]

    assert sketch_ids
    assert all(isinstance(sid, str) for sid in sketch_ids)
    assert len(sketch_ids) == len(set(sketch_ids))
    assert all("-" in sid for sid in sketch_ids)


def test_arrange_meal_plan_persists_week(client):
    auth = register(client, "planner_user")
    _seed_profile_and_library("planner_user")
    headers = _auth_headers(auth["access_token"])

    pool_resp = client.get("/api/meal-plan/pool", headers=headers)
    assert pool_resp.status_code == 200, pool_resp.text
    pool = pool_resp.json()

    arrange_resp = client.post(
        "/api/meal-plan/arrange",
        headers=headers,
        json=_pool_body(pool),
    )
    assert arrange_resp.status_code == 200, arrange_resp.text
    body = arrange_resp.json()
    assert body["arranged_entry_count"] > 0
    assert len(body["days"]) == 7
    assert body["weekly_totals"]["kcal"] > 0

    from database import SessionLocal
    import models

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.username == "planner_user").one()
        entries = db.query(models.MealPlanEntry).filter(models.MealPlanEntry.user_id == user.id).all()
        assert entries
        assert all(entry.status == "generated" for entry in entries)
    finally:
        db.close()


def test_arrange_meal_plan_skips_fixed_breakfast_slots(client):
    auth = register(client, "fixed_breakfast_user")
    _seed_profile_and_library("fixed_breakfast_user")
    _seed_everyday_fixed_breakfast("fixed_breakfast_user")
    headers = _auth_headers(auth["access_token"])

    pool_resp = client.get("/api/meal-plan/pool", headers=headers)
    assert pool_resp.status_code == 200, pool_resp.text

    arrange_resp = client.post(
        "/api/meal-plan/arrange",
        headers=headers,
        json=_pool_body(pool_resp.json()),
    )
    assert arrange_resp.status_code == 200, arrange_resp.text
    body = arrange_resp.json()

    breakfast_sources = [day["meals"].get("breakfast", {}).get("source") for day in body["days"]]
    assert breakfast_sources
    assert all(source == "fixed" for source in breakfast_sources)

    from database import SessionLocal
    import models

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.username == "fixed_breakfast_user").one()
        breakfast_entries = (
            db.query(models.MealPlanEntry)
            .filter(
                models.MealPlanEntry.user_id == user.id,
                models.MealPlanEntry.meal_type == "breakfast",
            )
            .count()
        )
        assert breakfast_entries == 0
    finally:
        db.close()


def test_pool_marks_breakfast_optional_when_breakfast_is_fixed_all_week(client):
    auth = register(client, "pool_fixed_breakfast_user")
    _seed_profile_and_library("pool_fixed_breakfast_user")
    _seed_everyday_fixed_breakfast("pool_fixed_breakfast_user")
    headers = _auth_headers(auth["access_token"])

    pool_resp = client.get("/api/meal-plan/pool", headers=headers)
    assert pool_resp.status_code == 200, pool_resp.text
    body = pool_resp.json()
    assert body["required_slot_counts"]["breakfast"] == 0
    assert body["requires_breakfast_pool"] is False
    assert body["requires_main_pool"] is True


def test_arrange_allows_empty_breakfast_pool_when_breakfast_is_fixed_all_week(client):
    auth = register(client, "fixed_only_breakfast_user")
    _seed_profile_and_library("fixed_only_breakfast_user")
    _seed_everyday_fixed_breakfast("fixed_only_breakfast_user")
    headers = _auth_headers(auth["access_token"])

    pool_resp = client.get("/api/meal-plan/pool", headers=headers)
    assert pool_resp.status_code == 200, pool_resp.text
    pool = _pool_body(pool_resp.json())
    pool["breakfast_dishes"] = []

    arrange_resp = client.post(
        "/api/meal-plan/arrange",
        headers=headers,
        json=pool,
    )
    assert arrange_resp.status_code == 200, arrange_resp.text
    body = arrange_resp.json()
    assert all(day["meals"].get("breakfast", {}).get("source") == "fixed" for day in body["days"])


def test_arrange_allows_empty_main_pool_when_lunch_and_dinner_are_fixed_all_week(client):
    auth = register(client, "fixed_main_pool_user")
    _seed_profile_and_library("fixed_main_pool_user")
    _seed_everyday_fixed_main_slots("fixed_main_pool_user")
    headers = _auth_headers(auth["access_token"])

    pool_resp = client.get("/api/meal-plan/pool", headers=headers)
    assert pool_resp.status_code == 200, pool_resp.text
    pool = _pool_body(pool_resp.json())
    assert pool_resp.json()["required_slot_counts"]["lunch"] == 0
    assert pool_resp.json()["required_slot_counts"]["dinner"] == 0
    pool["main_dishes"] = []

    arrange_resp = client.post(
        "/api/meal-plan/arrange",
        headers=headers,
        json=pool,
    )
    assert arrange_resp.status_code == 200, arrange_resp.text
    body = arrange_resp.json()
    assert all(day["meals"].get("lunch", {}).get("source") == "fixed" for day in body["days"])
    assert all(day["meals"].get("dinner", {}).get("source") == "fixed" for day in body["days"])
