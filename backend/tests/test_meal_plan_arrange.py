from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

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
        models.PhysicalCondition,
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


def _user_id(username: str) -> int:
    from database import SessionLocal
    import models

    db = SessionLocal()
    try:
        return db.query(models.User).filter(models.User.username == username).one().id
    finally:
        db.close()


def _structured_ingredients(slugs: list[str], grams: float = 40.0) -> list[dict]:
    return [
        {"slug": slug, "grams": grams, "required": True}
        for slug in slugs
    ]


def _macro_totals(ingredients: list[dict]) -> dict[str, float]:
    from services import food_library as FL

    totals = {"kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    for item in ingredients:
        slug = item["slug"]
        grams = float(item.get("grams") or 0)
        food = FL.FOOD_LIBRARY[slug]
        factor = grams / 100.0
        totals["kcal"] += food["kcal_per_100g"] * factor
        totals["protein_g"] += food["protein_per_100g"] * factor
        totals["carbs_g"] += food["carbs_per_100g"] * factor
        totals["fat_g"] += food["fat_per_100g"] * factor
    return {key: round(value, 1) for key, value in totals.items()}


def _coverage_slugs() -> list[str]:
    from services import food_library as FL

    slugs = [
        "rice",
        "chicken_breast",
        "beef_tenderloin",
        "salmon",
        "milk",
        "spinach",
        "almonds",
        "whole_egg",
    ]
    for role in FL.MICRONUTRIENT_ROLES:
        for slug in FL.slugs_by_micronutrient(role):
            if slug not in slugs:
                slugs.append(slug)
                break
    for bucket in ("red_meat", "deep_sea_fish"):
        for slug in FL.slugs_by_execution_bucket(bucket):
            if slug not in slugs:
                slugs.append(slug)
                break
    return slugs


def _seed_recipe(
    username: str,
    *,
    name: str,
    meal_types: str,
    slugs: list[str],
    is_approved: bool = True,
    submitted_by_current_user: bool = False,
    structured: bool = True,
) -> int:
    from database import SessionLocal
    import models

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.username == username).one()
        ingredients = _structured_ingredients(slugs)
        totals = _macro_totals(ingredients)
        recipe = models.Recipe(
            name=name,
            ingredients="\n".join(f"{item['slug']} {item['grams']}g" for item in ingredients),
            steps="1. Prep ingredients\n2. Cook and serve",
            meal_types=meal_types,
            calories=int(round(totals["kcal"])),
            protein_g=totals["protein_g"],
            carbs_g=totals["carbs_g"],
            fat_g=totals["fat_g"],
            serving_g=sum(float(item["grams"]) for item in ingredients),
            ingredient_slugs=json.dumps(slugs, ensure_ascii=False),
            ingredients_json=json.dumps(ingredients, ensure_ascii=False) if structured else None,
            is_builtin=False,
            submitted_by=user.id if submitted_by_current_user else None,
            is_approved=is_approved,
        )
        db.add(recipe)
        db.commit()
        return recipe.id
    finally:
        db.close()


def _remove_food_from_user_library(username: str, slug: str) -> None:
    from database import SessionLocal
    import models

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.username == username).one()
        pref = (
            db.query(models.FoodPreference)
            .filter(
                models.FoodPreference.user_id == user.id,
                models.FoodPreference.item_key == slug,
            )
            .first()
        )
        if pref is not None:
            db.delete(pref)
            db.commit()
    finally:
        db.close()


def _pool_candidates(pool: dict) -> list[dict]:
    candidates: list[dict] = []
    for key in ("breakfast_pool", "main_pool", "breakfast_dishes", "main_dishes"):
        candidates.extend(item for item in pool.get(key, []) if isinstance(item, dict))
    return candidates


def _candidate_by_recipe_id(pool: dict, recipe_id: int, *, meal_type: str | None = None) -> dict | None:
    for item in _pool_candidates(pool):
        try:
            item_recipe_id = int(item.get("recipe_id"))
        except (TypeError, ValueError):
            continue
        if item_recipe_id != recipe_id:
            continue
        if meal_type is not None and item.get("meal_type") != meal_type:
            continue
        return item
    return None


def _pool_dish_payload(item: dict, idx: int, meal_type: str) -> dict:
    ingredients = item.get("ingredients") or [
        {"slug": ing["slug"], "grams": ing["grams"]}
        for ing in item.get("parts", [])
    ]
    return {
        "dish_id": str(item.get("dish_id") or item.get("sketch_id") or item.get("recipe_id") or idx),
        "recipe_id": item.get("recipe_id"),
        "source": item.get("source"),
        "meal_type": meal_type,
        "name": item.get("name") or f"{meal_type.title()} {idx}",
        "ingredients": ingredients,
        "totals": item.get("totals") or _macro_totals(ingredients),
        "ingredient_slugs": item.get("ingredient_slugs") or [ing["slug"] for ing in ingredients],
        "day_type_affinities": item.get("day_type_affinities", []),
        "method_steps": item.get("method_steps") or item.get("steps") or "1. Cook and serve",
        "seasonings": item.get("seasonings", []),
    }


def _manual_pool_dish(name: str, meal_type: str, slugs: list[str]) -> dict:
    ingredients = _structured_ingredients(slugs, grams=60.0)
    return _pool_dish_payload(
        {
            "sketch_id": f"manual-{meal_type}-{name}",
            "meal_type": meal_type,
            "source": "generated",
            "name": name,
            "ingredients": ingredients,
            "totals": _macro_totals(ingredients),
            "ingredient_slugs": slugs,
            "method_steps": "1. Cook and serve",
        },
        0,
        meal_type,
    )


def _pool_name_used(username: str) -> int:
    from database import SessionLocal
    from services import llm_quota

    db = SessionLocal()
    try:
        return llm_quota.usage(db, _user_id(username), llm_quota.POOL_NAME)["used"]
    finally:
        db.close()


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
            _pool_dish_payload({**item, "name": item.get("name") or f"Breakfast {idx}"}, idx, "breakfast")
            for idx, item in enumerate(pool.get("breakfast_pool", []))
        ],
        "main_dishes": [
            _pool_dish_payload({**item, "name": item.get("name") or f"Main {idx}"}, idx, "main")
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


def test_pool_includes_only_visible_structured_library_recipes(client):
    auth = register(client, "pool_library_user")
    _seed_profile_and_library("pool_library_user")
    _remove_food_from_user_library("pool_library_user", "peanuts")
    headers = _auth_headers(auth["access_token"])

    visible_id = _seed_recipe(
        "pool_library_user",
        name="Visible library oats",
        meal_types="breakfast",
        slugs=["oats", "milk", "whole_egg"],
    )
    hidden_id = _seed_recipe(
        "pool_library_user",
        name="Hidden library oats",
        meal_types="breakfast",
        slugs=["oats", "milk", "whole_egg"],
        is_approved=False,
    )
    unstructured_id = _seed_recipe(
        "pool_library_user",
        name="Unstructured library oats",
        meal_types="breakfast",
        slugs=["oats", "milk", "whole_egg"],
        structured=False,
    )
    outside_library_id = _seed_recipe(
        "pool_library_user",
        name="Outside pantry peanuts",
        meal_types="breakfast",
        slugs=["peanuts"],
    )

    pool_resp = client.get("/api/meal-plan/pool", headers=headers)
    assert pool_resp.status_code == 200, pool_resp.text
    pool = pool_resp.json()

    recipe_candidates = {
        int(item["recipe_id"]): item
        for item in _pool_candidates(pool)
        if item.get("recipe_id") is not None
    }
    assert visible_id in recipe_candidates
    assert recipe_candidates[visible_id]["source"] == "recipe_library"
    assert hidden_id not in recipe_candidates
    assert unstructured_id not in recipe_candidates
    assert outside_library_id not in recipe_candidates


def test_pool_endpoints_dedupe_duplicate_library_candidates(client, monkeypatch):
    auth = register(client, "pool_duplicate_library_user")
    _seed_profile_and_library("pool_duplicate_library_user")
    headers = _auth_headers(auth["access_token"])

    breakfast_ids = {
        _seed_recipe(
            "pool_duplicate_library_user",
            name="Duplicate oats breakfast",
            meal_types="breakfast",
            slugs=["oats", "milk", "whole_egg"],
        )
        for _ in range(3)
    }
    main_ids = {
        _seed_recipe(
            "pool_duplicate_library_user",
            name="Duplicate chicken plate",
            meal_types="lunch,dinner",
            slugs=["chicken_breast", "potato", "spinach", "carrot"],
        )
        for _ in range(3)
    }

    def matches_recipe_ids(items: list[dict], recipe_ids: set[int]) -> list[dict]:
        return [
            item
            for item in items
            if item.get("source") == "recipe_library"
            and item.get("recipe_id") in recipe_ids
        ]

    pool_resp = client.get("/api/meal-plan/pool", headers=headers)
    assert pool_resp.status_code == 200, pool_resp.text
    pool = pool_resp.json()
    assert len(matches_recipe_ids(pool.get("breakfast_pool", []), breakfast_ids)) == 1
    assert len(matches_recipe_ids(pool.get("main_pool", []), main_ids)) == 1

    def fake_suggest_pool_names(pool, language="zh", batch_size=None):
        named = []
        for idx, sketch in enumerate(pool):
            parts = sketch.get("parts") or sketch.get("ingredients") or []
            named.append({
                **sketch,
                "name": f"Generated {idx}",
                "ingredients": [
                    {"slug": item["slug"], "grams": item["grams"]}
                    for item in parts
                ],
                "seasonings": [],
                "method_steps": "1. Cook and serve",
            })
        return {"named_dishes": named, "warnings": []}

    from services import recipe_suggester

    monkeypatch.setattr(recipe_suggester, "suggest_pool_names", fake_suggest_pool_names)

    named_resp = client.post("/api/meal-plan/pool/name", headers=headers)
    assert named_resp.status_code == 200, named_resp.text
    named = named_resp.json()
    assert len(matches_recipe_ids(named.get("breakfast_dishes", []), breakfast_ids)) == 1
    assert len(matches_recipe_ids(named.get("main_dishes", []), main_ids)) == 1


def test_arrange_recipe_library_candidate_reuses_original_recipe_and_saves(client):
    auth = register(client, "arrange_library_user")
    _seed_profile_and_library("arrange_library_user")
    headers = _auth_headers(auth["access_token"])

    breakfast_recipe_id = _seed_recipe(
        "arrange_library_user",
        name="Library coverage breakfast",
        meal_types="breakfast",
        slugs=_coverage_slugs(),
    )
    main_recipe_id = _seed_recipe(
        "arrange_library_user",
        name="Library coverage main",
        meal_types="lunch,dinner",
        slugs=_coverage_slugs(),
    )

    pool_resp = client.get("/api/meal-plan/pool", headers=headers)
    assert pool_resp.status_code == 200, pool_resp.text
    pool = pool_resp.json()
    breakfast_candidate = _candidate_by_recipe_id(pool, breakfast_recipe_id, meal_type="breakfast")
    main_candidate = _candidate_by_recipe_id(pool, main_recipe_id, meal_type="main")
    assert breakfast_candidate is not None
    assert main_candidate is not None

    from database import SessionLocal
    import models

    db = SessionLocal()
    try:
        recipe_count_before = db.query(models.Recipe).count()
    finally:
        db.close()

    arrange_resp = client.post(
        "/api/meal-plan/arrange",
        headers=headers,
        json={
            "breakfast_dishes": [_pool_dish_payload(breakfast_candidate, 0, "breakfast")],
            "main_dishes": [_pool_dish_payload(main_candidate, 0, "main")],
        },
    )
    assert arrange_resp.status_code == 200, arrange_resp.text

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.username == "arrange_library_user").one()
        entries = (
            db.query(models.MealPlanEntry)
            .filter(models.MealPlanEntry.user_id == user.id)
            .all()
        )
        assert entries
        assert db.query(models.Recipe).count() == recipe_count_before
        assert {entry.recipe_id for entry in entries} <= {breakfast_recipe_id, main_recipe_id}
        assert all(entry.status == "recipe" for entry in entries)
        saved_recipe_ids = {
            row.recipe_id
            for row in (
                db.query(models.UserSavedRecipe)
                .filter(models.UserSavedRecipe.user_id == user.id)
                .all()
            )
        }
        assert {breakfast_recipe_id, main_recipe_id} <= saved_recipe_ids
    finally:
        db.close()


def test_pool_supplement_returns_supplement_candidates_without_pool_name_quota(client, monkeypatch):
    auth = register(client, "supplement_pool_user")
    _seed_profile_and_library("supplement_pool_user")
    headers = _auth_headers(auth["access_token"])

    def fake_suggest_pool_names(pool, language="zh", batch_size=None):
        named = []
        for idx, sketch in enumerate(pool):
            parts = sketch.get("parts") or sketch.get("ingredients") or []
            named.append({
                **sketch,
                "source": "supplement",
                "name": f"Supplement {idx}",
                "ingredients": [
                    {"slug": item["slug"], "grams": item["grams"]}
                    for item in parts
                ],
                "seasonings": [],
                "method_steps": "1. Cook and serve",
            })
        return {"named_dishes": named, "warnings": []}

    from services import recipe_suggester

    monkeypatch.setattr(recipe_suggester, "suggest_pool_names", fake_suggest_pool_names)

    before = _pool_name_used("supplement_pool_user")
    response = client.post(
        "/api/meal-plan/pool/supplement",
        headers=headers,
        json={
            "selected_food_slugs": ["salmon"],
            "missing_roles": ["omega3"],
            "required_buckets": ["deep_sea_fish"],
            "variant": 0,
        },
    )
    after = _pool_name_used("supplement_pool_user")

    assert response.status_code == 200, response.text
    assert after == before
    body = response.json()
    candidates = _pool_candidates(body)
    assert candidates
    assert all(item.get("source") == "supplement" for item in candidates)
    if "llm_quota" in body:
        assert body["llm_quota"]["kind"] == "pool_name"
        assert body["llm_quota"]["used"] == before
    if "quota_waived" in body:
        assert body["quota_waived"]["kind"] == "pool_name"


def test_pool_supplement_naming_failure_does_not_consume_pool_name_quota(client, monkeypatch):
    auth = register(client, "supplement_failure_user")
    _seed_profile_and_library("supplement_failure_user")
    headers = _auth_headers(auth["access_token"])

    def fail_pool_names(pool, language="zh", batch_size=None):
        raise RuntimeError("naming down")

    from services import recipe_suggester

    monkeypatch.setattr(recipe_suggester, "suggest_pool_names", fail_pool_names)

    before = _pool_name_used("supplement_failure_user")
    response = client.post(
        "/api/meal-plan/pool/supplement",
        headers=headers,
        json={
            "selected_food_slugs": ["salmon"],
            "missing_roles": ["omega3"],
            "required_buckets": ["deep_sea_fish"],
            "variant": 0,
        },
    )
    after = _pool_name_used("supplement_failure_user")

    assert response.status_code in (200, 502), response.text
    assert after == before


def test_arrange_gap_response_includes_supplement_guidance(client):
    auth = register(client, "gap_guidance_user")
    _seed_profile_and_library("gap_guidance_user")
    headers = _auth_headers(auth["access_token"])

    arrange_resp = client.post(
        "/api/meal-plan/arrange",
        headers=headers,
        json={
            "breakfast_dishes": [
                _manual_pool_dish("Simple breakfast", "breakfast", ["oats", "milk", "whole_egg"]),
            ],
            "main_dishes": [
                _manual_pool_dish("No reinforcement main", "main", ["rice", "chicken_breast", "spinach"]),
            ],
        },
    )

    assert arrange_resp.status_code == 400, arrange_resp.text
    detail = arrange_resp.json()["detail"]
    assert detail["error"] in {
        "selection_cannot_cover_reinforcement_day",
        "weekly_micronutrients_missing",
    }
    assert detail.get("recommended_foods") or detail.get("required_buckets")


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
        saved_count = (
            db.query(models.UserSavedRecipe)
            .filter(models.UserSavedRecipe.user_id == user.id)
            .count()
        )
        assert saved_count > 0
    finally:
        db.close()

    procurement_resp = client.post(
        "/api/meal-engine/procurement",
        headers=headers,
        json={"start_date": body["start_date"]},
    )
    assert procurement_resp.status_code == 200, procurement_resp.text
    procurement = procurement_resp.json()
    assert procurement["total_slugs"] > 0
    assert procurement["total_planned_g"] > 0
    assert not any("generated slot" in warning for warning in procurement.get("warnings", []))


def test_week_plan_starts_today_and_slides_forward(client):
    auth = register(client, "week_window_user")
    headers = _auth_headers(auth["access_token"])

    response = client.get("/api/meal-plan/week", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    from services import local_dates

    expected_dates = local_dates.date_range_starting_today(7)
    assert body["today"] == expected_dates[0]
    assert [day["date"] for day in body["days"]] == expected_dates


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
