"""Regressions for the sixth code review: locked content, request parsing, search, throttles, audit trail."""
import json
import threading

import pytest

from brandguard import db as dbm
from brandguard import throttle
from brandguard import workflow as wf
from brandguard.app import _like_pattern, _snippet, create_app
from brandguard.errors import RateLimited
from conftest import IRA, NEHA, Session

BODY = "Hi there, our Brewline blend is a cheap way to wake up. Come now!"
AI_REPLY = json.dumps([{"rule_code": "G-01", "quote": "x", "span": "cheap way to wake up", "issue": "reads as cheap",
                        "severity": "low", "confidence": "low", "fix": ""}])


def _wait(app):
    for f in list(app.ai_futures):
        f.result(timeout=20)


def test_ai_findings_are_not_added_to_approved_content(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AI_ASYNC", "1")
    gate = threading.Event()

    def call(system, user, model):
        gate.wait(10)
        return AI_REPLY
    app = create_app(str(tmp_path / "a.db"), llm_call=call)
    Session(app, IRA).post("/api/kb/seed")
    cid = Session(app, NEHA).post("/api/content", title="t", body=BODY, images=[]).get_json()["id"]
    conn = dbm.connect(app.config["DB_PATH"])
    conn.execute("UPDATE content SET status='approved' WHERE id=?", (cid,))  # approved while the AI check is pending
    conn.commit()
    gate.set()
    _wait(app)
    assert conn.execute("SELECT COUNT(*) FROM findings WHERE content_id=? AND ai_generated=1", (cid,)).fetchone()[0] == 0
    meta = json.loads(conn.execute("SELECT review_meta FROM versions WHERE content_id=?", (cid,)).fetchone()[0])
    assert meta["llm_status"].startswith("skipped"), "the review must not stay pending forever"


def test_rereview_with_a_json_list_body_is_a_400(seeded, login, demo):
    n = login(NEHA)
    cid = n.post("/api/content", title=demo["title"], body=demo["body"], images=[]).get_json()["id"]
    r = n.c.post(f"/api/content/{cid}/review", json=["use_ai"])
    assert r.status_code == 400


def test_search_treats_percent_and_underscore_literally(seeded, login, demo):
    n = login(NEHA)
    n.post("/api/content", title=demo["title"], body=demo["body"], images=[])
    assert n.get("/api/search?q=%25%25").get_json()["results"] == []  # "%%" is not a wildcard
    assert n.get("/api/search?q=__").get_json()["results"] == []
    assert n.get("/api/search?q=Brewline").get_json()["results"]


def test_like_pattern_and_snippet_helpers():
    assert _like_pattern("50%_x") == "%50\\%\\_x%"
    long = "a" * 500 + "NEEDLE" + "b" * 500
    snip = _snippet(long, "needle")
    assert "NEEDLE" in snip and len(snip) <= 242
    assert _snippet("short", "sh") == "short"


def test_ai_requests_are_capped_per_user(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AI_RATE_LIMIT", "2")
    app = create_app(str(tmp_path / "r.db"), llm_call=lambda s, u, m: "[]")
    Session(app, IRA).post("/api/kb/seed")
    n = Session(app, NEHA)
    codes = [n.post("/api/content", title="t", body=BODY, images=[]).status_code for _ in range(3)]
    assert codes == [201, 201, 429]
    # rules-only requests do not reach the provider, so they are not counted
    assert n.post("/api/content", title="t", body=BODY, images=[], use_ai=False).status_code == 201
    # another user has their own allowance
    assert Session(app, IRA).post("/api/content", title="t", body=BODY, images=[]).status_code in (201, 403)


def test_spend_refuses_over_the_limit_and_does_not_count_refusals(tmp_path):
    conn = dbm.connect(str(tmp_path / "t.db"))
    dbm.init(conn)
    for _ in range(3):
        throttle.spend(conn, "ai:1", 3, now=1000.0)
    for _ in range(5):
        with pytest.raises(RateLimited):
            throttle.spend(conn, "ai:1", 3, now=1001.0)
    assert conn.execute("SELECT COUNT(*) FROM login_failures WHERE key='ai:1'").fetchone()[0] == 3
    throttle.spend(conn, "ai:1", 3, now=1000.0 + throttle.WINDOW + 1)  # the window moved on
    throttle.spend(conn, "ai:9", 0)  # limit 0 = no cap


def test_review_is_attributed_to_the_user_who_caused_it(seeded, login, demo):
    n = login(NEHA)
    cid = n.post("/api/content", title=demo["title"], body=demo["body"], images=[]).get_json()["id"]
    conn = dbm.connect(seeded.config["DB_PATH"])
    rows = conn.execute("SELECT user_id FROM audit WHERE content_id=? AND action='review_run'", (cid,)).fetchall()
    assert rows and all(r["user_id"] == NEHA for r in rows)


def test_settle_only_touches_reviews_whose_status_is_pending(tmp_path):
    conn = dbm.connect(str(tmp_path / "s.db"))
    dbm.init(conn)
    conn.execute("INSERT INTO users(name, role, is_external) VALUES ('u','creator',0)")
    conn.execute("INSERT INTO content(title, author_id, status, current_version, created_at) VALUES ('t',1,'draft',1,'x')")
    meta = json.dumps({"llm_status": "used", "warnings": ["a pending decision on the logo"],
                       "pending_since": "2000-01-01T00:00:00+00:00"})
    conn.execute("INSERT INTO versions(content_id, version, body, images, created_by, note, created_at, review_meta) "
                 "VALUES (1,1,'b','[]',1,'n','x',?)", (meta,))
    conn.commit()
    assert wf.settle_interrupted_reviews(conn) == 0


def test_sso_login_is_throttled(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AUTH", "accounts")
    monkeypatch.setenv("BRANDGUARD_ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setenv("BRANDGUARD_ADMIN_PASSWORD", "correct-horse-battery")
    monkeypatch.setenv("BRANDGUARD_SSO_EMAIL_HEADER", "X-Auth-Request-Email")
    monkeypatch.setenv("BRANDGUARD_SSO_SECRET", "s" * 24)
    c = create_app(str(tmp_path / "sso.db")).test_client()
    bad = {"X-Auth-Request-Email": "boss@example.com", "X-SSO-Secret": "wrong"}
    codes = [c.post("/api/sso/login", headers=bad).status_code for _ in range(throttle.LIMIT + 1)]
    assert codes[:throttle.LIMIT] == [401] * throttle.LIMIT and codes[-1] == 429
    good = {"X-Auth-Request-Email": "boss@example.com", "X-SSO-Secret": "s" * 24}
    assert c.post("/api/sso/login", headers=good).status_code == 429  # blocked until the window passes


def test_mfa_disable_refused_for_shared_demo_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AUTH", "accounts")
    monkeypatch.setenv("BRANDGUARD_ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setenv("BRANDGUARD_ADMIN_PASSWORD", "correct-horse-battery")
    monkeypatch.setenv("BRANDGUARD_SEED_DEMO", "1")
    monkeypatch.setenv("BRANDGUARD_DEMO_PASSWORD", "demo-password-123")
    c = create_app(str(tmp_path / "d.db")).test_client()
    assert c.post("/api/login", json={"email": "arjun@brewline.demo", "password": "demo-password-123"}).status_code == 200
    assert c.post("/api/mfa/disable", json={"password": "demo-password-123", "code": "123456"}).status_code == 403
