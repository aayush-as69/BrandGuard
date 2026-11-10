"""Revise/decide/approve flow hardening."""
import pytest

from brandguard import db, workflow as wf
from brandguard.errors import Forbidden
from conftest import ARJUN, MEERA, NEHA


def test_a_manager_who_edited_the_content_cannot_approve_it(seeded, login):
    n, arjun = login(NEHA), login(ARJUN)
    cid = n.post("/api/content", title="t", body="Hello there.", images=[]).get_json()["id"]
    conn = db.connect(seeded.config["DB_PATH"])
    user = dict(conn.execute("SELECT * FROM users WHERE id=?", (ARJUN,)).fetchone())
    c = wf.get_content(conn, user, cid)
    wf._new_version(conn, c, ARJUN, "Hello there, friend.", [], "Edited by manager", None)
    conn.close()
    n.post(f"/api/content/{cid}/submit")
    r = arjun.post(f"/api/content/{cid}/approve")
    assert r.status_code == 403
    assert login(MEERA).post(f"/api/content/{cid}/approve").status_code == 200


def test_stale_status_changes_are_refused(seeded, login):
    n = login(NEHA)
    cid = n.post("/api/content", title="t", body="Hello there.", images=[]).get_json()["id"]
    conn = db.connect(seeded.config["DB_PATH"])
    user = dict(conn.execute("SELECT * FROM users WHERE id=?", (NEHA,)).fetchone())
    n.post(f"/api/content/{cid}/submit")
    reviewer = dict(conn.execute("SELECT * FROM users WHERE id=?", (MEERA,)).fetchone())
    wf.request_changes(conn, reviewer, cid, "fix")
    with pytest.raises((ValueError, Forbidden)):
        wf.request_changes(conn, reviewer, cid, "again")
    conn.close()


def test_docx_tables_are_read_in_order_and_merged_cells_once():
    import io
    import docx
    from brandguard import kb
    d = docx.Document()
    d.add_paragraph("Voice rules")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "R1", "Never say cheap"
    a = t.cell(1, 0).merge(t.cell(1, 1))
    a.text = "Merged note"
    d.add_paragraph("After the table")
    buf = io.BytesIO(); d.save(buf)
    out = kb.extract_text("g.docx", buf.getvalue()).splitlines()
    assert out == ["Voice rules", "R1 | Never say cheap", "Merged note", "After the table"]


def test_pdf_running_headers_and_page_numbers_are_dropped():
    from brandguard import kb
    pages = [f"Brewline Brand Guide\nRule {i}: keep it warm.\nPage {i}" for i in range(1, 5)]
    out = "\n".join(kb._drop_running_lines(pages))
    assert "Brewline Brand Guide" not in out and "Page 2" not in out
    assert "Rule 3: keep it warm." in out
    assert kb._drop_running_lines(pages[:2]) == pages[:2]


def test_two_workers_bootstrapping_the_admin_at_once_do_not_crash(tmp_path, monkeypatch):
    """Render's gunicorn started two workers; both saw 'no admin yet' and the second insert hit the unique email."""
    from brandguard import app as appmod, db as dbm
    monkeypatch.setenv("BRANDGUARD_ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setenv("BRANDGUARD_ADMIN_PASSWORD", "correct-horse-battery")
    path = str(tmp_path / "r.db")
    first = dbm.connect(path); dbm.init(first, demo_users=False)
    appmod._bootstrap_admin(first, True)

    class Stale:   # a second worker whose first look ("is there an admin?") happened before the first worker's insert
        def __init__(self, c): self.c, self.n = c, 0
        def execute(self, sql, *a):
            if "role='admin'" in sql and self.n == 0:
                self.n += 1
                return dbm.connect(":memory:").execute("SELECT 1 WHERE 0")
            return self.c.execute(sql, *a)
        def __getattr__(self, name): return getattr(self.c, name)

    appmod._bootstrap_admin(Stale(dbm.connect(path)), True)   # must not raise
    n = first.execute("SELECT COUNT(*) FROM users WHERE email='boss@example.com'").fetchone()[0]
    assert n == 1


def test_demo_workspace_seeding_is_complete_and_repeatable(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AUTH", "accounts")
    monkeypatch.setenv("BRANDGUARD_ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setenv("BRANDGUARD_ADMIN_PASSWORD", "correct-horse-battery")
    monkeypatch.setenv("BRANDGUARD_SEED_DEMO", "1")
    monkeypatch.setenv("BRANDGUARD_DEMO_PASSWORD", "demo-password-123")
    from brandguard.app import create_app
    path = str(tmp_path / "d.db")
    create_app(path)
    app = create_app(path)          # a second start must not duplicate anything
    conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM guidelines").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM users WHERE email LIKE '%@brewline.demo'").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM content").fetchone()[0] == 1
    c = app.test_client()
    assert c.post("/api/login", json={"email": "arjun@brewline.demo", "password": "demo-password-123"}).status_code == 200


def test_demo_role_switch_only_between_demo_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AUTH", "accounts")
    monkeypatch.setenv("BRANDGUARD_ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setenv("BRANDGUARD_ADMIN_PASSWORD", "correct-horse-battery")
    monkeypatch.setenv("BRANDGUARD_SEED_DEMO", "1")
    monkeypatch.setenv("BRANDGUARD_DEMO_PASSWORD", "brandguard")
    from brandguard.app import create_app
    app = create_app(str(tmp_path / "s.db"))
    admin = app.test_client()
    admin.post("/api/login", json={"email": "boss@example.com", "password": "correct-horse-battery"})
    assert admin.post("/api/demo/switch-role", json={"role": "manager"}).status_code == 403   # real admin cannot hop
    c = app.test_client()
    c.post("/api/login", json={"email": "arjun@brewline.demo", "password": "brandguard"})
    assert c.post("/api/demo/switch-role", json={"role": "creator"}).get_json()["name"] == "Rahul"
    assert c.post("/api/demo/switch-role", json={"role": "agency"}).get_json()["name"] == "Neha"
    assert c.post("/api/demo/switch-role", json={"role": "admin"}).status_code == 400          # no hopping to admin
