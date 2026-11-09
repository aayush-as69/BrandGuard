import time

import pytest

from brandguard import totp
from brandguard.app import create_app

PW = "correct-horse-battery"


def test_totp_matches_rfc6238_vector():
    import base64
    secret = base64.b32encode(b"12345678901234567890").decode()  # RFC 6238 test key (SHA-1)
    assert totp.at(secret, 59) == "287082"  # 8-digit vector 94287082 truncated to 6 digits
    assert totp.verify(secret, "287082", now=59) == 1
    assert totp.verify(secret, "287082", last_step=1, now=59) is None  # replay refused
    assert totp.verify(secret, "000000", now=59) is None


@pytest.fixture()
def acct(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AUTH", "accounts")
    monkeypatch.setenv("BRANDGUARD_ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setenv("BRANDGUARD_ADMIN_PASSWORD", PW)
    return create_app(str(tmp_path / "m.db"))


def _login(app, **extra):
    c = app.test_client()
    return c, c.post("/api/login", json={"email": "boss@example.com", "password": PW, **extra})


def _enrol(app):
    c, _ = _login(app)
    secret = c.post("/api/mfa/setup").get_json()["secret"]
    assert c.post("/api/mfa/enable", json={"code": "123456"}).status_code == 400
    assert c.post("/api/mfa/enable", json={"code": totp.at(secret)}).status_code == 200
    return secret


def test_second_step_required_after_enrolment(acct):
    secret = _enrol(acct)
    c, r = _login(acct)
    assert r.status_code == 401 and r.get_json()["mfa_required"] is True
    assert c.get("/api/me").status_code == 401  # password alone gives no session
    assert _login(acct, code="000000")[1].status_code == 401
    # the code used to enrol is spent; the next 30-second code works
    good = totp.at(secret, time.time() + 30)
    c, r = _login(acct, code=good)
    assert r.status_code == 200 and c.get("/api/me").get_json()["mfa"] is True
    assert "totp_secret" not in c.get("/api/me").get_json()
    assert _login(acct, code=good)[1].status_code == 401  # replay


def test_disable_needs_password_and_code_and_admin_can_reset(acct):
    secret = _enrol(acct)
    c, _ = _login(acct, code=totp.at(secret, time.time() + 30))
    assert c.post("/api/mfa/disable", json={"password": "bad", "code": totp.at(secret, time.time() + 60)}).status_code == 403
    uid = c.get("/api/me").get_json()["id"]
    assert c.patch(f"/api/users/{uid}", json={"reset_mfa": True}).status_code == 200
    assert _login(acct)[1].status_code == 200  # no second step any more


@pytest.fixture()
def sso(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AUTH", "accounts")
    monkeypatch.setenv("BRANDGUARD_ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setenv("BRANDGUARD_ADMIN_PASSWORD", PW)
    monkeypatch.setenv("BRANDGUARD_SSO_EMAIL_HEADER", "X-Auth-Request-Email")
    monkeypatch.setenv("BRANDGUARD_SSO_SECRET", "s" * 24)
    return create_app(str(tmp_path / "s.db"))


def test_sso_requires_the_proxy_secret_and_an_existing_account(sso):
    c = sso.test_client()
    hdr = {"X-Auth-Request-Email": "boss@example.com"}
    assert c.post("/api/sso/login", headers=hdr).status_code == 401  # no secret: a client spoofing the header
    assert c.post("/api/sso/login", headers={**hdr, "X-SSO-Secret": "wrong"}).status_code == 401
    assert c.post("/api/sso/login", headers={"X-Auth-Request-Email": "stranger@x.in", "X-SSO-Secret": "s" * 24}).status_code == 403
    r = c.post("/api/sso/login", headers={**hdr, "X-SSO-Secret": "s" * 24})
    assert r.status_code == 200 and c.get("/api/me").get_json()["role"] == "admin"
    assert c.get("/api/config").get_json()["sso"] is True


def test_sso_off_by_default_and_needs_a_long_secret(acct, tmp_path, monkeypatch):
    assert acct.test_client().post("/api/sso/login").status_code == 404
    monkeypatch.setenv("BRANDGUARD_SSO_EMAIL_HEADER", "X-Email")
    monkeypatch.setenv("BRANDGUARD_SSO_SECRET", "short")
    with pytest.raises(RuntimeError, match="SSO_SECRET"):
        create_app(str(tmp_path / "z.db"))
