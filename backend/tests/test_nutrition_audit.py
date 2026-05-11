from services import food_library as FL
from services import nutrition_audit


def test_sufficiency_gap_generates_actionable_suggestion():
    role = next(
        role for role in FL.MICRONUTRIENT_ROLES
        if FL.slugs_by_micronutrient(role)
    )
    first_carrier = FL.slugs_by_micronutrient(role)[0]
    meta = FL.MICRONUTRIENT_ROLES[role]
    validation = {bucket: ["covered"] for bucket in FL.VALIDATION_BUCKETS}
    micronutrients = {
        role: {
            "status": "sufficient",
            "carriers": [first_carrier],
            "label_zh": meta["zh"],
            "label_en": meta["en"],
        }
    }
    sufficiency = {
        role: {
            "status": "impractical",
            "label_zh": meta["zh"],
            "label_en": meta["en"],
            "best_coverage_pct": 4.0,
            "carriers": [{"slug": first_carrier}],
        }
    }

    suggestions = nutrition_audit._suggestions(validation, micronutrients, sufficiency)

    assert any(
        item["kind"] == "sufficiency"
        and item["ref"] == role
        and item["resolution"] == "add_concentrated_source"
        for item in suggestions
    )
