import json
import os
from pathlib import Path

from tests.conftest import promote_to_admin, register


def test_admin_guard_blocks_non_admin(client, clean_db):
    """A regular user hitting an /api/admin/* endpoint gets 403."""
    # First registrant auto-gets admin, so make a second user (not admin) first.
    register(client, "first_admin")
    bob = register(client, "bob")
    assert bob["is_admin"] is False

    r = client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {bob['access_token']}"},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "Admin access required"


def test_admin_cannot_demote_self(client, clean_db):
    """Admin cannot strip their own admin flag — prevents accidental lock-out."""
    admin = register(client, "root")
    promote_to_admin("root")  # first registrant already is, but keep explicit

    # Re-login so token picks up the admin flag (the register response was issued
    # before the promotion — for the first user this is a no-op but it's cheap).
    lr = client.post("/api/auth/login", json={"username": "root", "password": "pw12345"})
    assert lr.status_code == 200
    token = lr.json()["access_token"]

    me_id = _find_user_id(client, token, "root")
    r = client.patch(
        f"/api/admin/users/{me_id}",
        json={"is_admin": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text
    assert "cannot revoke admin" in r.json()["detail"].lower()


def test_admin_delete_user_cascades(client, clean_db):
    """Admin deletes a user: user row + their refresh tokens are gone."""
    register(client, "root")
    victim = register(client, "victim")

    admin_token = client.post(
        "/api/auth/login", json={"username": "root", "password": "pw12345"}
    ).json()["access_token"]

    victim_id = _find_user_id(client, admin_token, "victim")

    # Victim has at least one refresh token from registration — sanity check.
    from database import SessionLocal
    import models
    db = SessionLocal()
    assert db.query(models.RefreshToken).filter(
        models.RefreshToken.user_id == victim_id
    ).count() >= 1
    db.close()

    r = client.delete(
        f"/api/admin/users/{victim_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text

    # User row + refresh tokens should be gone; audit row should exist.
    db = SessionLocal()
    assert db.query(models.User).filter(models.User.id == victim_id).first() is None
    assert db.query(models.RefreshToken).filter(
        models.RefreshToken.user_id == victim_id
    ).count() == 0
    audit = db.query(models.AdminAuditLog).filter(
        models.AdminAuditLog.action == "user.delete",
        models.AdminAuditLog.target_id == victim_id,
    ).first()
    assert audit is not None
    assert audit.actor_username == "root"
    db.close()


def test_admin_can_reset_llm_quota_and_repair_preferences(client, clean_db):
    register(client, "root")
    register(client, "victim")

    admin_token = client.post(
        "/api/auth/login", json={"username": "root", "password": "pw12345"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {admin_token}"}
    victim_id = _find_user_id(client, admin_token, "victim")

    from database import SessionLocal
    import models
    from services import llm_quota

    db = SessionLocal()
    db.add(models.LLMCallLog(user_id=victim_id, kind=llm_quota.POOL_NAME))
    db.add(models.LLMCallLog(user_id=victim_id, kind=llm_quota.RECIPE_SUGGEST))
    db.add(models.FoodPreference(user_id=victim_id, category="fruits", item_key="kiwi"))
    db.commit()
    db.close()

    r = client.get(f"/api/admin/llm-quotas?user_id={victim_id}", headers=headers)
    assert r.status_code == 200, r.text
    row = r.json()["users"][0]
    assert row["quotas"]["pool_name"]["used"] == 1

    r = client.post(
        f"/api/admin/users/{victim_id}/llm-quota/reset",
        json={"kind": "pool_name", "reason": "compensate unusable LLM output"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["quotas"]["pool_name"]["used"] == 0

    payload = {
        "replace": True,
        "reason": "repair closed-loop food library",
        "items": [
            {"category": "grains", "item_key": "rice"},
            {"category": "vegetables", "item_key": "spinach"},
            {"category": "fruits", "item_key": "strawberry"},
            {"category": "meat_low_fat", "item_key": "chicken_breast"},
            {"category": "dairy", "item_key": "milk"},
            {"category": "nuts", "item_key": "nut_mix"},
        ],
    }
    r = client.put(
        f"/api/admin/users/{victim_id}/preferences",
        json=payload,
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["categories"]["fruits"] == ["strawberry"]
    assert "nutrition_audit" in r.json()

    db = SessionLocal()
    actions = {
        row.action
        for row in db.query(models.AdminAuditLog)
        .filter(models.AdminAuditLog.target_id == victim_id)
        .all()
    }
    assert "user.llm_quota.reset" in actions
    assert "user.preferences.update" in actions
    db.close()


def test_admin_can_reset_pool_name_quota_for_all_users(client, clean_db):
    register(client, "root")
    register(client, "victim_one")
    register(client, "victim_two")

    admin_token = client.post(
        "/api/auth/login", json={"username": "root", "password": "pw12345"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {admin_token}"}
    victim_one_id = _find_user_id(client, admin_token, "victim_one")
    victim_two_id = _find_user_id(client, admin_token, "victim_two")

    from database import SessionLocal
    import models
    from services import llm_quota

    db = SessionLocal()
    db.add(models.LLMCallLog(user_id=victim_one_id, kind=llm_quota.POOL_NAME))
    db.add(models.LLMCallLog(user_id=victim_one_id, kind=llm_quota.RECIPE_SUGGEST))
    db.add(models.LLMCallLog(user_id=victim_two_id, kind=llm_quota.POOL_NAME))
    db.commit()
    db.close()

    r = client.post(
        "/api/admin/llm-quotas/reset",
        json={"kind": "pool_name", "reason": "restore all pool naming quotas"},
        headers=headers,
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "pool_name"
    assert body["scope"] == "all_users"
    assert body["deleted_rows"] == 2
    assert body["affected_user_count"] == 2

    db = SessionLocal()
    assert db.query(models.LLMCallLog).filter(
        models.LLMCallLog.kind == llm_quota.POOL_NAME,
    ).count() == 0
    assert db.query(models.LLMCallLog).filter(
        models.LLMCallLog.kind == llm_quota.RECIPE_SUGGEST,
    ).count() == 1
    audit = db.query(models.AdminAuditLog).filter(
        models.AdminAuditLog.action == "system.llm_quota.reset",
        models.AdminAuditLog.target_type == "llm_quota",
    ).first()
    assert audit is not None
    details = json.loads(audit.details)
    assert details["kind"] == "pool_name"
    assert details["scope"] == "all_users"
    assert details["affected_user_count"] == 2
    db.close()


def test_admin_observability_hides_raw_llm_payload(client, clean_db):
    admin = register(client, "root")
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    root_id = _find_user_id(client, admin["access_token"], "root")

    log_path = Path(os.environ["LOG_DIR"]) / "app.log"
    log_path.write_text(
        json.dumps({
            "ts": "2026-04-24T10:00:00",
            "lvl": "INFO",
            "logger": "compass.app",
            "msg": "recipe_suggester[pool] raw response: secret prompt payload",
            "event": "pool_name_raw",
            "user_id": root_id,
            "request_id": "req-test",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    r = client.get("/api/admin/observability/events?limit=1", headers=headers)
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["request_id"] == "req-test"
    assert "hidden" in item["msg"].lower()
    assert "secret prompt payload" not in item["msg"]


def _find_user_id(client, token: str, username: str) -> int:
    r = client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    for u in r.json():
        if u["username"] == username:
            return u["id"]
    raise AssertionError(f"user {username} not found in admin listing")
