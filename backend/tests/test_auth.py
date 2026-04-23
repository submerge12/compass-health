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
