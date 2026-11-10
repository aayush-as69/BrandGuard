"""Third review: behaviour behind a TLS-terminating proxy, resource limits, input types."""
import io

import pytest

from brandguard.app import create_app
from conftest import NEHA, Session


def test_https_origin_accepted_when_the_proxy_speaks_http_to_the_app(app):
    """Behind a TLS-terminating proxy the browser sends Origin https://host while the app sees http://host."""
    c = app.test_client()
    r = c.post("/api/login", json={"user_id": NEHA}, headers={"Origin": "https://localhost"})
    assert r.status_code == 200
    r = c.post("/api/login", json={"user_id": NEHA}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = c.post("/api/login", json={"user_id": NEHA}, headers={"Origin": "http://localhost.evil.example"})
    assert r.status_code == 403


def test_allowed_origins_setting_lists_extra_hosts(app, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_ALLOWED_ORIGINS", "https://brandguard.example.com")
    ok = app.test_client().post("/api/login", json={"user_id": NEHA}, headers={"Origin": "https://brandguard.example.com"})
    assert ok.status_code == 200


def test_throttle_uses_the_real_client_address_behind_proxies(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AUTH", "accounts")
    monkeypatch.setenv("BRANDGUARD_ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setenv("BRANDGUARD_ADMIN_PASSWORD", "correct-horse-battery")
    monkeypatch.setenv("BRANDGUARD_TRUSTED_PROXIES", "1")
    c = create_app(str(tmp_path / "p.db")).test_client()
    for i in range(10):  # one attacker, ten different email guesses: counted against their address
        c.post("/api/login", json={"email": f"x{i}@a.in", "password": "bad"}, environ_overrides={"REMOTE_ADDR": "10.0.0.1"},
               headers={"X-Forwarded-For": "203.0.113.9"})
    blocked = c.post("/api/login", json={"email": "boss@example.com", "password": "correct-horse-battery"},
                     environ_overrides={"REMOTE_ADDR": "10.0.0.1"}, headers={"X-Forwarded-For": "203.0.113.9"})
    other = c.post("/api/login", json={"email": "boss@example.com", "password": "correct-horse-battery"},
                   environ_overrides={"REMOTE_ADDR": "10.0.0.1"}, headers={"X-Forwarded-For": "198.51.100.7"})
    assert blocked.status_code == 429  # the attacker is stopped
    assert other.status_code == 200    # a different visitor behind the same proxy is not


def test_finished_ai_jobs_do_not_pile_up(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AI_ASYNC", "1")
    app = create_app(str(tmp_path / "f.db"), llm_call=lambda *a: "[]")
    from conftest import IRA
    Session(app, IRA).post("/api/kb/seed")
    n = Session(app, NEHA)
    for i in range(6):
        n.post("/api/content", title=f"t{i}", body="Hi there, our Brewline blend is a cheap way to wake up.", images=[])
        for f in list(app.ai_futures):
            f.result(timeout=20)
    n.post("/api/content", title="last", body="Hi there, our Brewline blend is a cheap way to wake up.", images=[])
    assert len(app.ai_futures) <= 2


def test_image_with_too_many_pixels_is_refused_before_decoding(app):
    PIL = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    PIL.new("1", (6000, 6000)).save(buf, "PNG")  # 36 million pixels, tiny file
    r = Session(app, NEHA).c.post("/api/image/analyze", data={"image": (io.BytesIO(buf.getvalue()), "big.png")},
                                  content_type="multipart/form-data")
    assert r.status_code == 400 and "too many pixels" in r.get_json()["error"]


def test_user_flags_must_be_booleans(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AUTH", "accounts")
    monkeypatch.setenv("BRANDGUARD_ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setenv("BRANDGUARD_ADMIN_PASSWORD", "correct-horse-battery")
    c = create_app(str(tmp_path / "u.db")).test_client()
    c.post("/api/login", json={"email": "boss@example.com", "password": "correct-horse-battery"})
    uid = c.post("/api/users", json={"name": "A", "email": "a@x.in", "role": "creator", "password": "long-enough-pass"}).get_json()["id"]
    assert c.patch(f"/api/users/{uid}", json={"active": "false"}).status_code == 400  # the string "false" is truthy
    assert c.patch(f"/api/users/{uid}", json={"active": False}).status_code == 200
