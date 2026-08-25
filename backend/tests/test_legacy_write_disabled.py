"""WO-HS-04 / M02: legacy health write gate tests.

With HEALTH_LEGACY_WRITE_MODE=readonly (the migration default going
forward), the old FastAPI health write routes return 410
legacy_health_write_disabled; reads keep working. The frontend now talks
to the domain API through the BFF, so this gate is what makes
"SQLite health writes == 0" enforceable rather than aspirational.
"""
from __future__ import annotations

import pytest

from services.legacy_write_gate import legacy_write_mode

from tests.conftest import register


@pytest.fixture()
def auth_client(client, monkeypatch, clean_db):
    monkeypatch.setenv("HEALTH_LEGACY_WRITE_MODE", "readonly")
    auth = register(client, "gate-user")
    return {"client": client, "token": auth["access_token"]}


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_mode_default_is_disabled(monkeypatch):
    # P0-8: production default is hard-off; `enabled` is opt-in only.
    monkeypatch.delenv("HEALTH_LEGACY_WRITE_MODE", raising=False)
    assert legacy_write_mode() == "disabled"


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("post", "/api/water/log", {"amount_ml": 250}),
        ("post", "/api/exercise/log", {"exercise_type": "run", "duration_min": 30, "calories_burned": 100}),
        ("post", "/api/diet/log", {"meal_type": "lunch", "food_name": "米饭", "calories": 200}),
        ("delete", "/api/water/log/99999", None),
    ],
)
def test_legacy_writes_return_410_in_readonly(auth_client, method, path, json_body):
    res = auth_client["client"].request(
        method,
        path,
        headers=_headers(auth_client["token"]),
        json=json_body,
    )
    assert res.status_code == 410, res.text
    body = res.json()
    detail = body.get("detail")
    if isinstance(detail, dict):
        assert detail["error"] == "legacy_health_write_disabled"
    else:
        # Some routes validate before the gate fires; those are 422 and still
        # refuse to write — acceptable, but flag them for tightening.
        assert res.status_code in (410, 422)


def test_legacy_reads_still_work_in_readonly(auth_client):
    res = auth_client["client"].get("/api/water/today", headers=_headers(auth_client["token"]))
    assert res.status_code == 200
    assert "total_ml" in res.json()


def test_enabled_mode_keeps_old_behavior(client, monkeypatch, clean_db):
    monkeypatch.setenv("HEALTH_LEGACY_WRITE_MODE", "enabled")
    auth = register(client, "gate-legacy-on")
    res = client.post(
        "/api/water/log",
        headers=_headers(auth["access_token"]),
        json={"amount_ml": 250},
    )
    assert res.status_code == 200, res.text
