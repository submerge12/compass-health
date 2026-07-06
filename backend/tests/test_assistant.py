from __future__ import annotations

import json

from tests.conftest import register


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_assistant_chat_requires_auth(client, clean_db):
    res = client.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert res.status_code == 401


def test_assistant_chat_without_bmr_guides_user_without_llm(client, clean_db):
    token = register(client, "assistant_no_bmr")["access_token"]
    res = client.post(
        "/api/assistant/chat",
        headers=_auth_headers(token),
        json={"messages": [{"role": "user", "content": "我这周缺什么？"}]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["tool_results"] == []
    assert body["proposed_actions"] == []
    assert "BMR" in body["reply"] or "身体目标" in body["reply"]


def test_search_food_library_maps_sea_bream_to_fish_candidates(client, clean_db):
    from services import assistant_tools

    result = assistant_tools.search_food_library("sea bream")
    slugs = [row["slug"] for row in result["candidates"]]
    assert "sea_bass" in slugs
    assert "tilapia" in slugs


def test_search_food_library_maps_domestic_dish_terms(client, clean_db):
    from services import assistant_tools

    result = assistant_tools.search_food_library("洋葱炒牛肉")
    slugs = [row["slug"] for row in result["candidates"]]
    assert "onion" in slugs
    assert "beef_tenderloin" in slugs


def test_evaluate_fat_loss_food_flags_craving_risk(client, clean_db):
    from database import SessionLocal
    import models
    from services import assistant_tools

    register(client, "assistant_craving")
    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(username="assistant_craving").one()
        result = assistant_tools.evaluate_fat_loss_food(db, user, "奶茶")
    finally:
        db.close()

    assert result["traffic_light_hint"] == "red"
    assert any(flag["code"] == "sugary_drink" for flag in result["risk_flags"])


def test_calculate_foods_uses_food_library_values(client, clean_db):
    from services import assistant_tools

    result = assistant_tools.calculate_foods([
        {"slug": "whole_egg", "grams": 100},
        {"slug": "milk", "grams": 200},
    ])
    totals = result["totals"]
    assert totals["kcal"] == 239.0
    assert totals["protein_g"] == 19.8
    assert totals["carbs_g"] == 11.1
    assert totals["fat_g"] == 13.0


def test_confirm_upsert_fixed_breakfast_creates_recipe_and_fixed_meal(client, clean_db):
    from database import SessionLocal
    import models
    from services import assistant_tools

    token = register(client, "assistant_breakfast")["access_token"]

    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(username="assistant_breakfast").one()
        action = assistant_tools.propose_action(
            db,
            user.id,
            assistant_tools.ACTION_UPSERT_FIXED_BREAKFAST,
            {
                "name": "2 eggs + 200ml milk",
                "ingredients": [
                    {"slug": "whole_egg", "grams": 120},
                    {"slug": "milk", "grams": 200},
                ],
            },
            "Set fixed breakfast to 2 eggs and 200ml milk.",
        )
        db.commit()
        action_id = action["id"]
    finally:
        db.close()

    res = client.post(
        f"/api/assistant/actions/{action_id}/confirm",
        headers=_auth_headers(token),
        json={},
    )
    assert res.status_code == 200, res.text

    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(username="assistant_breakfast").one()
        fixed = db.query(models.UserFixedMeal).filter_by(user_id=user.id, meal_type="breakfast").one()
        recipe = db.query(models.Recipe).filter_by(id=fixed.recipe_id).one()
        assert recipe.submitted_by == user.id
        assert recipe.is_approved is False
        assert json.loads(recipe.ingredients_json)[0]["slug"] == "whole_egg"
        assert fixed.calories == 270
        assert fixed.protein_g == 22.4
    finally:
        db.close()


def test_confirm_action_rejects_wrong_user_and_replay(client, clean_db):
    from database import SessionLocal
    import models
    from services import assistant_tools

    owner_token = register(client, "assistant_owner")["access_token"]
    other_token = register(client, "assistant_other")["access_token"]

    db = SessionLocal()
    try:
        owner = db.query(models.User).filter_by(username="assistant_owner").one()
        action = assistant_tools.propose_action(
            db,
            owner.id,
            assistant_tools.ACTION_SAVE_MEMORY,
            {"memory": {"milk_label": {"protein_g_per_100ml": 3.5}}},
            "Save milk label.",
        )
        db.commit()
        action_id = action["id"]
    finally:
        db.close()

    wrong = client.post(
        f"/api/assistant/actions/{action_id}/confirm",
        headers=_auth_headers(other_token),
        json={},
    )
    assert wrong.status_code == 403

    ok = client.post(
        f"/api/assistant/actions/{action_id}/confirm",
        headers=_auth_headers(owner_token),
        json={},
    )
    assert ok.status_code == 200

    replay = client.post(
        f"/api/assistant/actions/{action_id}/confirm",
        headers=_auth_headers(owner_token),
        json={},
    )
    assert replay.status_code == 409
