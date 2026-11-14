"""The benchmark, the learning loop and their API."""
import json

import pytest

from brandguard import benchmark as bm, db as dbm, engine, kb as kbm, learning
from conftest import ARJUN, IRA, MEERA, NEHA, RAHUL, ROOT


@pytest.fixture()
def conn(tmp_path):
    c = dbm.connect(str(tmp_path / "q.db"))
    dbm.init(c)
    kbm.seed_demo(c, ROOT / "seed")
    return c


def test_every_label_points_at_a_real_rule_or_fact(conn):
    kb = engine.load_kb(conn)
    known = set(kb.rules) | {f["code"] for f in kb.facts}
    for case in bm.load_cases():
        for e in case["expected"]:
            assert e["source_id"] in known, (case["id"], e)
            assert e["text"] in case["body"] or e["text"] in json.dumps(case.get("images", [])), (case["id"], e)


def test_benchmark_scores_the_engine(conn):
    r = bm.run(conn)
    assert r["drafts"] >= 30 and r["labels"] >= 40
    o = r["overall"]
    assert o["tp"] + o["fn"] == sum(1 for c in bm.load_cases() for e in c["expected"] if not e.get("ai"))
    assert 0.8 <= o["precision"] <= 1 and 0.8 <= o["recall"] <= 1
    g1 = next(x for x in r["rules"] if x["code"] == "G-01")
    assert g1["tp"] >= 9 and g1["fp"] == 0
    # honest labels mean honest weaknesses are visible
    assert any(n["kind"] == "false_alarm" and n["code"] == "G-02" and n["text"] == "ISO" for n in r["notes"])
    assert any(n["kind"] == "missed" and n["code"] == "F-03" for n in r["notes"])
    assert r["ai"] is None


def test_a_rule_with_many_false_alarms_is_flagged_for_review(conn):
    r = bm.run(conn)
    assert next(x for x in r["rules"] if x["code"] == "G-02")["review"] is True
    assert next(x for x in r["rules"] if x["code"] == "G-01")["review"] is False


def test_matching_pairs_each_label_once():
    from brandguard.models import Finding
    f = lambda t: Finding(category="tone", issue="xxx", span_text=t, span_start=0, span_end=len(t), source_type="guideline",
                          source_id="G-02", source_quote="xxx", severity="low", confidence="high")
    pairs, missed, spare = bm._match([{"source_id": "G-02", "text": "!"}, {"source_id": "G-02", "text": "!"}], [f("!")])
    assert len(pairs) == 1 and len(missed) == 1 and not spare


def test_ai_judge_is_measured_on_its_own(conn):
    reply = json.dumps([{"rule_code": "G-07", "quote": "Never describe coffee as addictive or imply medical benefits.",
                         "span": "cures headaches", "issue": "Medical claim.", "severity": "high", "confidence": "medium"}])
    judge = __import__("brandguard.llm", fromlist=["x"]).make_judge(conn, call=lambda s, u, m: reply)
    r = bm.run(conn, judge=judge)
    assert r["ai"]["drafts"] <= bm.AI_DRAFTS and r["ai"]["tp"] >= 1
    assert r["overall"]["tp"] == bm.run(conn)["overall"]["tp"]  # rule results do not change when the AI is added


# ------------------------------------------------------------------ API
def test_quality_page_is_for_staff_only(seeded, login):
    assert login(IRA).get("/api/quality").status_code == 200
    assert login(ARJUN).get("/api/quality").status_code == 200
    assert login(NEHA).get("/api/quality").status_code == 403
    assert login(RAHUL).post("/api/benchmark/run", use_ai=False).status_code == 403
    assert login(ARJUN).post("/api/benchmark/run", use_ai=False).status_code == 403


def test_first_visit_runs_the_benchmark_and_the_admin_can_rerun(seeded, login):
    d = login(IRA).get("/api/quality").get_json()
    assert d["benchmark"]["result"]["overall"]["precision"] and len(d["history"]) == 1
    d2 = login(IRA).post("/api/benchmark/run", use_ai=False).get_json()
    assert len(d2["history"]) == 2 and d2["ai_available"] is False
    assert login(IRA).post("/api/benchmark/run", use_ai=True).status_code == 400  # no provider configured


def test_apply_a_benchmark_suggestion_and_undo_it(seeded, login):
    admin = login(IRA)
    d = admin.get("/api/quality").get_json()
    s = next(x for x in d["suggestions"] if x["id"] == "review:G-02")
    assert s["apply"]["kind"] == "allow_caps" and set(s["apply"]["tokens"]) == {"BIS", "ISO"}
    before = d["benchmark"]["result"]["overall"]["precision"]
    out = admin.post("/api/learning/apply", suggestion="review:G-02").get_json()
    assert out["compare"]["precision_after"] > before and out["compare"]["recall_after"] == out["compare"]["recall_before"]
    assert all(x["id"] != "review:G-02" for x in out["suggestions"])
    assert out["changes"][0]["summary"].startswith("Allowed") and out["changes"][0]["compare"]["precision_change"] > 0
    # the change is real: new content with ISO is no longer flagged
    cid = login(NEHA).post("/api/content", title="t", body="Our estates are ISO certified.", images=[]).get_json()["id"]
    assert login(NEHA).get(f"/api/content/{cid}").get_json()["findings"] == []
    undo = admin.post("/api/learning/undo", change_id=out["change_id"]).get_json()
    assert undo["compare"]["precision_change"] < 0
    assert admin.post("/api/learning/undo", change_id=out["change_id"]).status_code == 400  # already undone
    assert any(x["id"] == "review:G-02" for x in undo["suggestions"])


def _dismiss_twice(login, body, reason="fine here"):
    for _ in range(2):
        n, boss = login(NEHA), login(ARJUN)  # a manager may dismiss fact and claim findings
        cid = n.post("/api/content", title="t", body=body, images=[]).get_json()["id"]
        fid = n.get(f"/api/content/{cid}").get_json()["findings"][0]["id"]
        assert boss.post(f"/api/findings/{fid}/decide", action="dismiss", reason=reason).status_code == 200


def test_a_mostly_dismissed_term_is_offered_for_retirement(seeded, login, app):
    _dismiss_twice(login, "Hello yaar, welcome.")
    admin = login(IRA)
    d = admin.get("/api/quality").get_json()
    s = next(x for x in d["suggestions"] if x["type"] == "narrow" and "yaar" in x["title"])
    assert s["evidence"]["dismissed"] == 2 and s["apply"]["kind"] == "retire_term"
    out = admin.post("/api/learning/apply", suggestion=s["id"]).get_json()
    assert "yaar" in out["summary"]
    cid = login(NEHA).post("/api/content", title="t", body="Hello yaar.", images=[]).get_json()["id"]
    assert login(NEHA).get(f"/api/content/{cid}").get_json()["findings"] == []
    admin.post("/api/learning/undo", change_id=out["change_id"])
    cid = login(NEHA).post("/api/content", title="t", body="Hello yaar.", images=[]).get_json()["id"]
    assert login(NEHA).get(f"/api/content/{cid}").get_json()["findings"]


def test_a_mostly_dismissed_rule_gets_advice_only(seeded, login):
    _dismiss_twice(login, "Our cafe is No. 1 on MG Road.")  # a G-04 finding with no mechanical origin
    d = login(IRA).get("/api/quality").get_json()
    s = next(x for x in d["suggestions"] if x["id"] == "narrow:rule:G-04")
    assert s["apply"] is None
    assert login(IRA).post("/api/learning/apply", suggestion=s["id"]).status_code == 400


def test_a_repeated_mistake_gets_an_example(seeded, login):
    for _ in range(3):
        n = login(NEHA)
        cid = n.post("/api/content", title="t", body="Hi Dude, welcome.", images=[]).get_json()["id"]
        fid = n.get(f"/api/content/{cid}").get_json()["findings"][0]["id"]
        n.post(f"/api/findings/{fid}/decide", action="accept")
    admin = login(IRA)
    s = next(x for x in admin.get("/api/quality").get_json()["suggestions"] if x["id"] == "example:G-01")
    assert s["apply"]["note"] == 'Example: write "Hello" instead of "Dude".'
    out = admin.post("/api/learning/apply", suggestion="example:G-01", note='Example: write "Hello" instead of "Dude".').get_json()
    rule = next(r for g in login(IRA).get("/api/kb").get_json()["guidelines"] for r in g["rules"] if r["code"] == "G-01")
    assert rule["text"].endswith('instead of "Dude".') and rule["text"].startswith("Voice:") is False
    assert out["compare"]["changed_rules"] == []   # an example does not change what the engine flags
    assert all(x["id"] != "example:G-01" for x in out["suggestions"])
    admin.post("/api/learning/undo", change_id=out["change_id"])
    rule = next(r for g in login(IRA).get("/api/kb").get_json()["guidelines"] for r in g["rules"] if r["code"] == "G-01")
    assert "Example:" not in rule["text"]


def test_an_example_never_copies_private_details_into_a_guideline(seeded, login):
    for _ in range(3):
        n = login(NEHA)
        cid = n.post("/api/content", title="t", body="Mail asha@brewline.test, yaar.", images=[]).get_json()["id"]
        d = n.get(f"/api/content/{cid}").get_json()
        fid = next(f["id"] for f in d["findings"] if f["span_text"] == "yaar")
        n.post(f"/api/findings/{fid}/decide", action="edit", text="asha@brewline.test")
    s = [x for x in login(IRA).get("/api/quality").get_json()["suggestions"] if x["type"] == "example"]
    assert all("asha@" not in json.dumps(x) for x in s)


def test_suggestions_never_name_a_person(seeded, login):
    _dismiss_twice(login, "Hello yaar.")
    text = json.dumps(login(ARJUN).get("/api/quality").get_json())
    for name in ("Neha", "Rahul", "Arjun", "Meera", "Ira"):
        assert name not in text


def test_changes_need_an_admin(seeded, login):
    _dismiss_twice(login, "Hello yaar.")
    sid = next(x["id"] for x in login(IRA).get("/api/quality").get_json()["suggestions"] if x["type"] == "narrow")
    assert login(ARJUN).post("/api/learning/apply", suggestion=sid).status_code == 403
    assert login(MEERA).post("/api/learning/undo", change_id=1).status_code == 403


def test_ai_benchmark_runs_with_an_injected_provider(tmp_path):
    from brandguard.app import create_app
    app = create_app(str(tmp_path / "a.db"), llm_call=lambda s, u, m: "[]")
    from conftest import Session
    admin = Session(app, IRA)
    admin.post("/api/kb/seed")
    d = admin.post("/api/benchmark/run", use_ai=True).get_json()
    assert d["ai_available"] and d["benchmark"]["result"]["ai"]["drafts"] > 0 and d["pending"] is False
