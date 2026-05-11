from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tests.conftest import register


@pytest.fixture(autouse=True)
def clean_diet_tables(client):
    from database import SessionLocal
    import models

    db = SessionLocal()
    try:
        for table in (
            models.DietLog,
            models.PhysicalCondition,
            models.RefreshToken,
            models.Membership,
            models.UserSettings,
            models.BMRProfile,
            models.User,
        ):
            db.query(table).delete()
        db.commit()
    finally:
        db.close()
    yield


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _FakeCompletions:
    def __init__(self, content: str, calls: list[dict]):
        self.content = content
        self.calls = calls

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.content)
                )
            ]
        )


class _FakeClient:
    def __init__(self, content: str, calls: list[dict]):
        self.chat = SimpleNamespace(
            completions=_FakeCompletions(content, calls)
        )


def test_log_ingredients_uses_reasoner_content_and_bumps_estimate(client, monkeypatch):
    from routers import diet_routes

    calls: list[dict] = []
    content = """
    {
      "food_name": "egg rice bowl",
      "calories": 200,
      "protein_g": 20,
      "carbs_g": 30,
      "fat_g": 10
    }
    """
    monkeypatch.setattr(
        diet_routes.deepseek,
        "get_client",
        lambda: _FakeClient(content, calls),
    )

    auth = register(client, "diet_reasoner_user")
    response = client.post(
        "/api/diet/log-ingredients",
        headers=_auth_headers(auth["access_token"]),
        json={
            "meal_type": "lunch",
            "ingredients": "egg 2\nrice 1 bowl",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["nutrition_status"] == "estimated"
    assert body["nutrition"] == {
        "food_name": "egg rice bowl",
        "calories": 220,
        "protein_g": 22.0,
        "carbs_g": 33.0,
        "fat_g": 11.0,
    }
    assert calls
    assert calls[0]["model"] == "deepseek-reasoner"
    assert calls[0]["max_tokens"] == 1200
    assert "response_format" not in calls[0]


def test_log_ingredients_saves_pending_record_when_reasoner_is_empty(client, monkeypatch):
    from routers import diet_routes

    monkeypatch.setattr(
        diet_routes.deepseek,
        "get_client",
        lambda: _FakeClient("", []),
    )

    auth = register(client, "diet_pending_user")
    response = client.post(
        "/api/diet/log-ingredients",
        headers=_auth_headers(auth["access_token"]),
        json={
            "meal_type": "dinner",
            "ingredients": "chicken 1 piece\nbroccoli 1 plate",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["nutrition_status"] == "pending"
    assert body["nutrition"]["calories"] == 0
    assert body["nutrition"]["food_name"] == "chicken 1 piece + broccoli 1 plate"

    today = client.get("/api/diet/today", headers=_auth_headers(auth["access_token"]))
    assert today.status_code == 200, today.text
    logs = today.json()["logs"]
    assert len(logs) == 1
    assert logs[0]["ingredients"] == "chicken 1 piece\nbroccoli 1 plate"
    assert logs[0]["calories"] == 0


def test_reanalyze_pending_log_updates_nutrition(client, monkeypatch):
    from routers import diet_routes

    monkeypatch.setattr(
        diet_routes.deepseek,
        "get_client",
        lambda: _FakeClient("", []),
    )

    auth = register(client, "diet_reanalyze_user")
    headers = _auth_headers(auth["access_token"])
    create_response = client.post(
        "/api/diet/log-ingredients",
        headers=headers,
        json={
            "meal_type": "breakfast",
            "ingredients": "egg 2\nyogurt 100g",
        },
    )
    assert create_response.status_code == 200, create_response.text
    log_id = create_response.json()["id"]
    assert create_response.json()["nutrition_status"] == "pending"

    content = """
    {
      "food_name": "egg yogurt breakfast",
      "calories": 300,
      "protein_g": 26,
      "carbs_g": 15,
      "fat_g": 12
    }
    """
    monkeypatch.setattr(
        diet_routes.deepseek,
        "get_client",
        lambda: _FakeClient(content, []),
    )

    retry_response = client.post(f"/api/diet/log/{log_id}/reanalyze", headers=headers)
    assert retry_response.status_code == 200, retry_response.text
    body = retry_response.json()
    assert body["nutrition_status"] == "estimated"
    assert body["nutrition"] == {
        "food_name": "egg yogurt breakfast",
        "calories": 330,
        "protein_g": 28.6,
        "carbs_g": 16.5,
        "fat_g": 13.2,
    }

    today = client.get("/api/diet/today", headers=headers)
    assert today.status_code == 200, today.text
    assert today.json()["logs"][0]["calories"] == 330


def test_diet_today_uses_app_local_date_across_utc_midnight(client, monkeypatch):
    from database import SessionLocal
    import models
    from services import local_dates

    monkeypatch.setattr(
        local_dates,
        "utc_now",
        lambda: datetime(2026, 4, 25, 16, 30, tzinfo=timezone.utc),
    )

    auth = register(client, "diet_local_date_user")
    headers = _auth_headers(auth["access_token"])
    yesterday = client.post(
        "/api/diet/log",
        headers=headers,
        json={
            "date": "2026-04-25",
            "meal_type": "lunch",
            "food_name": "old day meal",
            "calories": 400,
        },
    )
    assert yesterday.status_code == 200, yesterday.text
    today_log = client.post(
        "/api/diet/log",
        headers=headers,
        json={
            "meal_type": "breakfast",
            "food_name": "local day breakfast",
            "calories": 500,
        },
    )
    assert today_log.status_code == 200, today_log.text

    today = client.get("/api/diet/today", headers=headers)

    assert today.status_code == 200, today.text
    body = today.json()
    assert body["totals"]["calories"] == 500
    assert len(body["logs"]) == 1

    db = SessionLocal()
    try:
        row = (
            db.query(models.DietLog)
            .filter(models.DietLog.id == today_log.json()["id"])
            .first()
        )
        assert row.date == "2026-04-26"
    finally:
        db.close()
