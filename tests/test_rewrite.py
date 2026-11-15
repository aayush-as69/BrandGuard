"""Three-strength rewrites: what each strength changes, the safety checks, hiding and applying."""
import json

from conftest import ARJUN, IRA, MEERA, NEHA, RAHUL

from brandguard import rewrite as rw


def make(session, demo):
    r = session.post("/api/content", title=demo["title"], body=demo["body"], images=demo["images"])
    assert r.status_code == 201
    return r.get_json()["id"]


def opts(session, cid):
    d = session.get(f"/api/content/{cid}/rewrites").get_json()
    return {o["strength"]: o for o in d["options"]}


def make_text(session, body, title="Test"):
    return session.post("/api/content", title=title, body=body, images=[]).get_json()["id"]


def test_each_strength_adds_more_and_none_changes_a_price_wrongly(seeded, login, demo):
    s = login(NEHA)
    o = opts(s, make(s, demo))
    n = {k: len(v["changes"]) for k, v in o.items()}
    assert 0 < n["minimal"] < n["balanced"] <= n["full"]
    assert all(v["status"] == "ok" for v in o.values())
    assert "₹449" in o["minimal"]["body"] and "₹399" not in o["minimal"]["body"]
    assert "1 December 2026" in o["minimal"]["body"]                           # F-02 is restricted for Neha, so it is never used for her
    assert all(c["source_id"] != "F-02" for c in o["full"]["changes"])
    m = opts(login(ARJUN), s.get("/api/content").get_json()[0]["id"])           # a manager sees the launch date and gets that fix too
    assert "1 December 2026" not in m["minimal"]["body"] and "15 December 2026" in m["minimal"]["body"]
    assert "!!!" in o["minimal"]["body"] and "!!!" not in o["full"]["body"]     # polish only arrives in Full
    assert "Dude" in o["minimal"]["body"] and "Dude" not in o["balanced"]["body"]  # slang is a wording fix: Balanced


def test_minimal_contains_only_high_severity_rule_based_high_confidence_fixes(seeded, login, demo):
    s = login(NEHA)
    o = opts(s, make(s, demo))
    assert all(c["severity"] == "high" and not c["ai_generated"] for c in o["minimal"]["changes"])


def test_every_option_passes_all_six_checks_and_shows_them(seeded, login, demo):
    s = login(NEHA)
    o = opts(s, make(s, demo))["full"]
    assert [c["id"] for c in o["checks"]] == ["numbers", "facts", "clean", "support", "length", "nonempty"]
    assert all(c["ok"] for c in o["checks"])
    assert any(seg["op"] == "added" for seg in o["diff"]) and any(seg["op"] == "removed" for seg in o["diff"])
    assert "".join(seg["text"] for seg in o["diff"] if seg["op"] != "removed") == o["body"]


def test_an_option_identical_to_a_smaller_one_says_so(seeded, login):
    s = login(NEHA)
    o = opts(s, make_text(s, "The 250g pouch is only ₹399 this week."))
    assert o["minimal"]["same_as"] is None and o["balanced"]["same_as"] == "minimal" and o["full"]["same_as"] == "minimal"


def test_clean_content_has_no_options_to_offer(seeded, login):
    s = login(NEHA)
    o = opts(s, make_text(s, "Hello friend. The 250g pouch is ₹449."))
    assert {v["status"] for v in o.values()} == {"none"}


def test_low_confidence_findings_are_never_applied(seeded, login):
    s = login(NEHA)
    cid = make_text(s, "Free delivery above ₹999.")                          # guessed price: low confidence, needs a person
    d = s.get(f"/api/content/{cid}").get_json()
    assert any(f["confidence"] == "low" for f in d["findings"])
    assert {v["status"] for v in opts(s, cid).values()} == {"none"}


def test_an_unsafe_glossary_fix_is_hidden_and_cannot_be_applied(seeded, login):
    """An admin sets the preferred wording for 'cheap' to a different price. Rewriting would slip a wrong fact in."""
    ira = login(IRA)
    fd = {"kind": "glossary", "text": json.dumps([{"term": "bargain", "preferred": "₹399 priced", "kind": "banned", "rule_code": "G-03"}])}
    assert ira.c.post("/api/kb/import", data=fd).status_code == 200
    s = login(NEHA)
    cid = make_text(s, "A bargain way to start your morning.")
    o = opts(s, cid)
    assert o["balanced"]["status"] == "hidden" and o["balanced"]["body"] == "" and o["balanced"]["changes"] == []
    assert any(not c["ok"] for c in o["balanced"]["checks"])
    r = s.post(f"/api/content/{cid}/rewrites/balanced/apply")
    assert r.status_code == 400 and "safety checks" in r.get_json()["error"]
    assert s.get(f"/api/content/{cid}").get_json()["content"]["current_version"] == 1       # nothing was applied


def test_validate_catches_each_kind_of_problem(seeded, app):
    from brandguard import db as dbm, engine
    kb = engine.load_kb(dbm.connect(app.config["DB_PATH"]))
    fx = {"id": 1, "source_type": "guideline", "span_text": "cheap", "suggested_fix": "₹399 priced"}
    r = {c["id"]: c for c in rw.validate(kb, "A cheap start. Only ₹449.", [], "A ₹399 priced start. Only ₹449.", [fx])}
    assert not r["numbers"]["ok"] and not r["facts"]["ok"] and not r["clean"]["ok"]
    big = rw.validate(kb, "A cheap start to a long morning of coffee.", [], "Ok", [{**fx, "suggested_fix": "Ok"}])
    assert not {c["id"]: c for c in big}["length"]["ok"]
    empty = {c["id"]: c for c in rw.validate(kb, "x", [], "  ", [])}
    assert not empty["nonempty"]["ok"]


def test_overlapping_fixes_apply_once(seeded, login):
    f = lambda i, s, e, t, fx: {"id": i, "span_start": s, "span_end": e, "span_text": t, "suggested_fix": fx}
    body, applied, skipped = rw._splice("abcdef", [f(1, 0, 3, "abc", "X"), f(2, 2, 5, "cde", "Y"), f(3, 5, 6, "f", "Z")])
    assert body == "XdeZ" and [a["id"] for a in applied] == [1, 3] and [k["id"] for k in skipped] == [2]


def test_applying_creates_a_version_marks_findings_accepted_and_audits(seeded, login, demo, app):
    s = login(NEHA)
    cid = make(s, demo)
    out = s.post(f"/api/content/{cid}/rewrites/minimal/apply").get_json()
    assert out["new_version"] == 2 and out["applied"] > 0
    d = s.get(f"/api/content/{cid}").get_json()
    assert "₹449" in d["body"] and "₹399" not in d["body"]
    assert {h["decision"] for h in d["history"]} == {"accepted"} and len(d["history"]) == out["applied"]
    assert any(a["action"] == "rewrite_applied" for a in login(ARJUN).get(f"/api/content/{cid}").get_json()["audit"])
    left = {f["source_id"] for f in d["findings"] if f["severity"] == "high"}
    assert left == {"F-02", "G-06"}                                # only what has no safe automatic fix is left for a person
    assert d["versions"][0]["note"].startswith("Minimal rewrite")


def test_permissions_and_validation(seeded, login, demo):
    neha, arjun = login(NEHA), login(ARJUN)
    cid = make(neha, demo)
    assert login(RAHUL).get(f"/api/content/{cid}/rewrites").status_code == 403           # creators see only their own work
    assert neha.post(f"/api/content/{cid}/rewrites/huge/apply").status_code == 400
    assert neha.post(f"/api/content/{cid}/rewrites/full/apply").status_code == 200
    assert neha.post(f"/api/content/{cid}/rewrites/minimal/apply").status_code == 400    # nothing left to apply
    assert arjun.get(f"/api/content/{cid}/rewrites").status_code == 200                  # a manager can read them


def test_approved_content_is_locked(seeded, login):
    neha, meera = login(NEHA), login(MEERA)
    cid = make_text(neha, "Hello friend. The pouch is ₹449.")
    assert neha.post(f"/api/content/{cid}/submit").status_code == 200
    assert meera.post(f"/api/content/{cid}/approve").status_code == 200
    assert login(MEERA).post(f"/api/content/{cid}/rewrites/full/apply").status_code == 403


def test_restricted_sources_are_never_used_in_a_rewrite(seeded, login, demo, app):
    from brandguard import db as dbm
    c = dbm.connect(app.config["DB_PATH"])
    c.execute("UPDATE facts SET access_level='confidential' WHERE code='F-01'")
    c.commit()
    s = login(NEHA)                                                                         # internal clearance cannot see F-01
    cid = make(s, demo)
    o = opts(s, cid)
    assert "₹399" in o["full"]["body"] and all(ch["source_id"] != "F-01" for ch in o["full"]["changes"])


def test_the_ai_judge_is_never_called_for_rewrites(seeded, login, demo, monkeypatch):
    from brandguard import engine
    seen = []
    real = engine.review
    monkeypatch.setattr(engine, "review", lambda kb, body, images, judge=None, inherited=None: (seen.append(judge), real(kb, body, images, judge=judge, inherited=inherited))[1])
    s = login(NEHA)
    cid = make(s, demo)
    seen.clear()
    s.get(f"/api/content/{cid}/rewrites")
    assert seen and set(seen) == {None}
