"""M01 BFF contract tests: identity, trace propagation, and failure mode.

Uses httpx.MockTransport so no live :8788 service is needed. Verifies:
- JWT required (401 without / with bad token);
- X-External-User-ID derived from the verified JWT user, a client-supplied
  header is ignored (cross-user isolation);
- service token + X-Request-ID/X-Journey-ID propagate downstream;
- domain unreachable → 503 domain_unavailable with request id, never a
  silent fallback;
- HEALTH_DOMAIN_MODE != postgres → 503.
"""
from __future__ import annotations

import pytest

from services.health_domain_client import HealthDomainClient

from tests.conftest import register


@pytest.fixture()
def captured():
    return {"requests": []}


def _mock_transport(captured, *, status=200, payload=None):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        captured["requests"].append(
            {
                "method": request.method,
                "path": request.url.path,
                "query": dict(request.url.params),
                "headers": dict(request.headers),
                "body": request.content,
            }
        )
        return httpx.Response(status, json=payload or {"ok": True})

    return httpx.MockTransport(handler)


@pytest.fixture()
def bff_client(client):
    """Override the router's client dependency with a MockTransport per-test."""
    import routers.health_domain_routes as routes

    def attach(transport):
        client.app.dependency_overrides[routes._client] = lambda: HealthDomainClient(
            transport=transport, token="svc-token"
        )

    return {"client": client, "attach": attach}


def test_bff_requires_jwt(bff_client, captured):
    bff_client["attach"](_mock_transport(captured))
    res = bff_client["client"].get("/api/domain/plan?start=2026-08-24&days=1")
    assert res.status_code == 401
    assert captured["requests"] == []


def test_bff_forwards_with_jwt_identity_and_trace(bff_client, captured, clean_db):
    bff_client["attach"](_mock_transport(captured))
    auth = register(bff_client["client"], "bff-user")

    import models
    from database import SessionLocal
    db = SessionLocal()
    try:
        user_id = db.query(models.User).filter(models.User.username == "bff-user").one().id
    finally:
        db.close()

    res = bff_client["client"].get(
        "/api/domain/plan?start=2026-08-24&days=1",
        headers={
            "Authorization": f"Bearer {auth['access_token']}",
            "X-Request-ID": "req-test-1",
            "X-Journey-ID": "jrn-test-1",
        },
    )
    assert res.status_code == 200

    downstream = captured["requests"][0]
    assert downstream["path"] == "/api/plan"
    assert downstream["query"]["start"] == "2026-08-24"
    # Identity derived from the JWT user id, not from any client header.
    assert downstream["headers"]["x-external-user-id"] == f"compass-health:{user_id}"
    assert downstream["headers"]["authorization"] == "Bearer svc-token"
    assert downstream["headers"]["x-request-id"] == "req-test-1"
    assert downstream["headers"]["x-journey-id"] == "jrn-test-1"


def test_bff_ignores_client_supplied_external_id(bff_client, captured, clean_db):
    bff_client["attach"](_mock_transport(captured))
    auth = register(bff_client["client"], "bff-user-2")

    res = bff_client["client"].get(
        "/api/domain/plan",
        headers={
            "Authorization": f"Bearer {auth['access_token']}",
            "X-External-User-ID": "compass-health:999",
        },
    )
    assert res.status_code == 200
    downstream = captured["requests"][0]
    assert downstream["headers"]["x-external-user-id"] != "compass-health:999"


def test_bff_users_are_isolated(bff_client, captured, clean_db):
    bff_client["attach"](_mock_transport(captured))
    import models
    from database import SessionLocal

    db = SessionLocal()
    try:
        second = models.User(username="bff-other", hashed_password="x", email="o@x.y")
        db.add(second)
        db.commit()
    finally:
        db.close()

    auth = register(bff_client["client"], "bff-user-3")
    db = SessionLocal()
    try:
        current = db.query(models.User).filter(models.User.username == "bff-user-3").one()
        current_id = current.id
    finally:
        db.close()

    res = bff_client["client"].get(
        "/api/domain/profile",
        headers={"Authorization": f"Bearer {auth['access_token']}"},
    )
    assert res.status_code == 200
    downstream = captured["requests"][0]
    assert downstream["headers"]["x-external-user-id"] == f"compass-health:{current_id}"


def test_bff_forwards_post_body(bff_client, captured, clean_db):
    bff_client["attach"](_mock_transport(captured))
    auth = register(bff_client["client"], "bff-poster")

    res = bff_client["client"].post(
        "/api/domain/log/meal",
        headers={"Authorization": f"Bearer {auth['access_token']}"},
        json={"date": "2026-08-24", "mealType": "lunch", "description": "牛肉 150 克"},
    )
    assert res.status_code == 200
    downstream = captured["requests"][0]
    assert downstream["method"] == "POST"
    assert downstream["path"] == "/api/log/meal"
    import json as _json

    sent = _json.loads(downstream["body"].decode("utf-8"))
    assert sent["description"] == "牛肉 150 克"


def test_bff_domain_down_returns_503(bff_client, clean_db):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    bff_client["attach"](httpx.MockTransport(handler))
    auth = register(bff_client["client"], "bff-down")
    res = bff_client["client"].get(
        "/api/domain/plan",
        headers={"Authorization": f"Bearer {auth['access_token']}"},
    )
    assert res.status_code == 503
    body = res.json()
    assert body["error"] == "domain_unavailable"
    assert "request_id" in body


def test_bff_disabled_mode_returns_503(bff_client, captured, monkeypatch, clean_db):
    monkeypatch.setenv("HEALTH_DOMAIN_MODE", "off")
    bff_client["attach"](_mock_transport(captured))
    auth = register(bff_client["client"], "bff-off")
    res = bff_client["client"].get(
        "/api/domain/plan",
        headers={"Authorization": f"Bearer {auth['access_token']}"},
    )
    assert res.status_code == 503
    assert res.json()["error"] == "domain_unavailable"
    assert captured["requests"] == []


def test_bff_proxies_v1_daily_state_paths(bff_client, captured, clean_db):
    """M03: the same authenticated proxy serves the new /api/v1/* routes."""
    bff_client["attach"](_mock_transport(captured))
    auth = register(bff_client["client"], "bff-v1")

    res = bff_client["client"].get(
        "/api/domain/v1/daily-state?date=2026-08-24",
        headers={"Authorization": f"Bearer {auth['access_token']}"},
    )
    assert res.status_code == 200
    downstream = captured["requests"][0]
    assert downstream["path"] == "/api/v1/daily-state"
    assert downstream["query"]["date"] == "2026-08-24"

    captured["requests"].clear()
    res = bff_client["client"].post(
        "/api/domain/v1/observations",
        headers={"Authorization": f"Bearer {auth['access_token']}"},
        json={"observedOn": "2026-08-24", "kind": "sleep", "value": {"hours": 6.5}},
    )
    assert res.status_code == 200
    downstream = captured["requests"][0]
    assert downstream["path"] == "/api/v1/observations"
    import json as _json

    sent = _json.loads(downstream["body"].decode("utf-8"))
    assert sent["kind"] == "sleep"
