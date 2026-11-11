"""Hardening: input limits, malformed requests, login, rate limits, concurrency and security headers."""
import io
import json
from pathlib import Path

import pytest

from brandguard import db, engine, kb, workflow as wf
from brandguard.app import create_app
from conftest import ARJUN, IRA, NEHA

SEED = Path(__file__).resolve().parent.parent / "seed"


def review(tmp_path, body, images=()):
    conn = db.connect(str(tmp_path / "h.db"))
    db.init(conn)
    kb.seed_demo(conn, SEED)
    return engine.review(engine.load_kb(conn), body, list(images))


# ------------------------------------------------------------ engine false positives
def test_ranking_regex_has_word_boundaries(tmp_path):
    r = review(tmp_path, "We are #10 on the chart and have no 100 problems. Item #1 is shipped.")
    flagged = [f.span_text for f in r.findings if f.category == "claim"]
    assert flagged == ["#1"]  # only the real "#1" (and not the verb after it), not "#10" or "no 100"
    fixes = [f.suggested_fix for f in review(tmp_path, "India's #1 coffee is here.").findings if f.category == "claim"]
    assert fixes == ["Our coffee"]
    for text in ("We are No. 1 in tea.", "Truly number one in India.", "India's #1 coffee."):
        assert [f for f in review(tmp_path, text).findings if f.category == "claim"], text


def test_price_regex_ignores_letters_before_rs(tmp_path):
    r = review(tmp_path, "Our ADRs 300 holders. Launching soon.")
    assert not [c for c in r.claims if c["status"] == "contradicted"]
    for text in ("Pouch is Rs 399 today.", "Pouch is Rs.399 today.", "Pouch is INR 399 today.", "Pouch is ₹399."):
        assert any(f.source_id == "F-01" for f in review(tmp_path, text).findings), text


# ------------------------------------------------------------------ knowledge base
def test_mixed_guideline_document_keeps_every_rule(tmp_path):
    conn = db.connect(str(tmp_path / "m.db"))
    db.init(conn)
    out = kb.import_guidelines(
        conn, "Mixed", "G-90 | A: Be kind to every customer always.\n\nNever promise delivery dates in any email.")
    assert out["rules"] == 2
    codes = {r["code"] for r in conn.execute("SELECT code FROM rules")}
    assert "G-90" in codes and any(c.startswith("S") for c in codes)


def test_bad_facts_are_rejected_at_import_not_at_review_time(tmp_path):
    conn = db.connect(str(tmp_path / "f.db"))
    db.init(conn)
    good = {"code": "F-9", "kind": "date", "statement": "Launch is 1 Jan 2027.", "data": {"date": "2027-01-01"}}
    for bad, fragment in [
        ({**good, "data": {"date": "soon"}}, "YYYY-MM-DD"),
        ({"code": "F-8", "kind": "price", "statement": "x y z", "data": {"amount": "cheap"}}, "numeric"),
        ({**good, "code": "F-7", "data": {"date": "2027-01-01", "match": "launch"}}, "list of text"),
        ({**good, "code": "F-6", "data": []}, "object"),
    ]:
        with pytest.raises(ValueError, match=fragment):
            kb.import_facts(conn, [bad])
    assert kb.import_facts(conn, [good]) == 1
    with pytest.raises(ValueError, match="already exists"):
        kb.import_facts(conn, [good])
    with pytest.raises(ValueError, match="number"):
        kb.import_settings(conn, {"rule_checks": {"alt_text": {"rule_code": "G-06", "min_len": "five"}}})


def test_unreadable_files_give_a_clear_error():
    with pytest.raises(ValueError, match="Could not read"):
        kb.extract_text("broken.pdf", b"not a pdf at all")
    with pytest.raises(ValueError, match="Could not read"):
        kb.extract_text("broken.docx", b"not a docx")


# --------------------------------------------------------------------- AI behaviour
AI_REPLY = json.dumps([{
    "rule_code": "G-01", "quote": "Avoid slang and hype", "span": "taste the difference",
    "issue": "Generic hype phrase.", "severity": "low", "confidence": "medium", "fix": "enjoy it for yourself",
}])


@pytest.fixture()
def ai_app(tmp_path):
    calls = []

    def fake(system, user, model):
        calls.append(1)
        return AI_REPLY

    app = create_app(str(tmp_path / "ai.db"), llm_call=fake)
    return app, calls


def sess(app, uid):
    c = app.test_client()
    c.post("/api/login", json={"user_id": uid})
    return c


def make_ai_content(app, demo):
    sess(app, IRA).post("/api/kb/seed")
    neha = sess(app, NEHA)
    cid = neha.post("/api/content", json=demo).get_json()["id"]
    return neha, cid


def test_applying_fixes_does_not_resend_content_to_the_ai(ai_app, demo):
    app, calls = ai_app
    neha, cid = make_ai_content(app, demo)
    assert len(calls) == 1
    for _ in range(3):
        d = neha.get(f"/api/content/{cid}").get_json()
        f = next(x for x in d["findings"] if x["suggested_fix"] and not x["ai_generated"])
        assert neha.post(f"/api/findings/{f['id']}/decide", json={"action": "accept"}).status_code == 200
    assert len(calls) == 1  # still one call
    d = neha.get(f"/api/content/{cid}").get_json()
    ai = [f for f in d["findings"] if f["ai_generated"]]
    assert len(ai) == 1 and ai[0]["span_text"] == "taste the difference"  # carried over, re-located
    assert "not re-run" in d["review_meta"]["llm_status"] or "carried over" in d["review_meta"]["llm_status"]
    assert d["content"]["current_version"] == 4


def test_explicit_rerun_and_author_edit_do_call_the_ai(ai_app, demo):
    app, calls = ai_app
    neha, cid = make_ai_content(app, demo)
    assert neha.post(f"/api/content/{cid}/review", json={}).status_code == 200
    assert len(calls) == 2
    body = neha.get(f"/api/content/{cid}").get_json()["body"]
    neha.post(f"/api/content/{cid}/revise", json={"body": body + "\n", "images": demo["images"]})
    assert len(calls) == 3


def test_dismissed_ai_finding_stays_dismissed_and_accepted_one_disappears(ai_app, demo):
    app, calls = ai_app
    neha, cid = make_ai_content(app, demo)
    d = neha.get(f"/api/content/{cid}").get_json()
    ai = next(f for f in d["findings"] if f["ai_generated"])
    assert neha.post(f"/api/findings/{ai['id']}/decide", json={"action": "dismiss", "reason": "Brand slogan"}).status_code == 200
    price = next(f for f in neha.get(f"/api/content/{cid}").get_json()["findings"] if f["source_id"] == "F-01")
    neha.post(f"/api/findings/{price['id']}/decide", json={"action": "accept"})
    again = next(f for f in neha.get(f"/api/content/{cid}").get_json()["findings"] if f["ai_generated"])
    assert again["decision"] == "dismissed" and "Brand slogan" in again["decision_reason"]
    assert len(calls) == 1


def test_accepting_the_ai_fix_removes_it_without_another_call(ai_app, demo):
    app, calls = ai_app
    neha, cid = make_ai_content(app, demo)
    ai = next(f for f in neha.get(f"/api/content/{cid}").get_json()["findings"] if f["ai_generated"])
    neha.post(f"/api/findings/{ai['id']}/decide", json={"action": "accept"})
    d = neha.get(f"/api/content/{cid}").get_json()
    assert "enjoy it for yourself" in d["body"] and not [f for f in d["findings"] if f["ai_generated"]]
    assert len(calls) == 1


# ------------------------------------------------------------------ errors and auth
def test_real_bugs_are_500_not_404_and_missing_records_are_404(app, login):
    login(IRA).post("/api/kb/seed")
    fresh = create_app(str(Path(app.config["DB_PATH"]).with_name("boom.db")))

    @fresh.get("/boom")
    def boom():
        return {}["missing"]  # a genuine KeyError bug

    r = fresh.test_client().get("/boom")
    assert r.status_code == 500 and "went wrong" in r.get_json()["error"] and "missing" not in r.get_json()["error"]
    neha = login(NEHA)
    assert neha.get("/api/content/999").status_code == 404
    assert neha.post("/api/findings/999/decide", action="accept").status_code == 404
    assert app.test_client().get("/api/nope").status_code == 404
    assert app.test_client().get("/api/nope").get_json()["error"]


def test_malformed_requests_are_400_not_500(seeded, login):
    neha = login(NEHA)
    for body in ([], "text", 5):
        r = neha.c.post("/api/content", json=body)
        assert r.status_code == 400, body
    assert neha.c.post("/api/content", data="not json", content_type="application/json").status_code == 400
    assert neha.post("/api/content", title="T", body=123, images=[]).status_code == 400
    assert neha.post("/api/content", title=["x"], body="b", images=[]).status_code == 400
    big = neha.c.post("/api/kb/import", data={"kind": "facts", "file": (io.BytesIO(b"x" * (11 * 1024 * 1024)), "f.json")})
    assert big.status_code in (400, 403, 413)


def test_input_limits_and_image_validation(seeded, login):
    neha = login(NEHA)
    ok = {"title": "T", "body": "Hello there.", "images": []}
    assert neha.post("/api/content", **ok).status_code == 201
    assert neha.post("/api/content", **{**ok, "title": "x" * 201}).status_code == 400
    assert neha.post("/api/content", **{**ok, "body": "x" * 50_001}).status_code == 400
    assert neha.post("/api/content", **{**ok, "images": [{"name": f"i{i}"} for i in range(21)]}).status_code == 400
    assert neha.post("/api/content", **{**ok, "images": "hero.png"}).status_code == 400
    assert neha.post("/api/content", **{**ok, "images": ["hero.png"]}).status_code == 400
    dup = neha.post("/api/content", **{**ok, "images": [{"name": "a.png"}, {"name": "a.png"}]})
    assert dup.status_code == 400 and "twice" in dup.get_json()["error"]
    bad = neha.post("/api/content", **{**ok, "images": [{"name": "a.png", "text_color": "red", "bg_color": "#fff"}]})
    assert bad.status_code == 400 and "#RRGGBB" in bad.get_json()["error"]
    short = neha.post("/api/content", **{**ok, "images": [{"name": "a.png", "alt": "A pouch on a table", "text_color": "#444", "bg_color": "fff"}]})
    cid = short.get_json()["id"]
    assert neha.get(f"/api/content/{cid}").get_json()["images"][0]["text_color"] == "#444444"  # normalised


def test_colour_edit_is_validated_and_content_cannot_be_emptied(seeded, login, demo):
    neha = login(NEHA)
    cid = neha.post("/api/content", title="T", body=demo["body"], images=demo["images"]).get_json()["id"]
    f = next(x for x in neha.get(f"/api/content/{cid}").get_json()["findings"] if x["target"].startswith("image.text_color"))
    assert neha.post(f"/api/findings/{f['id']}/decide", action="edit", text="javascript:alert(1)").status_code == 400
    assert neha.post(f"/api/findings/{f['id']}/decide", action="edit", text="#222").status_code == 200
    only = neha.post("/api/content", title="T2", body="cheap", images=[]).get_json()["id"]
    g = neha.get(f"/api/content/{only}").get_json()["findings"][0]
    r = neha.post(f"/api/findings/{g['id']}/decide", action="edit", text="")
    assert r.status_code == 400 and "empty" in r.get_json()["error"]


def test_stale_writes_are_refused(seeded, login, demo, tmp_path):
    neha = login(NEHA)
    cid = neha.post("/api/content", title="T", body=demo["body"], images=demo["images"]).get_json()["id"]
    conn = db.connect(seeded.config["DB_PATH"])
    stale = dict(conn.execute("SELECT * FROM content WHERE id=?", (cid,)).fetchone())
    f = next(x for x in neha.get(f"/api/content/{cid}").get_json()["findings"] if x["suggested_fix"])
    assert neha.post(f"/api/findings/{f['id']}/decide", action="accept").status_code == 200  # someone else moves it to v2
    with pytest.raises(ValueError, match="Someone else"):
        wf._new_version(conn, stale, NEHA, "body", [], "late", None)
    twice = neha.post(f"/api/findings/{f['id']}/decide", action="accept")
    assert twice.status_code == 400
    versions = [v["version"] for v in neha.get(f"/api/content/{cid}").get_json()["versions"]]
    assert versions == [2, 1]  # no duplicate or skipped version


def test_passcode_login_and_rate_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_PASSCODE", "open-sesame")
    monkeypatch.setenv("BRANDGUARD_ADMIN_PASSCODE", "admin-only")
    app = create_app(str(tmp_path / "p.db"))
    c = app.test_client()
    assert c.get("/api/config").get_json() == {"passcode_required": True}
    assert c.post("/api/login", json={"user_id": NEHA}).status_code == 403
    assert c.get("/api/me").status_code == 401  # a failed login does not sign anyone in
    assert c.post("/api/login", json={"user_id": NEHA, "passcode": "open-sesame"}).status_code == 200
    assert c.get("/api/me").get_json()["name"] == "Neha"
    assert c.post("/api/login", json={"user_id": IRA, "passcode": "open-sesame"}).status_code == 403  # admin needs its own
    assert c.post("/api/login", json={"user_id": IRA, "passcode": "admin-only"}).status_code == 200
    codes = [c.post("/api/login", json={"user_id": ARJUN, "passcode": f"guess{i}"}).status_code for i in range(12)]
    assert codes[-1] == 429
    assert c.post("/api/login", json={"user_id": ARJUN, "passcode": "open-sesame"}).status_code == 429


def test_open_demo_mode_has_no_passcode(app):
    assert app.test_client().get("/api/config").get_json() == {"passcode_required": False}


def test_production_refuses_to_start_unprotected(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_ENV", "production")
    with pytest.raises(RuntimeError, match="BRANDGUARD_PASSCODE"):
        create_app(str(tmp_path / "x.db"))
    monkeypatch.setenv("BRANDGUARD_SECRET", "s" * 20)
    monkeypatch.setenv("BRANDGUARD_PASSCODE", "pw")
    app = create_app(str(tmp_path / "x.db"))
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_session_secret_survives_restart_and_cookie_flags(tmp_path):
    path = str(tmp_path / "s.db")
    first, second = create_app(path), create_app(path)
    assert first.config["SECRET_KEY"] == second.config["SECRET_KEY"]
    assert (tmp_path / "s.db.secret").stat().st_mode & 0o077 == 0  # owner-only
    c = first.test_client()
    r = c.post("/api/login", json={"user_id": NEHA})
    cookie = r.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_security_headers_and_no_store(app):
    r = app.test_client().get("/api/users")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["Cache-Control"] == "no-store"


def test_sentence_splitter_respects_abbreviations(tmp_path):
    assert [t.strip() for _, t in engine.sentences("We are No. 1 in tea. Pouch is Rs. 399 today! Done.")] == [
        "We are No. 1 in tea.", "Pouch is Rs. 399 today!", "Done."]
    body = "Line one.\nLine two. Line three"
    for off, text in engine.sentences(body):
        assert body[off:off + len(text)] == text  # offsets still point at the exact text
    price = [f for f in review(tmp_path, "Grab it for Rs. 399 now.").findings if f.source_id == "F-01"]
    assert price and price[0].span_text == "Rs. 399"  # was silently missed when "Rs." ended a sentence
