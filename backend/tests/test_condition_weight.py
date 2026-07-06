from __future__ import annotations

from datetime import timedelta

import pytest

from tests.conftest import register


@pytest.fixture(autouse=True)
def clean_condition_weight_tables(client):
    from database import SessionLocal
    import models

    db = SessionLocal()
    try:
        for table in (
            models.PhysicalCondition,
            models.DailyActivityPlan,
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


def _today() -> str:
    from services import local_dates

    return local_dates.today_key()


def _yesterday() -> str:
    from services import local_dates

    return (local_dates.app_now() - timedelta(days=1)).strftime("%Y-%m-%d")


def _create_bmr_profile(client, token: str, weight_kg: float = 62.0) -> None:
    response = client.post(
        "/api/users/bmr",
        json={
            "age": 32,
            "gender": "female",
            "height_cm": 168,
            "weight_kg": weight_kg,
            "goal": "improve_health",
        },
        headers=_auth_headers(token),
    )
    assert response.status_code == 200, response.text


def test_today_condition_returns_latest_weight_without_today_entry(client):
    auth = register(client, "condition_latest_weight_user")
    token = auth["access_token"]
    yesterday = _yesterday()

    response = client.post(
        "/api/condition/log",
        json={"date": yesterday, "weight_kg": 61.5},
        headers=_auth_headers(token),
    )
    assert response.status_code == 200, response.text

    today_response = client.get("/api/condition/today", headers=_auth_headers(token))

    assert today_response.status_code == 200, today_response.text
    body = today_response.json()
    assert body["date"] == _today()
    assert body["weight_kg"] == 61.5
    assert body["latest_weight_kg"] == 61.5
    assert body["latest_weight_date"] == yesterday
    assert body["weight_date"] == yesterday
    assert body["weight_is_latest_fallback"] is True


def test_today_condition_falls_back_when_today_entry_has_no_weight(client):
    auth = register(client, "condition_today_without_weight_user")
    token = auth["access_token"]
    yesterday = _yesterday()

    old_weight = client.post(
        "/api/condition/log",
        json={"date": yesterday, "weight_kg": 60.8},
        headers=_auth_headers(token),
    )
    assert old_weight.status_code == 200, old_weight.text
    today_mood = client.post(
        "/api/condition/log",
        json={"mood": 4},
        headers=_auth_headers(token),
    )
    assert today_mood.status_code == 200, today_mood.text

    today_response = client.get("/api/condition/today", headers=_auth_headers(token))

    assert today_response.status_code == 200, today_response.text
    body = today_response.json()
    assert body["date"] == _today()
    assert body["mood"] == 4
    assert body["weight_kg"] == 60.8
    assert body["weight_date"] == yesterday
    assert body["weight_is_latest_fallback"] is True


def test_profile_weight_update_writes_today_condition_weight(client):
    auth = register(client, "profile_weight_sync_user")
    token = auth["access_token"]
    _create_bmr_profile(client, token, weight_kg=62.0)

    response = client.patch(
        "/api/users/me/weight",
        json={"weight_kg": 64.2},
        headers=_auth_headers(token),
    )
    assert response.status_code == 200, response.text

    today_response = client.get("/api/condition/today", headers=_auth_headers(token))

    assert today_response.status_code == 200, today_response.text
    body = today_response.json()
    assert body["date"] == _today()
    assert body["weight_kg"] == 64.2
    assert body["weight_is_latest_fallback"] is False


def test_logging_today_weight_updates_bmr_profile(client):
    auth = register(client, "condition_weight_profile_sync_user")
    token = auth["access_token"]
    _create_bmr_profile(client, token, weight_kg=62.0)

    response = client.post(
        "/api/condition/log",
        json={"weight_kg": 63.1},
        headers=_auth_headers(token),
    )
    assert response.status_code == 200, response.text

    bmr_response = client.get("/api/users/bmr", headers=_auth_headers(token))

    assert bmr_response.status_code == 200, bmr_response.text
    assert bmr_response.json()["weight_kg"] == 63.1
