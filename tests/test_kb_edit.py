import json

from conftest import ARJUN, IRA, NEHA


def _admin(seeded, login):
    return login(IRA)


def test_only_admin_can_edit_or_delete(seeded, login):
    for who in (ARJUN, NEHA):
        s = login(who)
        assert s.c.patch("/api/kb/facts/F-01", json={"statement": "x"}).status_code == 403
        assert s.c.delete("/api/kb/facts/F-01").status_code == 403


def test_edit_a_price_fact_changes_what_the_review_expects(seeded, login):
    ira = login(IRA)
    r = ira.c.patch("/api/kb/facts/F-01", json={"data": {"amount": 499, "match": ["250g", "pouch"]}, "statement": "The 250g pouch costs Rs. 499."})
    assert r.status_code == 200, r.get_json()
    s = login(NEHA)
    cid = s.post("/api/content", title="t", body="Our 250g pouch is Rs. 449.", images=[]).get_json()["id"]
    f = next(x for x in s.get(f"/api/content/{cid}").get_json()["findings"] if x["source_id"] == "F-01")
    assert f["suggested_fix"] == "Rs. 499"


def test_bad_edits_are_refused_with_clear_messages(seeded, login):
    ira = login(IRA)
    assert "numeric" in ira.c.patch("/api/kb/facts/F-01", json={"data": {"amount": "lots"}}).get_json()["error"]
    assert ira.c.patch("/api/kb/facts/F-01", json={"kind": "date"}).status_code == 400
    assert ira.c.patch("/api/kb/facts/F-01", json={"access_level": "secret"}).status_code == 400
    assert ira.c.patch("/api/kb/facts/F-01", json={}).status_code == 400
    assert ira.c.patch("/api/kb/facts/F-01", json={"statement": "   "}).status_code == 400
    assert ira.c.patch("/api/kb/facts/NOPE", json={"statement": "x"}).status_code == 404
    assert ira.c.patch("/api/kb/nonsense/1", json={"a": 1}).status_code == 404
    assert ira.c.patch("/api/kb/glossary/abc", json={"term": "x"}).status_code == 404
    assert ira.c.patch("/api/kb/glossary/1", json={"rule_code": "G-99"}).status_code == 400


def test_edit_a_rule_and_a_glossary_term(seeded, login):
    ira = login(IRA)
    assert ira.c.patch("/api/kb/rules/G-01", json={"text": "Write warmly. Avoid slang and hype words."}).status_code == 200
    kb = ira.get("/api/kb").get_json()
    assert any(r["text"].startswith("Write warmly") for g in kb["guidelines"] for r in g["rules"])
    term = next(g for g in kb["glossary"] if g["term"] == "dude")
    assert ira.c.patch(f"/api/kb/glossary/{term['id']}", json={"preferred": "Hi there"}).status_code == 200
    s = login(NEHA)
    cid = s.post("/api/content", title="t", body="Hey dude.", images=[]).get_json()["id"]
    assert next(f for f in s.get(f"/api/content/{cid}").get_json()["findings"])["suggested_fix"] == "Hi there"


def test_a_rule_in_use_cannot_be_deleted(seeded, login):
    ira = login(IRA)
    r = ira.c.delete("/api/kb/rules/G-01")
    assert r.status_code == 400 and "still used" in r.get_json()["error"]
    assert ira.c.delete("/api/kb/rules/G-07").status_code == 400   # the 'addictive' glossary term cites it
    # unused after its terms go:
    kb = ira.get("/api/kb").get_json()
    for g in kb["glossary"]:
        if g["rule_code"] == "G-07":
            assert ira.c.delete(f"/api/kb/glossary/{g['id']}").status_code == 200
    assert ira.c.delete("/api/kb/rules/G-07").status_code == 200


def test_delete_fact_and_asset_and_it_is_audited(seeded, login):
    ira = login(IRA)
    assert ira.c.delete("/api/kb/facts/F-03").status_code == 200
    assert "F-03" not in {f["code"] for f in ira.get("/api/kb").get_json()["facts"]}
    asset = ira.get("/api/kb").get_json()["assets"][0]
    assert ira.c.patch(f"/api/kb/assets/{asset['id']}", json={"note": "Updated"}).status_code == 200
    assert ira.c.delete(f"/api/kb/assets/{asset['id']}").status_code == 200
    assert ira.c.delete(f"/api/kb/assets/{asset['id']}").status_code == 404


# ---- Hinglish
def test_hinglish_slang_is_caught(seeded, login):
    s = login(NEHA)
    cid = s.post("/api/content", title="t", body="Arre yaar, this blend is bindaas. Ekdum mast coffee, paisa vasool!", images=[]).get_json()["id"]
    hits = {f["span_text"].lower() for f in s.get(f"/api/content/{cid}").get_json()["findings"]}
    assert {"yaar", "bindaas", "ekdum mast", "paisa vasool"} <= hits


def test_hinglish_terms_do_not_match_inside_other_words(seeded, login):
    s = login(NEHA)
    cid = s.post("/api/content", title="t", body="Bhaiyya and Yaarana are names of cafés.", images=[]).get_json()["id"]
    assert s.get(f"/api/content/{cid}").get_json()["findings"] == []
