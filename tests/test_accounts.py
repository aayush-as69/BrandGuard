import pytest

from brandguard.app import create_app

PW = "correct-horse-battery"


@pytest.fixture()
def acct(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AUTH", "accounts")
    monkeypatch.setenv("BRANDGUARD_ADMIN_EMAIL", "Boss@Example.com")
    monkeypatch.setenv("BRANDGUARD_ADMIN_PASSWORD", PW)
    return create_app(str(tmp_path / "a.db"))


def login(app, email="boss@example.com", password=PW):
    c = app.test_client()
    return c, c.post("/api/login", json={"email": email, "password": password})



def test_demo_role_switch_stays_in_demo_session(app):
    client = app.test_client()
    assert client.post("/api/login", json={"user_id": 2}).status_code == 200
    assert client.get("/api/me").get_json()["role"] == "manager"
    switched = client.post("/api/demo/switch-role", json={"role": "reviewer"})
    assert switched.status_code == 200
    assert switched.get_json()["role"] == "reviewer"
    assert client.get("/api/me").get_json()["role"] == "reviewer"
    switched = client.post("/api/demo/switch-role", json={"role": "admin"})
    assert switched.status_code == 200
    assert client.get("/api/me").get_json()["role"] == "admin"


def test_demo_role_switch_is_not_available_in_accounts_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_ENV", "production")
    monkeypatch.setenv("BRANDGUARD_SECRET", "s" * 32)
    monkeypatch.setenv("BRANDGUARD_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("BRANDGUARD_ADMIN_PASSWORD", "strong-admin-password")
    monkeypatch.setenv("BRANDGUARD_AUTH", "accounts")
    app = create_app(str(tmp_path / "accounts-switch.db"))
    client = app.test_client()
    assert client.post("/api/demo/switch-role", json={"role": "admin"}).status_code in (401, 403)


def test_no_demo_users_and_anonymous_cannot_pick_admin(acct):
    c = acct.test_client()
    assert c.post("/api/login", json={"user_id": 1}).status_code == 401  # id login is a demo-mode feature
    assert c.get("/api/users").status_code == 401  # account list is not public
    assert c.get("/api/config").get_json()["auth"] == "accounts"


def test_login_password_rules_and_generic_error(acct):
    assert login(acct)[1].status_code == 200
    assert login(acct, password="wrong")[1].status_code == 401
    r = login(acct, email="nobody@example.com")[1]
    assert r.status_code == 401 and r.get_json()["error"] == "Wrong email or password"


def test_password_is_hashed(acct):
    from brandguard import db
    row = db.connect(acct.config["DB_PATH"]).execute("SELECT password_hash FROM users").fetchone()
    assert PW not in row[0] and row[0].startswith(("scrypt", "pbkdf2"))


def test_throttle(acct):
    codes = [login(acct, password=f"bad{i}")[1].status_code for i in range(12)]
    assert codes[-1] == 429
    assert login(acct)[1].status_code == 429


def test_admin_manages_accounts_and_deactivation_revokes_session(acct):
    admin, _ = login(acct)
    r = admin.post("/api/users", json={"name": "Neha", "email": "neha@agency.in", "role": "creator",
                                       "is_external": True, "password": "another-long-pass"})
    assert r.status_code == 201
    uid = r.get_json()["id"]
    neha, r = login(acct, "neha@agency.in", "another-long-pass")
    assert r.status_code == 200 and neha.get("/api/me").status_code == 200
    assert neha.get("/api/users").status_code == 403 and neha.post("/api/users", json={}).status_code == 403
    assert admin.patch(f"/api/users/{uid}", json={"active": False}).status_code == 200
    assert neha.get("/api/me").status_code == 401  # revoked at once
    assert login(acct, "neha@agency.in", "another-long-pass")[1].status_code == 401


def test_password_reset_ends_old_sessions(acct):
    admin, _ = login(acct)
    uid = admin.post("/api/users", json={"name": "R", "email": "r@x.in", "role": "reviewer",
                                         "password": "first-long-pass"}).get_json()["id"]
    rr, _ = login(acct, "r@x.in", "first-long-pass")
    admin.patch(f"/api/users/{uid}", json={"password": "second-long-pass"})
    assert rr.get("/api/me").status_code == 401
    assert login(acct, "r@x.in", "second-long-pass")[1].status_code == 200


def test_change_own_password(acct):
    c, _ = login(acct)
    assert c.post("/api/password", json={"current": "nope", "new": "x" * 12}).status_code == 403
    assert c.post("/api/password", json={"current": PW, "new": "short"}).status_code == 400
    assert c.post("/api/password", json={"current": PW, "new": "brand-new-password"}).status_code == 200
    assert c.get("/api/me").status_code == 200  # this device stays signed in
    assert login(acct, password=PW)[1].status_code == 401


def test_cannot_remove_last_admin_or_weaken_inputs(acct):
    admin, _ = login(acct)
    me = admin.get("/api/me").get_json()["id"]
    assert admin.patch(f"/api/users/{me}", json={"active": False}).status_code == 400
    assert admin.patch(f"/api/users/{me}", json={"role": "creator"}).status_code == 400
    assert admin.post("/api/users", json={"name": "A", "email": "a@x.in", "role": "admin",
                                          "is_external": True, "password": "long-enough-pass"}).status_code == 400
    assert admin.post("/api/users", json={"name": "A", "email": "a@x.in", "role": "root",
                                          "password": "long-enough-pass"}).status_code == 400
    assert admin.post("/api/users", json={"name": "A", "email": "a@x.in", "role": "creator",
                                          "password": "short"}).status_code == 400


def test_duplicate_email_refused(acct):
    admin, _ = login(acct)
    body = {"name": "A", "email": "BOSS@example.com", "role": "creator", "password": "long-enough-pass"}
    assert admin.post("/api/users", json=body).status_code == 400
