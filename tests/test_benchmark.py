"""Accuracy benchmark: scoring, runs, comparison, access control and validation."""
import json
from types import SimpleNamespace

from conftest import ARJUN, IRA, MEERA, NEHA

from brandguard import benchmark as bm


def F(source_id, span_text="", issue="issue text"):
    return SimpleNamespace(source_id=source_id, span_text=span_text, issue=issue)


# ------------------------------------------------------------------ the scoring maths
def test_perfect_match_scores_all_true_positives():
    s = bm.score_case([F("G-03", "cheap")], [{"source_id": "G-03", "text": "cheap"}])
    assert (s["tp"], s["fp"], s["fn"]) == (1, 0, 0) and s["missed"] == [] and s["extra"] == []


def test_a_missed_problem_is_a_false_negative_and_noise_is_a_false_positive():
    s = bm.score_case([F("G-02", "!!!")], [{"source_id": "G-03", "text": "cheap"}])
    assert (s["tp"], s["fp"], s["fn"]) == (0, 1, 1)
    assert s["missed"] == [{"source_id": "G-03", "text": "cheap"}] and s["extra"][0]["source_id"] == "G-02"


def test_flagged_text_may_contain_the_expected_text_case_insensitively():
    assert bm.score_case([F("G-03", "A Cheap")], [{"source_id": "G-03", "text": "cheap"}])["tp"] == 1
    assert bm.score_case([F("G-03", "cheaper")], [{"source_id": "G-03", "text": "dear"}])["tp"] == 0


def test_expected_without_text_matches_any_finding_from_that_source():
    assert bm.score_case([F("G-06", "hero.png")], [{"source_id": "G-06", "text": ""}])["tp"] == 1


def test_matching_is_one_to_one_so_a_finding_cannot_satisfy_two_expectations():
    two = [{"source_id": "G-02", "text": "!!!"}, {"source_id": "G-02", "text": "!!!"}]
    s = bm.score_case([F("G-02", "!!!")], two)
    assert (s["tp"], s["fn"], s["fp"]) == (1, 1, 0)
    assert len(s["matched"]) == 1                                  # per-rule counts come from this, so identical expectations stay correct
    assert bm.score_case([F("G-02", "!!!"), F("G-02", "!!!")], two)["tp"] == 2


def test_a_clean_case_with_no_findings_is_perfect():
    s = bm.score_case([], [])
    assert (s["tp"], s["fp"], s["fn"]) == (0, 0, 0)


# ------------------------------------------------------------------ API
def ira(login):
    return login(IRA)


def case(title="Wrong price", body="The 250g pouch is only ₹399 this week.", expected=None):
    return {"title": title, "body": body, "images": [], "expected": [{"source_id": "F-01", "text": "₹399"}] if expected is None else expected}


def test_only_admins_can_use_the_benchmark(seeded, login):
    for who in (ARJUN, MEERA, NEHA):
        s = login(who)
        assert s.get("/api/benchmark").status_code == 403
        assert s.post("/api/benchmark/run").status_code == 403
        assert s.post("/api/benchmark/seed").status_code == 403
        assert s.post("/api/benchmark/cases", cases=[case()]).status_code == 403
        assert s.c.delete("/api/benchmark/cases/1").status_code == 403
        assert s.get("/api/benchmark/runs/1").status_code == 403
        assert s.get("/api/benchmark/compare?before=1&after=1").status_code == 403


def test_running_with_no_cases_explains_what_to_do(seeded, login):
    r = ira(login).post("/api/benchmark/run")
    assert r.status_code == 400 and "no benchmark cases" in r.get_json()["error"].lower()


def test_run_scores_cases_against_the_current_knowledge_base(seeded, login):
    s = ira(login)
    assert s.post("/api/benchmark/cases", cases=[case(), case("Clean", "Hello friend.", [])]).get_json()["added"] == 2
    run = s.post("/api/benchmark/run", label="first").get_json()
    assert run["summary"] == {"cases": 2, "tp": 1, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0}
    assert run["per_rule"]["F-01"]["recall"] == 1.0 and run["label"] == "first"
    assert [c["fp"] + c["fn"] for c in run["per_case"]] == [0, 0]


def test_the_demo_set_loads_once_and_has_real_gaps(seeded, login):
    s = ira(login)
    n = s.post("/api/benchmark/seed").get_json()["added"]
    assert n >= 20 and s.post("/api/benchmark/seed").get_json()["added"] == 0      # loading twice adds nothing
    run = s.post("/api/benchmark/run").get_json()
    sm = run["summary"]
    assert sm["precision"] < 1 and sm["recall"] < 1                                # honest: the demo set exposes real misses
    assert sm["tp"] + sm["fn"] > 0 and sm["precision"] == round(sm["tp"] / (sm["tp"] + sm["fp"]), 4)
    assert sm["recall"] == round(sm["tp"] / (sm["tp"] + sm["fn"]), 4)


def test_improving_the_glossary_raises_recall_and_the_comparison_explains_why(seeded, login):
    s = ira(login)
    s.post("/api/benchmark/cases", cases=[case("Unlisted slang", "This blend is lit, honestly.", [{"source_id": "G-01", "text": "lit"}]), case()])
    before = s.post("/api/benchmark/run", label="before").get_json()
    assert before["summary"]["recall"] == 0.5 and before["per_case"][0]["fn"] == 1
    fd = {"kind": "glossary", "text": json.dumps([{"term": "lit", "preferred": "wonderful", "kind": "slang", "rule_code": "G-01"}])}
    assert s.c.post("/api/kb/import", data=fd).status_code == 200
    after = s.post("/api/benchmark/run", label="after").get_json()
    assert after["summary"]["recall"] == 1.0
    cmp = s.get(f"/api/benchmark/compare?before={before['id']}&after={after['id']}").get_json()
    assert cmp["summary"]["delta"]["recall"] == 0.5 and cmp["summary"]["delta"]["precision"] == 0.0
    assert cmp["changes"]["glossary"]["added"] == ["lit -> wonderful (slang, G-01)"] and cmp["changes"]["glossary"]["removed"] == []
    assert [c["title"] for c in cmp["cases_changed"]] == ["Unlisted slang"]
    assert cmp["rules"]["G-01"]["before"]["recall"] == 0.0 and cmp["rules"]["G-01"]["after"]["recall"] == 1.0


def test_comparison_shows_rule_version_and_check_setting_changes(seeded, login):
    s = ira(login)
    s.post("/api/benchmark/cases", cases=[case()])
    a = s.post("/api/benchmark/run").get_json()
    s.post("/api/kb/rules/G-03/draft", text="Never use cheap. Say affordable.")
    s.post("/api/kb/rules/G-03/publish")
    b = s.post("/api/benchmark/run").get_json()
    cmp = s.get(f"/api/benchmark/compare?before={a['id']}&after={b['id']}").get_json()
    assert cmp["changes"]["rule_versions"] == [{"code": "G-03", "from": 1, "to": 2}]


def test_run_history_is_listed_newest_first_and_runs_can_be_opened(seeded, login):
    s = ira(login)
    s.post("/api/benchmark/cases", cases=[case()])
    ids = [s.post("/api/benchmark/run", label=f"r{i}").get_json()["id"] for i in range(3)]
    runs = s.get("/api/benchmark").get_json()["runs"]
    assert [r["id"] for r in runs] == sorted(ids, reverse=True) and runs[0]["author"] == "Ira"
    assert s.get(f"/api/benchmark/runs/{ids[0]}").get_json()["snapshot"]["rules"]["G-03"] == 1
    assert s.get("/api/benchmark/runs/999").status_code == 404
    assert s.get("/api/benchmark/compare?before=1").status_code == 400
    assert s.get(f"/api/benchmark/compare?before={ids[0]}&after=999").status_code == 404


def test_case_validation(seeded, login):
    s = ira(login)
    bad = [([], "list of cases"), ("x", "list of cases"), ([5], "must be an object"), ([case(title=" ")], "title cannot be empty"),
           ([case(body="")], "text cannot be empty"), ([case(body="x" * 20001)], "too long"),
           ([case(expected=[{"source_id": "Z-99", "text": "x"}])], "not a rule or fact"), ([case(expected=["G-01"])], "must be an object"),
           ([case(expected=[{"source_id": "F-01"}] * 51)], "up to 50"), ([{**case(), "images": "x"}], "images")]
    for cases, msg in bad:
        r = s.post("/api/benchmark/cases", cases=cases)
        assert r.status_code == 400 and msg in r.get_json()["error"], (cases, r.get_json())
    assert "Case 2" in s.post("/api/benchmark/cases", cases=[case(), case(title="")]).get_json()["error"]
    assert s.get("/api/benchmark").get_json()["cases"] == []                       # a bad batch saves nothing


def test_case_limit_and_delete(seeded, login):
    s = ira(login)
    s.post("/api/benchmark/cases", cases=[case()])
    cid = s.get("/api/benchmark").get_json()["cases"][0]["id"]
    assert s.c.delete(f"/api/benchmark/cases/{cid}").status_code == 200
    assert s.c.delete(f"/api/benchmark/cases/{cid}").status_code == 404
    assert s.post("/api/benchmark/cases", cases=[case()] * 201).status_code == 400


def test_runs_never_use_the_ai_judge(seeded, login, monkeypatch):
    from brandguard import engine
    seen = []
    real = engine.review
    monkeypatch.setattr(engine, "review", lambda kb, body, images, judge=None, inherited=None: (seen.append(judge), real(kb, body, images, judge=judge, inherited=inherited))[1])
    s = ira(login)
    s.post("/api/benchmark/cases", cases=[case(), case("Clean", "Hello friend.", [])])
    assert s.post("/api/benchmark/run").status_code == 200
    assert seen == [None, None]                                    # every case reviewed with the rule checks only, so no text leaves the server


def test_benchmark_actions_are_audited(seeded, login, app):
    from brandguard import db as dbm
    s = ira(login)
    s.post("/api/benchmark/cases", cases=[case()])
    s.post("/api/benchmark/run")
    c = dbm.connect(app.config["DB_PATH"])
    actions = {r["action"] for r in c.execute("SELECT action FROM audit")}
    assert {"benchmark_cases_added", "benchmark_run"} <= actions
