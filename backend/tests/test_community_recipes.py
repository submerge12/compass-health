from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from tests.conftest import register


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _payload() -> dict:
    return {
        "name": "西兰花炒鸡胸肉",
        "servings": 1,
        "ingredients": "鸡胸肉 160g\n西兰花 220g\n食用油 6g\n生抽 8g\n蒜 5g",
        "steps": "1. 西兰花焯水。\n2. 鸡胸肉切片腌制。\n3. 不粘锅少油快炒，加入西兰花翻匀。",
    }


def test_analyze_community_recipe_scores_low_fat_fit(client, clean_db):
    auth = register(client, "community_author")

    res = client.post(
        "/api/recipes/community/analyze",
        headers=_headers(auth["access_token"]),
        json=_payload(),
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["score"] >= 70
    assert body["traffic_light"] == "green"
    assert body["estimated_nutrition_per_serving"]["coverage"] == "estimated"
    assert body["suggestions"]


def test_submitted_community_recipe_stays_pending_until_approval(client, clean_db):
    author = register(client, "community_author_2")
    reviewer = register(client, "community_reviewer")

    create = client.post(
        "/api/recipes/community",
        headers=_headers(author["access_token"]),
        json=_payload(),
    )
    assert create.status_code == 200, create.text
    recipe = create.json()
    assert recipe["community_status"] == "pending"
    assert recipe["is_approved"] is False
    assert recipe["low_fat_score"] >= 70
    assert recipe["community_rating_count"] == 0

    listing = client.get(
        "/api/recipes/community",
        headers=_headers(reviewer["access_token"]),
    )
    assert listing.status_code == 200, listing.text
    assert listing.json() == []

    rated = client.post(
        f"/api/recipes/community/{recipe['id']}/trial-rating",
        headers=_headers(reviewer["access_token"]),
        json={
            "rating": 5,
            "satiety_score": 4,
            "difficulty_score": 2,
            "would_cook_again": True,
            "feedback": "好做，油少也好吃。",
        },
    )
    assert rated.status_code == 404, rated.text

    updated = client.post(
        f"/api/recipes/community/{recipe['id']}/trial-rating",
        headers=_headers(reviewer["access_token"]),
        json={"rating": 4, "feedback": "复做时口味淡一点。"},
    )
    assert updated.status_code == 404, updated.text


def test_admin_approval_publishes_pending_community_recipe_and_preserves_guards(client, clean_db):
    admin = register(client, "community_admin")
    author = register(client, "community_author_approval")
    viewer = register(client, "community_viewer")

    create = client.post(
        "/api/recipes/community",
        headers=_headers(author["access_token"]),
        json=_payload(),
    )
    assert create.status_code == 200, create.text
    recipe = create.json()
    assert recipe["community_status"] == "pending"
    assert recipe["is_approved"] is False

    listing = client.get(
        "/api/recipes/community",
        headers=_headers(viewer["access_token"]),
    )
    assert listing.status_code == 200, listing.text
    assert listing.json() == []

    from database import SessionLocal
    import models

    db = SessionLocal()
    approved_pending = models.Recipe(
        name="approved but pending",
        ingredients="tofu 100g",
        steps="steam",
        category="community_low_fat",
        is_builtin=False,
        submitted_by=recipe["submitted_by"],
        is_approved=True,
        community_status="pending",
    )
    published_unapproved = models.Recipe(
        name="published but unapproved",
        ingredients="spinach 100g",
        steps="boil",
        category="community_low_fat",
        is_builtin=False,
        submitted_by=recipe["submitted_by"],
        is_approved=False,
        community_status="published",
    )
    db.add_all([approved_pending, published_unapproved])
    db.commit()
    guard_recipe_ids = {approved_pending.id, published_unapproved.id}
    db.close()

    guarded_listing = client.get(
        "/api/recipes/community",
        headers=_headers(viewer["access_token"]),
    )
    assert guarded_listing.status_code == 200, guarded_listing.text
    assert guarded_listing.json() == []

    approved = client.put(
        f"/api/admin/recipes/{recipe['id']}/approve",
        headers=_headers(admin["access_token"]),
    )
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()
    assert approved_body["is_approved"] is True
    assert approved_body["community_status"] == "published"

    published_listing = client.get(
        "/api/recipes/community",
        headers=_headers(viewer["access_token"]),
    )
    assert published_listing.status_code == 200, published_listing.text
    visible_ids = [item["id"] for item in published_listing.json()]
    assert visible_ids == [recipe["id"]]
    assert not guard_recipe_ids.intersection(visible_ids)


def test_run_migrations_adds_recipe_json_and_meal_plan_status(tmp_path, monkeypatch):
    import main

    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE recipes (id INTEGER PRIMARY KEY, name VARCHAR)"))
            conn.execute(
                text(
                    "CREATE TABLE meal_plan_entries ("
                    "id INTEGER PRIMARY KEY, "
                    "user_id INTEGER NOT NULL, "
                    "date VARCHAR NOT NULL, "
                    "meal_type VARCHAR NOT NULL"
                    ")"
                )
            )

        monkeypatch.setattr(main, "engine", engine)

        main.run_migrations()

        columns = {
            table: {column["name"]: column for column in inspect(engine).get_columns(table)}
            for table in ("recipes", "meal_plan_entries")
        }
        assert str(columns["recipes"]["ingredients_json"]["type"]).upper() == "TEXT"
        assert "status" in columns["meal_plan_entries"]

        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO meal_plan_entries "
                    "(user_id, date, meal_type) VALUES (1, '2026-06-09', 'lunch')"
                )
            )
            status = conn.execute(text("SELECT status FROM meal_plan_entries")).scalar_one()
        assert status == "recipe"
    finally:
        engine.dispose()
