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
