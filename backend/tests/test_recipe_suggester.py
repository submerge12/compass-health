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
                "commonality": {"is_common": True, "reason": "everyday home-style dish"},
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
    assert all(item["commonality"]["is_common"] for item in result["named_dishes"])


def test_suggest_pool_names_rejects_uncommon_or_unverified_names(monkeypatch):
    pool = [
        {
            "sketch_id": "main-0",
            "meal_type": "main",
            "day_type_affinities": [],
            "parts": [{"slug": "chicken_breast", "grams": 120.0}],
            "totals": {"kcal": 198, "protein_g": 37.2, "carbs_g": 0.0, "fat_g": 4.3},
            "ingredient_slugs": ["chicken_breast"],
        },
        {
            "sketch_id": "main-1",
            "meal_type": "main",
            "day_type_affinities": [],
            "parts": [{"slug": "chicken_breast", "grams": 120.0}],
            "totals": {"kcal": 198, "protein_g": 37.2, "carbs_g": 0.0, "fat_g": 4.3},
            "ingredient_slugs": ["chicken_breast"],
        },
        {
            "sketch_id": "main-2",
            "meal_type": "main",
            "day_type_affinities": [],
            "parts": [{"slug": "chicken_breast", "grams": 120.0}],
            "totals": {"kcal": 198, "protein_g": 37.2, "carbs_g": 0.0, "fat_g": 4.3},
            "ingredient_slugs": ["chicken_breast"],
        },
    ]

    def _fake_call(batch: list[dict], language: str) -> dict:
        return {
            "main-0": {
                "name": "青椒鸡胸肉",
                "commonality": {"is_common": True, "reason": "家常炒菜"},
                "seasonings": [{"name": "生抽", "grams": 5}],
                "method_steps": ["切配", "炒熟"],
            },
            "main-1": {
                "name": "奇异莓鸡胸慕斯",
                "commonality": {"is_common": False, "reason": "不是常见家常菜"},
                "seasonings": [],
                "method_steps": ["混合", "冷藏"],
            },
            "main-2": {
                "name": "未验证鸡胸组合",
                "seasonings": [],
                "method_steps": ["烹饪"],
            },
        }

    monkeypatch.setattr(recipe_suggester, "_call_llm_for_pool_batch", _fake_call)

    result = recipe_suggester.suggest_pool_names(pool, language="zh", batch_size=8)

    assert [item["sketch_id"] for item in result["named_dishes"]] == ["main-0"]
    assert len(result["warnings"]) == 2
    assert all("uncommon or unverified" in warning for warning in result["warnings"])


def test_clean_candidate_requires_commonality():
    slot = {
        "slot_key": "2026-05-19/main",
        "target_kcal": 200,
        "target_protein_g": 30,
        "target_carbs_g": 0,
        "target_fat_g": 5,
    }
    candidate = {
        "name": "清炒鸡胸肉",
        "commonality": {"is_common": True, "reason": "家常做法"},
        "ingredients": [{"slug": "chicken_breast", "grams": 120}],
        "seasonings": [{"name": "生抽", "grams": 5}],
        "method_steps": ["切片腌制", "热锅快炒"],
    }

    cleaned = recipe_suggester._clean_candidate(candidate, slot, {"chicken_breast"})

    assert cleaned is not None
    assert cleaned["commonality"]["is_common"] is True

    uncommon = dict(candidate)
    uncommon["commonality"] = {"is_common": False, "reason": "不常见"}

    assert recipe_suggester._clean_candidate(uncommon, slot, {"chicken_breast"}) is None
    assert recipe_suggester._reject_reason(uncommon, {"chicken_breast"}).startswith(
        "not_common_or_missing_commonality"
    )


def test_recipe_prompts_require_commonality():
    pool_prompt, _ = recipe_suggester._build_pool_prompt([], "zh")
    day_prompt, _ = recipe_suggester._build_day_prompt(
        "2026-05-19", [], ["chicken_breast"], "zh", 1
    )

    assert "commonality.is_common" in pool_prompt
    assert "commonality.is_common" in day_prompt
