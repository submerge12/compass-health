from __future__ import annotations

from services import recipe_suggester


def test_suggest_pool_names_matches_string_sketch_ids(monkeypatch):
    pool = [
        {
            "sketch_id": "breakfast-0",
            "meal_type": "breakfast",
            "day_type_affinities": [],
            "parts": [{"slug": "egg", "grams": 100.0}],
            "totals": {"kcal": 160, "protein_g": 12.0, "carbs_g": 2.0, "fat_g": 10.0},
            "ingredient_slugs": ["egg"],
        },
        {
            "sketch_id": "main-0",
            "meal_type": "main",
            "day_type_affinities": ["red_meat_day"],
            "parts": [{"slug": "beef", "grams": 140.0}],
            "totals": {"kcal": 320, "protein_g": 28.0, "carbs_g": 8.0, "fat_g": 18.0},
            "ingredient_slugs": ["beef"],
        },
    ]

    def _fake_call(batch: list[dict], language: str) -> dict:
        assert language == "zh"
        return {
            str(item["sketch_id"]): {
                "name": f"Dish for {item['sketch_id']}",
                "seasonings": [{"name": "salt", "grams": 2}],
                "method_steps": ["Prep ingredients", "Cook and serve"],
            }
            for item in batch
        }

    monkeypatch.setattr(recipe_suggester, "_call_llm_for_pool_batch", _fake_call)

    result = recipe_suggester.suggest_pool_names(pool, language="zh", batch_size=8)

    assert result["warnings"] == []
    assert [item["sketch_id"] for item in result["named_dishes"]] == [
        "breakfast-0",
        "main-0",
    ]
    assert [item["name"] for item in result["named_dishes"]] == [
        "Dish for breakfast-0",
        "Dish for main-0",
    ]
