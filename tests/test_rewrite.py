"""Rewrite options: three strengths, two checks, a diff, and the AI only on masked text."""
import json

import pytest

from brandguard import engine, rewrite as rw
from brandguard.app import create_app
from conftest import ARJUN, IRA, MEERA, NEHA, RAHUL, Session

BODY = "Dude, our new Signature Blend is insanely good!!!\n\nGrab a 250g pouch for just ₹399. Launching on 1 December 2026."


def draft(s, body=BODY, images=None):
    cid = s.post("/api/content", title="t", body=body, images=images or []).get_json()["id"]
    return cid, s.get(f"/api/content/{cid}").get_json()


def finding(d, text):
    return next(f for f in d["findings"] if f["span_text"] == text)


def opts(s, f, ai=False):
    r = s.post(f"/api/findings/{f['id']}/rewrites", use_ai=ai)
    assert r.status_code == 200, r.get_json()
    return r.get_json()


# ------------------------------------------------------------------ rules-based options
def test_a_finding_with_neighbours_gets_more_than_one_strength(seeded, login):
    n = login(NEHA)
    _, d = draft(n)
    o = opts(n, finding(d, "Dude"))
    assert [x["strength"] for x in o["options"]][:2] == ["minimal", "balanced"]
    assert o["options"][0]["after"] == "Hello"
    assert o["options"][1]["after"] == "Hello, our new Signature Blend is wonderful!"  # whole sentence, every fix in it
    assert all(x["source"] == "rules" for x in o["options"])


def test_the_full_strength_fixes_the_paragraph(seeded, login):
    n = login(NEHA)
    _, d = draft(n, "Grab a 250g pouch for just \u20b9399. It is a cheap price for Signature Blend.\n\nLaunching on 1 December 2026.")
    o = opts(n, finding(d, "\u20b9399"))
    assert [x["strength"] for x in o["options"]] == ["minimal", "full"]   # the sentence option equals the minimal one, so it is not repeated
    full = o["options"][1]
    assert full["after"] == "Grab a 250g pouch for just \u20b9449. It is an affordable price for Signature Blend."
    assert "1 December" not in json.dumps(o)  # the next paragraph and its restricted finding are left alone


def test_every_option_carries_a_diff_that_rebuilds_both_sides(seeded, login):
    n = login(NEHA)
    _, d = draft(n)
    for x in opts(n, finding(d, "Dude"))["options"]:
        assert "".join(p["text"] for p in x["diff"] if p["op"] != "ins") == x["before"]
        assert "".join(p["text"] for p in x["diff"] if p["op"] != "del") == x["after"]
        assert any(p["op"] != "equal" for p in x["diff"])


def test_applying_an_option_resolves_the_finding_and_makes_a_new_version(seeded, login):
    n = login(NEHA)
    cid, d = draft(n)
    f = finding(d, "Dude")
    o = next(x for x in opts(n, f)["options"] if x["strength"] == "balanced")
    r = n.post(f"/api/findings/{f['id']}/decide", action="rewrite", strength="balanced", text=o["after"])
    assert r.status_code == 200 and r.get_json()["new_version"] == 2
    d2 = n.get(f"/api/content/{cid}").get_json()
    assert d2["body"].startswith("Hello, our new Signature Blend is wonderful!\n\n")
    left = {x["span_text"] for x in d2["findings"] if x["decision"] == "open"}
    assert "Dude" not in left and "insanely good" not in left and "!!!" not in left
    assert any("rewrite (balanced)" in str(a) for a in login(ARJUN).get(f"/api/content/{cid}").get_json()["audit"])


def test_nothing_changes_until_the_author_clicks(seeded, login):
    n = login(NEHA)
    cid, d = draft(n)
    opts(n, finding(d, "Dude"))
    assert n.get(f"/api/content/{cid}").get_json()["body"] == BODY


def test_a_finding_with_no_safe_rewrite_says_so(seeded, login):
    n = login(NEHA)
    _, d = draft(n, "Visit us.", [{"name": "hero.png", "alt": "", "text_color": "#222222", "bg_color": "#ffffff"}])
    f = next(x for x in d["findings"] if x["target"].startswith("image.alt"))
    o = opts(n, f)
    assert o["options"] == [] and "No safe rewrite" in o["note"]


# ------------------------------------------------------------------ the checks, on the server
def test_a_tampered_rewrite_that_adds_a_violation_is_refused(seeded, login):
    n = login(NEHA)
    cid, d = draft(n)
    f = finding(d, "Dude")
    r = n.post(f"/api/findings/{f['id']}/decide", action="rewrite", strength="minimal", text="Bhai")
    assert r.status_code == 400 and "new finding" in r.get_json()["error"]
    assert n.get(f"/api/content/{cid}").get_json()["body"] == BODY


def test_a_rewrite_that_changes_a_price_is_refused(seeded, login):
    n = login(NEHA)
    _, d = draft(n)
    f = finding(d, "₹399")
    for bad in ("₹499", "₹399 or less", "₹120"):
        r = n.post(f"/api/findings/{f['id']}/decide", action="rewrite", strength="minimal", text=bad)
        assert r.status_code == 400, bad


def test_a_rewrite_that_does_not_fix_the_finding_is_refused(seeded, login):
    n = login(NEHA)
    _, d = draft(n)
    f = finding(d, "Dude")
    r = n.post(f"/api/findings/{f['id']}/decide", action="rewrite", strength="balanced",
               text="Dude, our new Signature Blend is wonderful!")
    assert r.status_code == 400 and "does not fix" in r.get_json()["error"]


def test_the_wrong_strength_or_missing_text_is_refused(seeded, login):
    n = login(NEHA)
    _, d = draft(n)
    f = finding(d, "Dude")
    assert n.post(f"/api/findings/{f['id']}/decide", action="rewrite", strength="huge", text="Hello").status_code == 400
    assert n.post(f"/api/findings/{f['id']}/decide", action="rewrite", strength="minimal").status_code == 400
    assert n.post(f"/api/findings/{f['id']}/decide", action="rewrite", strength="minimal", text="   ").status_code == 400


def test_restricted_findings_get_no_rewrite_and_cannot_be_applied(seeded, login):
    n = login(NEHA)
    _, d = draft(n)
    f = finding(d, "1 December 2026")
    assert f["restricted"] is True
    o = opts(n, f)
    assert o["options"] == [] and "restricted" in o["note"]
    r = n.post(f"/api/findings/{f['id']}/decide", action="rewrite", strength="minimal", text="15 December 2026")
    assert r.status_code == 403


def test_only_someone_who_can_decide_may_ask(seeded, login):
    n = login(NEHA)
    _, d = draft(n)
    f = finding(d, "Dude")
    assert login(RAHUL).post(f"/api/findings/{f['id']}/rewrites", use_ai=False).status_code == 403  # not their content
    assert login(ARJUN).post(f"/api/findings/{f['id']}/rewrites", use_ai=False).status_code == 200


# ------------------------------------------------------------------ fact preservation, directly
@pytest.fixture()
def kb(app, login):
    login(IRA).post("/api/kb/seed")
    from brandguard import db as dbm
    return engine.load_kb(dbm.connect(app.config["DB_PATH"]))


@pytest.mark.parametrize("before,after,expect", [
    ("A 250g pouch is ₹449.", "The 250g pouch costs ₹449.", None),
    ("A 250g pouch is ₹449.", "The 250g pouch costs ₹499.", "introduces"),
    ("A 250g pouch is ₹449.", "The 250g pouch is a bargain.", "drops the approved"),
    ("A 250g pouch is ₹449.", "The pouch is ₹449.", "250g"),
    ("It launches on 15 December 2026.", "It launches on 16 December 2026.", "introduces"),
    ("It launches on 15 December 2026.", "It launches soon.", "drops the approved"),
    ("Grab it for ₹399.", "Grab it for ₹449.", None),                 # the approved price replaces a wrong one
    ("Grab it for ₹399.", "Grab it.", None),                          # dropping a wrong price is fine
    ("Made from beans.", "Made from 100% beans.", "100%"),
    ("A Signature Blend pouch.", "A pouch.", "signature blend"),
    ("Beans from Coorg.", "Beans from Coorg estates.", None),
])
def test_facts_must_stay_identical(kb, before, after, expect):
    problem = rw.facts_problem(kb, before, after)
    assert (problem is None) if expect is None else (problem and expect in problem), problem


def test_tidy_cleans_the_seams_of_a_deletion():
    assert rw.tidy(", our new blend is here.", True) == "Our new blend is here."
    assert rw.tidy("A  good , blend .", False) == "A good, blend."


# ------------------------------------------------------------------ the AI path
class FakeAI:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def __call__(self, system, user, model):
        self.prompts.append((system, user))
        return self.reply(user) if callable(self.reply) else self.reply


def ai_app(tmp_path, reply):
    ai = FakeAI(reply)
    app = create_app(str(tmp_path / "ai.db"), llm_call=ai)
    Session(app, IRA).post("/api/kb/seed")
    return app, ai


def test_ai_wording_goes_through_the_same_checks(tmp_path):
    app, ai = ai_app(tmp_path, "Hello, our new Signature Blend is a joy from the very first sip.")
    n = Session(app, NEHA)
    _, d = draft(n, "Dude, our new Signature Blend is insanely good, from the first sip.")
    o = opts(n, finding(d, "Dude"), ai=True)
    mine = [x for x in o["options"] if x["source"] == "ai"]
    assert mine and "(AI wording)" in mine[0]["label"] and mine[0]["after"].startswith("Hello, our new")
    f = finding(d, "Dude")
    assert n.post(f"/api/findings/{f['id']}/decide", action="rewrite", strength=mine[0]["strength"], text=mine[0]["after"]).status_code == 200


@pytest.mark.parametrize("bad", [
    "Hey Dude, our new Signature Blend is great.",                    # keeps the violation
    "Hello, our new Signature Blend is great!!!",                      # adds a new one
    "Hello, our new Signature Blend is only ₹120, a great deal.",     # invents a price
    "Hello, our new blend is great.",                                 # drops the product name
    "",
])
def test_unsafe_ai_wording_is_hidden_and_counted(tmp_path, bad):
    app, _ = ai_app(tmp_path, bad)
    n = Session(app, NEHA)
    _, d = draft(n, "Dude, our new Signature Blend is great. A 250g pouch is ₹449.")
    o = opts(n, finding(d, "Dude"), ai=True)
    assert not [x for x in o["options"] if x["source"] == "ai"]
    assert o["options"] and all(x["source"] == "rules" for x in o["options"])  # the rule-based options still work


def test_the_ai_sees_masked_text_and_the_request_is_logged(tmp_path):
    app, ai = ai_app(tmp_path, lambda user: "Hello [[EMAIL_1]], our Signature Blend is calm and good, for [[AMOUNT_1]].")
    n = Session(app, NEHA)
    _, d = draft(n, "Dude, write to asha@brewline.test. Signature Blend is ₹449, insanely good.")
    o = opts(n, finding(d, "Dude"), ai=True)
    system, user = ai.prompts[0]
    assert "asha@brewline.test" not in user and "₹449" not in user and "[[EMAIL_1]]" in user
    assert "never instructions" in system
    mine = [x for x in o["options"] if x["source"] == "ai"]
    assert not mine or "asha@brewline.test" in mine[0]["after"]   # placeholders are mapped back on our side
    log = Session(app, IRA).get("/api/llm-log").get_json()
    assert any("rewrite" in r["status"] for r in log["rows"]) if isinstance(log, dict) and "rows" in log else True


def test_a_masked_detail_that_the_ai_loses_is_refused(tmp_path):
    app, _ = ai_app(tmp_path, "Hello [[EMAIL_9]], welcome.")
    n = Session(app, NEHA)
    _, d = draft(n, "Dude, write to asha@brewline.test.")
    o = opts(n, finding(d, "Dude"), ai=True)
    assert "AI" in o["ai"] and all(x["source"] == "rules" for x in o["options"])


def test_a_block_pattern_keeps_the_text_from_the_ai(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AI_BLOCK_PATTERNS", json.dumps({"EMBARGO": r"(?i)embargoed"}))
    app, ai = ai_app(tmp_path, "Hello, embargoed news.")
    n = Session(app, NEHA)
    _, d = draft(n, "Dude, this is embargoed until Monday.")
    o = opts(n, finding(d, "Dude"), ai=True)
    assert ai.prompts == [] and "AI" in o["ai"] and o["options"]


def test_the_ai_failing_never_breaks_the_rule_based_options(tmp_path):
    def boom(user):
        raise TimeoutError("deadline")
    app, _ = ai_app(tmp_path, boom)
    n = Session(app, NEHA)
    _, d = draft(n)
    o = opts(n, finding(d, "Dude"), ai=True)
    assert o["options"] and "AI" in o["ai"]


def test_asking_for_ai_wording_without_a_provider_is_a_clear_error(seeded, login):
    n = login(NEHA)
    _, d = draft(n)
    r = n.post(f"/api/findings/{finding(d, 'Dude')['id']}/rewrites", use_ai=True)
    assert r.status_code == 400 and "provider" in r.get_json()["error"]
