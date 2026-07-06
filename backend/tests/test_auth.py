from tests.conftest import register


def test_login_happy_path(client, clean_db):
    register(client, "alice")

    r = client.post("/api/auth/login", json={"username": "alice", "password": "pw12345"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["username"] == "alice"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["membership_level"] == "free"
    assert body["is_admin"] is True   # first user auto-promoted


def test_login_wrong_password(client, clean_db):
    register(client, "bob")

    r = client.post("/api/auth/login", json={"username": "bob", "password": "wrongpw"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid username or password"


def test_refresh_token_is_hashed_and_rotated(client, clean_db):
    import hashlib

    from database import SessionLocal
    import models

    auth = register(client, "charlie")
    original_refresh = auth["refresh_token"]

    db = SessionLocal()
    try:
        row = db.query(models.RefreshToken).one()
        assert row.token != original_refresh
        assert row.token == hashlib.sha256(original_refresh.encode("utf-8")).hexdigest()
    finally:
        db.close()

    refreshed = client.post(
        "/api/auth/refresh",
        json={"refresh_token": original_refresh},
    )
    assert refreshed.status_code == 200, refreshed.text
    body = refreshed.json()
    assert body["access_token"]
    assert body["refresh_token"] != original_refresh

    reused = client.post(
        "/api/auth/refresh",
        json={"refresh_token": original_refresh},
    )
    assert reused.status_code == 401

    db = SessionLocal()
    try:
        rows = db.query(models.RefreshToken).all()
        assert len(rows) == 1
        assert rows[0].token == hashlib.sha256(body["refresh_token"].encode("utf-8")).hexdigest()
    finally:
        db.close()


def test_refresh_token_consume_is_single_use(client, clean_db):
    import hashlib

    from database import SessionLocal
    from routers import auth_routes

    auth = register(client, "delta")
    token_hash = hashlib.sha256(auth["refresh_token"].encode("utf-8")).hexdigest()

    db = SessionLocal()
    try:
        assert auth_routes._consume_refresh_token(db, token_hash) is True
        db.commit()
        assert auth_routes._consume_refresh_token(db, token_hash) is False
        db.rollback()
    finally:
        db.close()


def test_refresh_token_migration_hashes_legacy_plaintext(client, clean_db):
    import hashlib
    from datetime import datetime, timedelta, timezone

    from database import SessionLocal
    import models
    from scripts import migrate_refresh_tokens_to_hash as migration

    register(client, "legacy_refresh_owner")
    legacy_value = "legacy-refresh-token-value"

    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(username="legacy_refresh_owner").one()
        db.add(models.RefreshToken(
            user_id=user.id,
            token=legacy_value,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        ))
        db.commit()
    finally:
        db.close()

    dry_run = migration.migrate_refresh_tokens(apply=False, session_factory=SessionLocal)
    assert dry_run["migrated"] == 1
    assert dry_run["committed"] == 0

    db = SessionLocal()
    try:
        assert db.query(models.RefreshToken).filter_by(token=legacy_value).count() == 1
    finally:
        db.close()

    applied = migration.migrate_refresh_tokens(apply=True, session_factory=SessionLocal)
    assert applied["migrated"] == 1
    assert applied["committed"] == 1

    db = SessionLocal()
    try:
        expected = hashlib.sha256(legacy_value.encode("utf-8")).hexdigest()
        assert db.query(models.RefreshToken).filter_by(token=legacy_value).count() == 0
        assert db.query(models.RefreshToken).filter_by(token=expected).count() == 1
    finally:
        db.close()
