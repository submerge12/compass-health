from __future__ import annotations

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
