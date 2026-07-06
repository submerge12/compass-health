from __future__ import annotations

from itertools import product
from types import SimpleNamespace

from services import menu_planner


def test_missing_micronutrient_guidance_returns_recommendations():
    weekly_micro_report = {
        "calcium": {
            "label_zh": "钙",
            "label_en": "Calcium",
            "unit": "mg",
            "actual": 0.0,
            "target": 5600.0,
            "status": "missing",
            "carriers": [],
        },
        "iron": {
            "label_zh": "铁",
            "label_en": "Iron",
            "unit": "mg",
            "actual": 180.0,
            "target": 140.0,
            "status": "ok",
            "carriers": ["beef_tenderloin"],
        },
    }

    guidance = menu_planner._missing_micronutrient_guidance(weekly_micro_report)

    assert [item["role"] for item in guidance["missing_micronutrients"]] == ["calcium"]
    assert guidance["missing_micronutrients"][0]["gap"] == 5600.0
    assert guidance["missing_micronutrients"][0]["recommended_foods"]
    assert guidance["recommended_foods"]
    assert all(item["slug"] for item in guidance["recommended_foods"])


def _fake_main_dish(idx: int) -> dict:
    return {
        "name": f"Dish {idx:02d}",
        "signature": f"dish-{idx:02d}",
        "ingredient_slugs": [f"ingredient-{idx:02d}"],
        "bucket_set": set(),
        "day_type_affinities": [],
        "totals": {
            "kcal": 400.0 + idx * 30.0,
            "protein_g": 30.0 + idx * 2.0,
            "carbs_g": 40.0 + idx * 3.0,
            "fat_g": 12.0 + idx,
        },
        "nutrients": {},
    }


def test_main_combinations_preserves_exhaustive_small_pool():
    dishes = [_fake_main_dish(idx) for idx in range(4)]
    target = SimpleNamespace(calories=800.0, protein=60.0, carbs=80.0, fat=24.0)

    combinations = menu_planner._main_combinations(
        dishes,
        2,
        remaining_target=target,
        day_type="moderate_activity",
    )

    assert combinations == list(product(dishes, repeat=2))


def test_main_combinations_caps_large_pool_to_top_scored_dishes():
    dishes = [_fake_main_dish(idx) for idx in range(20)]
    target = SimpleNamespace(calories=800.0, protein=60.0, carbs=80.0, fat=24.0)

    combinations = menu_planner._main_combinations(
        dishes,
        2,
        remaining_target=target,
        day_type="moderate_activity",
    )

    selected_names = {
        dish["name"]
        for combination in combinations
        for dish in combination
    }
    assert len(combinations) == 12 * 12
    assert selected_names == {f"Dish {idx:02d}" for idx in range(12)}


def test_route_pool_helpers_use_menu_planner_canonical_helpers(monkeypatch):
    from routers import meal_plan_routes

    assert menu_planner.pool_source_label("recipe_library") == "Recipe library"
    assert menu_planner.day_type_affinities_for_slugs(
        ["beef_tenderloin", "salmon", "oats", "rice"]
    ) == [
        "red_meat_day",
        "deep_sea_fish_day",
        "low_activity",
        "high_activity",
    ]

    monkeypatch.setattr(
        menu_planner,
        "pool_source_label",
        lambda source: f"canonical:{source}",
    )
    assert meal_plan_routes._stamp_pool_dish(
        {"source": "recipe_library"}
    )["source_label"] == "canonical:recipe_library"

    monkeypatch.setattr(
        menu_planner,
        "day_type_affinities_for_slugs",
        lambda slugs: ["canonical_affinity"],
    )
    recipe = SimpleNamespace(
        id=42,
        name="Route helper candidate",
        calories=410,
        protein_g=32.0,
        carbs_g=46.0,
        fat_g=11.0,
        steps="Cook and serve",
    )
    candidate = meal_plan_routes._recipe_to_pool_candidate(
        recipe,
        "main",
        [{"slug": "rice", "grams": 60.0}],
    )
    assert candidate["source_label"] == "canonical:recipe_library"
    assert candidate["day_type_affinities"] == ["canonical_affinity"]
