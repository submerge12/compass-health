import models
from database import SessionLocal
from routers import preferences_routes
from services import food_library as FL


def test_all_known_preference_slugs_exist_in_food_library():
    known = {
        slug
        for slugs in preferences_routes.CATEGORY_ITEMS.values()
        for slug in slugs
    }

    assert sorted(known - set(FL.FOOD_LIBRARY)) == []


def test_nutrient_preference_groups_use_known_preference_slugs():
    groups = preferences_routes._nutrient_preference_groups()
    allowed = {
        slug
        for slugs in preferences_routes.CATEGORY_ITEMS.values()
        for slug in slugs
    }

    assert "iron" in groups
    assert "zinc" in groups
    assert "beef_tenderloin" in groups["iron"]
    assert "beef_tenderloin" in groups["zinc"]
    assert "red_beans" in groups["fiber"]
    assert "you_cai" in groups["calcium"]
    assert "dried_shrimp" in groups["calcium"]
    assert "sesame_paste" in groups["zinc"]
    assert all(slug in allowed for slugs in groups.values() for slug in slugs)


def test_food_preferences_get_keeps_custom_slug_in_known_category(client, clean_db):
    register_response = client.post(
        "/api/auth/register",
        json={"username": "custom-pref-user", "password": "pw12345"},
    )
    assert register_response.status_code == 201, register_response.text
    tokens = register_response.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    custom_slug = "pea_shoots"

    assert custom_slug not in preferences_routes.CATEGORY_ITEMS["vegetables"]

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.username == "custom-pref-user").one()
        db.add(
            models.FoodPreference(
                user_id=user.id,
                category="vegetables",
                item_key=custom_slug,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/preferences/food", headers=headers)

    assert response.status_code == 200, response.text
    assert custom_slug in response.json()["categories"]["vegetables"]
