"""Fourth pass: insights leaked confidential facts to agency reviewers; time-to-approval pairing."""
import pytest

from brandguard import insights
from brandguard.app import create_app
from conftest import ARJUN, MEERA, NEHA


@pytest.fixture()
def acct(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AUTH", "accounts")
    monkeypatch.setenv("BRANDGUARD_ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setenv("BRANDGUARD_ADMIN_PASSWORD", "correct-horse-battery")
    app = create_app(str(tmp_path / "r.db"))
    admin = app.test_client()
    admin.post("/api/login", json={"email": "boss@example.com", "password": "correct-horse-battery"})
    admin.post("/api/kb/seed")
    app.admin = admin
    return app


def test_agency_accounts_can_only_be_writers(acct):
    body = {"name": "E", "email": "e@x.in", "is_external": True, "password": "long-enough-pass"}
    for role in ("reviewer", "manager", "admin"):
        assert acct.admin.post("/api/users", json={**body, "role": role}).status_code == 400
    uid = acct.admin.post("/api/users", json={**body, "role": "creator"}).get_json()["id"]
    assert acct.admin.patch(f"/api/users/{uid}", json={"role": "reviewer"}).status_code == 400
    ok = acct.admin.post("/api/users", json={"name": "I", "email": "i@x.in", "role": "reviewer", "password": "long-enough-pass"})
    assert ok.status_code == 201
    assert acct.admin.patch(f"/api/users/{ok.get_json()['id']}", json={"is_external": True}).status_code == 400


def test_an_existing_external_reviewer_still_cannot_read_insights_or_the_ai_log(acct):
    """Even if such an account already exists (older data), the routes themselves refuse it."""
    import sqlite3
    uid = acct.admin.post("/api/users", json={"name": "E", "email": "e@x.in", "role": "creator", "is_external": True,
                                              "password": "long-enough-pass"}).get_json()["id"]
    con = sqlite3.connect(acct.config["DB_PATH"])
    con.execute("UPDATE users SET role='reviewer' WHERE id=?", (uid,))
    con.commit()
    e = acct.test_client()
    e.post("/api/login", json={"email": "e@x.in", "password": "long-enough-pass"})
    for url in ("/api/insights", "/api/llm-log"):
        r = e.get(url)
        assert r.status_code == 403 and "15 December" not in r.get_data(as_text=True), url


def test_time_to_approval_pairs_each_approval_with_its_own_submission(seeded, login):
    from brandguard import db
    n, arjun = login(NEHA), login(ARJUN)
    cid = n.post("/api/content", title="t", body="Hello there.", images=[]).get_json()["id"]
    n.post(f"/api/content/{cid}/submit")
    arjun.post(f"/api/content/{cid}/approve")
    conn = db.connect(seeded.config["DB_PATH"])
    # a later resubmission that is never approved must not drag the average to zero
    conn.execute("UPDATE audit SET created_at='2026-01-01T10:00:00+00:00' WHERE content_id=? AND action='submitted'", (cid,))
    conn.execute("UPDATE audit SET created_at='2026-01-01T14:00:00+00:00' WHERE content_id=? AND action='approved'", (cid,))
    conn.execute("INSERT INTO audit(content_id, user_id, action, detail, created_at) VALUES (?,?,?,?,?)",
                 (cid, None, "submitted", "again", "2026-02-01T10:00:00+00:00"))
    conn.commit()
    assert insights.compute(conn)["avg_hours_to_approve"] == 4.0
    conn.close()
