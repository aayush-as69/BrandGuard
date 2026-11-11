"""Second external review: stale comments, shared throttle, safe errors, upload limits, AI privacy patterns."""
import io
import json
import sqlite3
import zipfile

import pytest

from brandguard import kb as kbm
from brandguard import llm, throttle
from brandguard.app import create_app
from brandguard.errors import RateLimited
from conftest import ARJUN, IRA, NEHA, Session


# ---- A. comments only on current-version findings ---------------------------------------------
def test_comment_on_current_finding_ok_old_or_foreign_refused(seeded, login):
    n = login(NEHA)
    a = n.post("/api/content", title="a", body="Hi Dude. Buy now!!", images=[]).get_json()["id"]
    b = n.post("/api/content", title="b", body="Hi Dude. Buy now!!", images=[]).get_json()["id"]
    f1 = n.get(f"/api/content/{a}").get_json()["findings"][0]["id"]
    assert n.post(f"/api/content/{a}/comments", body="ok", finding_id=f1).status_code in (200, 201)
    n.post(f"/api/content/{a}/revise", body="Hello friend. Buy now!!", images=[])  # a new version supersedes f1
    assert n.post(f"/api/content/{a}/comments", body="late", finding_id=f1).status_code == 400
    fb = n.get(f"/api/content/{b}").get_json()["findings"][0]["id"]
    assert n.post(f"/api/content/{a}/comments", body="wrong item", finding_id=fb).status_code == 400


# ---- B. throttle shared between workers, fails closed ------------------------------------------
def test_failed_logins_from_two_workers_share_one_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AUTH", "accounts")
    monkeypatch.setenv("BRANDGUARD_ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setenv("BRANDGUARD_ADMIN_PASSWORD", "correct-horse-battery")
    path = str(tmp_path / "t.db")
    w1, w2 = create_app(path), create_app(path)  # two workers, one database
    c1, c2 = w1.test_client(), w2.test_client()
    bad = {"email": "boss@example.com", "password": "nope"}
    for i in range(5):
        assert c1.post("/api/login", json=bad).status_code == 401
        assert c2.post("/api/login", json=bad).status_code == 401
    assert c1.post("/api/login", json=bad).status_code == 429
    assert c2.post("/api/login", json={**bad, "password": "correct-horse-battery"}).status_code == 429


def test_throttle_expiry_and_outage(tmp_path):
    from brandguard import db
    conn = db.connect(str(tmp_path / "x.db"))
    db.init(conn)
    for _ in range(10):
        throttle.record(conn, "k", now=1000.0)
    with pytest.raises(RateLimited):
        throttle.check(conn, "k", now=1001.0)
    throttle.check(conn, "k", now=1000.0 + throttle.WINDOW + 1)  # expired failures are forgotten
    assert conn.execute("SELECT COUNT(*) FROM login_failures").fetchone()[0] == 0
    conn.execute("DROP TABLE login_failures")
    with pytest.raises(RateLimited):  # store broken: refuse, do not allow
        throttle.check(conn, "k")
    conn.close()


def test_successful_login_not_blocked_below_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AUTH", "accounts")
    monkeypatch.setenv("BRANDGUARD_ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setenv("BRANDGUARD_ADMIN_PASSWORD", "correct-horse-battery")
    c = create_app(str(tmp_path / "ok.db")).test_client()
    for _ in range(3):
        c.post("/api/login", json={"email": "boss@example.com", "password": "bad"})
    assert c.post("/api/login", json={"email": "boss@example.com", "password": "correct-horse-battery"}).status_code == 200


# ---- C. no SQL detail in responses -------------------------------------------------------------
def test_duplicate_email_gives_safe_message(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AUTH", "accounts")
    monkeypatch.setenv("BRANDGUARD_ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setenv("BRANDGUARD_ADMIN_PASSWORD", "correct-horse-battery")
    c = create_app(str(tmp_path / "d.db")).test_client()
    c.post("/api/login", json={"email": "boss@example.com", "password": "correct-horse-battery"})
    r = c.post("/api/users", json={"name": "X", "email": "BOSS@example.com", "role": "creator", "password": "long-enough-pass"})
    body = r.get_data(as_text=True)
    assert r.status_code == 400 and "already in use" in body
    for leak in ("UNIQUE", "users.", "sqlite", "constraint", "INSERT"):
        assert leak.lower() not in body.lower()


def test_other_integrity_errors_are_generic(app, monkeypatch):
    from brandguard import workflow as wf

    def boom(*a, **k):
        raise sqlite3.IntegrityError("NOT NULL constraint failed: content.secret_column")
    monkeypatch.setattr(wf, "list_content", boom)
    r = Session(app, NEHA).get("/api/content")
    assert r.status_code == 400 and "secret_column" not in r.get_data(as_text=True)


# ---- E. upload limits ----------------------------------------------------------------------------
def test_text_and_pdf_limits():
    with pytest.raises(ValueError, match="characters"):
        kbm.extract_text("big.txt", b"a" * (kbm.MAX_EXTRACT_CHARS + 1))
    pypdf = pytest.importorskip("pypdf")
    w = pypdf.PdfWriter()
    for _ in range(kbm.MAX_PDF_PAGES + 1):
        w.add_blank_page(100, 100)
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(ValueError, match="pages"):
        kbm.extract_text("many.pdf", buf.getvalue())
    w = pypdf.PdfWriter()
    w.add_blank_page(100, 100)
    w.encrypt("pw")
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(ValueError, match="password"):
        kbm.extract_text("locked.pdf", buf.getvalue())


def test_docx_zip_bomb_and_garbage_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"a" * (60 * 1024 * 1024))  # ~60 MB of zeros compresses to ~60 KB
    with pytest.raises(ValueError, match="unreasonable size"):
        kbm.extract_text("bomb.docx", buf.getvalue())
    with pytest.raises(ValueError, match="Could not read"):
        kbm.extract_text("junk.docx", b"not a zip at all")
    with pytest.raises(ValueError, match="Could not read"):
        kbm.extract_text("junk.pdf", b"%PDF-1.4 garbage")


def test_import_endpoint_reports_limit_as_400(app):
    ira = Session(app, IRA)
    r = ira.c.post("/api/kb/import", data={"kind": "glossary", "file": (io.BytesIO(b"a" * 600_000), "g.txt")},
                   content_type="multipart/form-data")
    assert r.status_code == 400


# ---- D. organisation-defined masking and blocking ---------------------------------------------------
@pytest.fixture()
def ai_app(tmp_path):
    calls = []

    def call(system, user, model):
        calls.append(user)
        return "[]"
    app = create_app(str(tmp_path / "p.db"), llm_call=call)
    app.calls = calls
    Session(app, IRA).post("/api/kb/seed")
    return app


def test_custom_mask_pattern_reaches_callback_masked_and_rules_still_run(ai_app, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AI_MASK_PATTERNS", json.dumps({"CODENAME": r"Project \w+"}))
    r = Session(ai_app, NEHA).post("/api/content", title="t", body="Hi there, Project Falcon is a cheap way to wake up. Buy now!!", images=[])
    assert r.status_code == 201
    assert "Project Falcon" not in ai_app.calls[0] and "[[CODENAME_1]]" in ai_app.calls[0]
    cid = r.get_json()["id"]
    assert Session(ai_app, NEHA).get(f"/api/content/{cid}").get_json()["findings"]  # rule checks unaffected


def test_block_pattern_sends_nothing_and_invalid_config_fails_closed(ai_app, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AI_BLOCK_PATTERNS", json.dumps({"EMBARGO": r"(?i)embargoed"}))
    n = Session(ai_app, NEHA)
    cid = n.post("/api/content", title="t", body="Hi there, embargoed: our Brewline blend is a cheap way to wake up.", images=[]).get_json()["id"]
    assert ai_app.calls == []
    assert "not sent to the AI" in n.get(f"/api/content/{cid}").get_json()["review_meta"]["llm_status"]
    monkeypatch.setenv("BRANDGUARD_AI_BLOCK_PATTERNS", "{broken json")
    cid = n.post("/api/content", title="t2", body="Hi there, our Brewline blend is a cheap way to wake up.", images=[]).get_json()["id"]
    assert ai_app.calls == []  # a broken privacy setting never means "send it anyway"
