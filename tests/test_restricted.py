"""Agency users and internal creators must not learn restricted facts through findings, fixes or records."""
from conftest import ARJUN, NEHA, RAHUL


def _draft(login, who, body="We launch on 20 December. Our 250g pouch is Rs. 399."):
    s = login(who)
    cid = s.post("/api/content", title="t", body=body, images=[]).get_json()["id"]
    return s, cid


def _date_finding(session, cid):
    return next(f for f in session.get(f"/api/content/{cid}").get_json()["findings"] if f["source_id"] == "F-02")


def test_agency_sees_that_a_restricted_fact_conflicts_but_not_what_it_says(seeded, login):
    s, cid = _draft(login, NEHA)
    f = _date_finding(s, cid)
    assert f["restricted"] is True and f["suggested_fix"] is None
    assert "15 December" not in f["issue"] and "15 December" not in f["source_quote"]
    whole = s.get(f"/api/content/{cid}").get_data(as_text=True)
    record = s.get(f"/api/content/{cid}/record").get_data(as_text=True)
    assert "15 December" not in whole and "2026-12-15" not in whole
    assert "15 December" not in record


def test_public_facts_still_come_with_a_fix(seeded, login):
    s, cid = _draft(login, NEHA)
    price = next(f for f in s.get(f"/api/content/{cid}").get_json()["findings"] if f["source_id"] == "F-01")
    assert price["restricted"] is False and price["suggested_fix"] == "Rs. 449"


def test_accepting_a_restricted_fix_is_refused_but_editing_is_allowed(seeded, login):
    s, cid = _draft(login, NEHA)
    f = _date_finding(s, cid)
    r = s.post(f"/api/findings/{f['id']}/decide", action="accept")
    assert r.status_code == 403 and "restricted" in r.get_json()["error"]
    assert s.post(f"/api/findings/{f['id']}/decide", action="edit", text="a date to be confirmed").status_code == 200


def test_an_internal_creator_does_not_see_confidential_facts_either(seeded, login):
    s, cid = _draft(login, RAHUL)
    f = _date_finding(s, cid)
    assert f["restricted"] and "15 December" not in s.get(f"/api/content/{cid}").get_data(as_text=True)


def test_managers_see_everything_and_can_apply_the_fix_for_the_author(seeded, login):
    s, cid = _draft(login, NEHA)
    arjun = login(ARJUN)
    f = _date_finding(arjun, cid)
    assert f["restricted"] is False and f["suggested_fix"] == "15 December" and "15 December" in f["issue"]
    assert arjun.post(f"/api/findings/{f['id']}/decide", action="accept").status_code == 200
    # the author now sees the corrected text she was not allowed to look up. That is the brand team's call to make.
    assert "15 December" in s.get(f"/api/content/{cid}").get_json()["body"]


def test_history_does_not_leak_a_restricted_fix(seeded, login):
    s, cid = _draft(login, NEHA)
    f = _date_finding(login(ARJUN), cid)
    login(ARJUN).post(f"/api/findings/{f['id']}/decide", action="accept")
    hist = [h for h in s.get(f"/api/content/{cid}").get_json()["history"] if h["source_id"] == "F-02"]
    assert hist and all(h["restricted"] and h["decision_text"] is None for h in hist)
