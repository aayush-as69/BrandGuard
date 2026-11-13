"""Guideline version history: draft, publish, compare, rollback. Reviews use only the published text."""
from conftest import ARJUN, IRA, MEERA, NEHA

CODE = "G-03"   # preferred terminology: "never cheap"


def versions(s, code=CODE):
    return s.get(f"/api/kb/rules/{code}/versions").get_json()


def live_text(s, code=CODE):
    kb = s.get("/api/kb").get_json()
    return next(r["text"] for g in kb["guidelines"] for r in g["rules"] if r["code"] == code)


def test_first_look_creates_version_one_as_published(seeded, login):
    ira = login(IRA)
    d = versions(ira)
    assert [v["version"] for v in d["versions"]] == [1]
    assert d["published"]["version"] == 1 and d["published"]["text"] == live_text(ira) and d["draft"] is None


def test_only_admins_can_see_or_change_versions(seeded, login):
    for who in (ARJUN, MEERA, NEHA):
        s = login(who)
        assert s.get(f"/api/kb/rules/{CODE}/versions").status_code == 403
        assert s.post(f"/api/kb/rules/{CODE}/draft", text="x").status_code == 403
        assert s.post(f"/api/kb/rules/{CODE}/publish").status_code == 403
        assert s.post(f"/api/kb/rules/{CODE}/rollback", version=1).status_code == 403
        assert s.c.delete(f"/api/kb/rules/{CODE}/draft").status_code == 403
        assert s.get(f"/api/kb/rules/{CODE}/compare?from=1&to=1").status_code == 403


def test_a_draft_changes_nothing_a_review_uses_until_it_is_published(seeded, login):
    ira, neha = login(IRA), login(NEHA)
    before = live_text(ira)
    assert ira.post(f"/api/kb/rules/{CODE}/draft", text="Describe our pricing as keenly priced.", note="Softer wording").status_code == 200
    assert live_text(ira) == before                                       # the live rule is untouched
    d = versions(ira)
    assert d["draft"]["version"] == 2 and d["draft"]["text"].startswith("Describe our pricing as keenly") and d["published"]["version"] == 1
    cid = neha.post("/api/content", title="t", body="Hi, our cheap blend.", images=[]).get_json()["id"]
    f = next(x for x in neha.get(f"/api/content/{cid}").get_json()["findings"] if x["source_id"] == CODE)
    assert f["source_quote"] == before                                    # evidence still quotes the published text


def test_saving_again_replaces_the_one_draft(seeded, login):
    ira = login(IRA)
    ira.post(f"/api/kb/rules/{CODE}/draft", text="First idea")
    ira.post(f"/api/kb/rules/{CODE}/draft", text="Second idea")
    d = versions(ira)
    assert [v["status"] for v in d["versions"]] == ["draft", "published"] and d["draft"]["text"] == "Second idea"


def test_publish_makes_it_live_and_archives_the_previous_version(seeded, login):
    ira, neha = login(IRA), login(NEHA)
    old = live_text(ira)
    ira.post(f"/api/kb/rules/{CODE}/draft", text="Never use the word cheap. Say affordable or great value.")
    assert ira.post(f"/api/kb/rules/{CODE}/publish").get_json()["version"] == 2
    assert live_text(ira) == "Never use the word cheap. Say affordable or great value."
    d = versions(ira)
    assert [(v["version"], v["status"]) for v in d["versions"]] == [(2, "published"), (1, "archived")]
    assert d["versions"][1]["text"] == old                                  # history keeps the earlier wording
    cid = neha.post("/api/content", title="t", body="Hi, our cheap blend.", images=[]).get_json()["id"]
    f = next(x for x in neha.get(f"/api/content/{cid}").get_json()["findings"] if x["source_id"] == CODE)
    assert f["source_quote"] == "Never use the word cheap. Say affordable or great value."   # the next review cites the new text


def test_publish_needs_a_real_change(seeded, login):
    ira = login(IRA)
    assert "no draft" in ira.post(f"/api/kb/rules/{CODE}/publish").get_json()["error"].lower()
    ira.post(f"/api/kb/rules/{CODE}/draft", text=live_text(ira))
    assert "identical" in ira.post(f"/api/kb/rules/{CODE}/publish").get_json()["error"]


def test_rollback_publishes_a_new_version_and_loses_nothing(seeded, login):
    ira = login(IRA)
    original = live_text(ira)
    ira.post(f"/api/kb/rules/{CODE}/draft", text="Changed once")
    ira.post(f"/api/kb/rules/{CODE}/publish")
    ira.post(f"/api/kb/rules/{CODE}/draft", text="Changed twice")
    ira.post(f"/api/kb/rules/{CODE}/publish")
    assert ira.post(f"/api/kb/rules/{CODE}/rollback", version=1).get_json()["version"] == 4
    assert live_text(ira) == original
    d = versions(ira)
    assert [(v["version"], v["status"]) for v in d["versions"]] == [(4, "published"), (3, "archived"), (2, "archived"), (1, "archived")]
    assert d["published"]["note"] == "Rolled back to version 1" and d["versions"][1]["text"] == "Changed twice"
    assert "already the published" in ira.post(f"/api/kb/rules/{CODE}/rollback", version=4).get_json()["error"]
    assert ira.post(f"/api/kb/rules/{CODE}/rollback", version=99).status_code == 404
    assert ira.post(f"/api/kb/rules/{CODE}/rollback", version="x").status_code == 400


def test_compare_shows_removed_and_added_words(seeded, login):
    ira = login(IRA)
    ira.post(f"/api/kb/rules/{CODE}/draft", text="Describe our pricing as affordable or great value, never expensive.")
    ira.post(f"/api/kb/rules/{CODE}/publish")
    r = ira.get(f"/api/kb/rules/{CODE}/compare?from=1&to=2").get_json()
    ops = {(s["op"], s["text"].strip()) for s in r["segments"]}
    assert ("removed", "cheap.") in ops and ("added", "expensive.") in ops and not r["identical"]
    assert "".join(s["text"] for s in r["segments"] if s["op"] != "added") == versions(ira)["versions"][1]["text"]   # nothing is lost from the old side
    assert ira.get(f"/api/kb/rules/{CODE}/compare?from=1&to=1").get_json()["identical"]
    assert ira.get(f"/api/kb/rules/{CODE}/compare?from=1").status_code == 400
    assert ira.get(f"/api/kb/rules/{CODE}/compare?from=1&to=9").status_code == 404


def test_discard_draft(seeded, login):
    ira = login(IRA)
    assert ira.c.delete(f"/api/kb/rules/{CODE}/draft").status_code == 404
    ira.post(f"/api/kb/rules/{CODE}/draft", text="Maybe")
    assert ira.c.delete(f"/api/kb/rules/{CODE}/draft").status_code == 200 and versions(ira)["draft"] is None


def test_validation_and_unknown_rules(seeded, login):
    ira = login(IRA)
    assert ira.post(f"/api/kb/rules/{CODE}/draft", text="   ").status_code == 400
    assert ira.post(f"/api/kb/rules/{CODE}/draft").status_code == 400
    assert ira.post(f"/api/kb/rules/{CODE}/draft", text="x" * 4001).status_code == 400
    assert ira.post(f"/api/kb/rules/{CODE}/draft", text="ok", title="t" * 201).status_code == 400
    assert ira.post(f"/api/kb/rules/{CODE}/draft", text=5).status_code == 400
    assert ira.get("/api/kb/rules/NOPE/versions").status_code == 404
    assert ira.post("/api/kb/rules/NOPE/draft", text="x").status_code == 404


def test_a_direct_edit_is_recorded_so_the_history_stays_complete(seeded, login):
    ira = login(IRA)
    original = live_text(ira)
    assert ira.c.patch(f"/api/kb/rules/{CODE}", json={"text": "Edited in place."}).status_code == 200
    d = versions(ira)
    assert [(v["version"], v["status"]) for v in d["versions"]] == [(2, "published"), (1, "archived")]
    assert d["versions"][1]["text"] == original and d["published"]["note"] == "Edited directly in the knowledge base"


def test_changes_made_outside_versions_are_noticed_not_lost(seeded, login, app):
    ira = login(IRA)
    versions(ira)                                                          # baseline v1
    ira.post("/api/kb/seed")                                              # reloading the demo set rewrites the rules table
    ira.c.patch(f"/api/kb/rules/{CODE}", json={"text": "X"})
    ira.c.patch(f"/api/kb/rules/{CODE}", json={"text": "Y"})
    d = versions(ira)
    assert d["published"]["text"] == "Y" and sum(v["status"] == "published" for v in d["versions"]) == 1


def test_deleting_a_rule_removes_its_history_and_it_can_be_recreated(seeded, login, app):
    from brandguard import db as dbm
    c = dbm.connect(app.config["DB_PATH"])
    gid = c.execute("SELECT id FROM guidelines LIMIT 1").fetchone()[0]
    c.execute("INSERT INTO rules(guideline_id, code, title, text) VALUES (?,?,?,?)", (gid, "X-01", "Scratch rule", "Temporary."))
    c.commit()                                                              # a rule nothing else refers to, so it may be deleted
    ira = login(IRA)
    versions(ira, "X-01")
    ira.post("/api/kb/rules/X-01/draft", text="a draft")
    assert ira.c.delete("/api/kb/rules/X-01").status_code == 200
    assert ira.get("/api/kb/rules/X-01/versions").status_code == 404
    assert c.execute("SELECT COUNT(*) FROM rule_versions WHERE rule_code='X-01'").fetchone()[0] == 0
    c.execute("INSERT INTO rules(guideline_id, code, title, text) VALUES (?,?,?,?)", (gid, "X-01", "Scratch rule again", "New."))
    c.commit()
    assert [v["version"] for v in versions(ira, "X-01")["versions"]] == [1]    # a recreated rule starts a fresh history


def test_every_version_action_is_audited(seeded, login, app):
    ira = login(IRA)
    ira.post(f"/api/kb/rules/{CODE}/draft", text="Draft one")
    ira.post(f"/api/kb/rules/{CODE}/publish")
    ira.post(f"/api/kb/rules/{CODE}/rollback", version=1)
    from brandguard import db as dbm
    c = dbm.connect(app.config["DB_PATH"])
    actions = [r["action"] for r in c.execute("SELECT action FROM audit")]
    assert {"rule_draft_saved", "rule_published", "rule_rolled_back"} <= set(actions)


def test_one_published_version_per_rule_is_enforced_by_the_database(seeded, login, app):
    import sqlite3

    import pytest
    from brandguard import db as dbm
    login(IRA)
    versions(login(IRA))
    c = dbm.connect(app.config["DB_PATH"])
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO rule_versions(rule_code, version, title, text, status, created_at) VALUES (?,?,?,?,?,?)",
                  (CODE, 50, "t", "x", "published", "now"))
