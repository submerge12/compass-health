from __future__ import annotations

import pytest

from tests.conftest import register


@pytest.fixture(autouse=True)
def clean_user_activity_tables(client):
    from database import SessionLocal
    import models

    db = SessionLocal()
    try:
        for table in (
            models.DailyActivityPlan,
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


def _create_bmr_profile(client, token: str) -> None:
    response = client.post(
        "/api/users/bmr",
        json={
            "age": 32,
            "gender": "female",
            "height_cm": 168,
            "weight_kg": 62,
            "goal": "improve_health",
        },
        headers=_auth_headers(token),
    )
    assert response.status_code == 200, response.text

    # The onboarding flow may seed the editable daily activity date. This test
    # only wants to exercise the profile fallback.
    from database import SessionLocal
    import models

    db = SessionLocal()
    try:
        db.query(models.DailyActivityPlan).delete()
        db.commit()
    finally:
        db.close()


def test_update_activity_level_sets_profile_default(client):
    auth = register(client, "activity_default_user")
    token = auth["access_token"]
    _create_bmr_profile(client, token)

    response = client.patch(
        "/api/users/me/activity-level",
        json={"activity_level": "strength_training"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200, response.text
    assert response.json()["activity_level"] == "strength_training"

    bmr_response = client.get("/api/users/bmr", headers=_auth_headers(token))
    assert bmr_response.status_code == 200, bmr_response.text
    bmr = bmr_response.json()
    assert bmr["profile_activity_level"] == "strength_training"
    assert bmr["activity_level"] == "strength_training"


def test_update_activity_level_rejects_unknown_level(client):
    auth = register(client, "activity_invalid_user")
    token = auth["access_token"]
    _create_bmr_profile(client, token)

    response = client.patch(
        "/api/users/me/activity-level",
        json={"activity_level": "marathon_every_hour"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 422
