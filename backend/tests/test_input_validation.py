from tests.conftest import register


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_daily_log_endpoints_reject_invalid_dates(client, clean_db):
    auth = register(client, "date_validation_user")
    headers = _headers(auth["access_token"])

    cases = [
        (
            "/api/diet/log",
            {
                "date": "2026-02-31",
                "meal_type": "lunch",
                "food_name": "rice bowl",
                "calories": 450,
            },
        ),
        (
            "/api/water/log",
            {
                "date": "2026-13-01",
                "amount_ml": 250,
            },
        ),
        (
            "/api/exercise/log",
            {
                "date": "2026-00-10",
                "exercise_type": "walk",
                "duration_min": 30,
                "calories_burned": 120,
            },
        ),
        (
            "/api/condition/log",
            {
                "date": "2026-04-99",
                "weight_kg": 70,
            },
        ),
    ]

    for path, payload in cases:
        response = client.post(path, headers=headers, json=payload)
        assert response.status_code == 422, (path, response.text)


def test_diet_rejects_unknown_meal_type(client, clean_db):
    auth = register(client, "meal_type_validation_user")
    response = client.post(
        "/api/diet/log",
        headers=_headers(auth["access_token"]),
        json={
            "date": "2026-04-26",
            "meal_type": "brunch",
            "food_name": "late meal",
            "calories": 350,
        },
    )

    assert response.status_code == 422, response.text


def test_meal_engine_rejects_invalid_query_dates(client, clean_db):
    auth = register(client, "meal_engine_date_user")
    headers = _headers(auth["access_token"])

    daily = client.get("/api/meal-engine/daily?date=2026-02-31", headers=headers)
    weekly = client.get("/api/meal-engine/weekly?end_date=2026-11-31", headers=headers)

    assert daily.status_code == 422, daily.text
    assert weekly.status_code == 422, weekly.text
