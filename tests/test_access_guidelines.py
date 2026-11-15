"""Guideline-level access: a finding must not reveal the text of a guideline its reader may not see."""
import json

import pytest

from conftest import ARJUN, IRA, NEHA, RAHUL

SECRET = "Never mention the competitor Rivalbrew in any copy."


@pytest.fixture()
def tiers(seeded, login):
    """One guideline per access level, each with one glossary term that triggers it."""
    ira = login(IRA)
    for level, code, term, text in (
        ("confidential", "Z-01", "Rivalbrew", SECRET),
        ("internal", "Y-01", "stalecoffee", "Internal note: never call our beans stalecoffee."),
        ("public", "X-01", "blandbean", "Public rule: do not call our beans blandbean."),
    ):
        assert ira.c.post("/api/kb/import", data={"kind": "guidelines", "title": f"{level} guideline", "access_level": level,
                                                "text": f"{code} | Rule: {text}"}).status_code == 200
        assert ira.c.post("/api/kb/import", data={"kind": "glossary", "text": json.dumps(
            [{"term": term, "preferred": "our coffee", "rule_code": code}])}).status_code == 200
    return ira


def _finding(session, body, code):
    cid = session.post("/api/content", title="t", body=body, images=[]).get_json()["id"]
    d = session.get(f"/api/content/{cid}").get_json()
    return cid, next(f for f in d["findings"] if f["source_id"] == code), d


BODY = "We beat Rivalbrew, stalecoffee and blandbean."


def test_agency_sees_public_rules_only(tiers, login):
    n = login(NEHA)
    _, public, _ = _finding(n, BODY, "X-01")
    assert public["restricted"] is False and "Public rule" in public["source_quote"] and public["suggested_fix"]
    for code in ("Y-01", "Z-01"):
        _, f, _ = _finding(n, BODY, code)
        assert f["restricted"] is True and f["suggested_fix"] is None and f["source_quote"].startswith("Restricted")


def test_internal_creator_sees_internal_but_not_confidential(tiers, login):
    r = login(RAHUL)
    assert _finding(r, BODY, "Y-01")[1]["restricted"] is False
    assert _finding(r, BODY, "Z-01")[1]["restricted"] is True


def test_manager_sees_everything(tiers, login):
    n = login(NEHA)
    cid, _, _ = _finding(n, BODY, "Z-01")
    f = next(x for x in login(ARJUN).get(f"/api/content/{cid}").get_json()["findings"] if x["source_id"] == "Z-01")
    assert f["restricted"] is False and SECRET in f["source_quote"]


def test_confidential_text_appears_nowhere_in_an_agency_response_or_record(tiers, login):
    n = login(NEHA)
    cid, _, _ = _finding(n, BODY, "Z-01")
    for url in (f"/api/content/{cid}", f"/api/content/{cid}/record", "/api/content"):
        text = n.get(url).get_data(as_text=True)
        assert SECRET not in text and "Never mention the competitor" not in text, url
    assert n.get("/api/kb").status_code == 403


def test_a_restricted_guideline_fix_cannot_be_accepted_by_the_agency_but_can_be_edited(tiers, login):
    n = login(NEHA)
    cid, f, _ = _finding(n, BODY, "Z-01")
    r = n.post(f"/api/findings/{f['id']}/decide", action="accept")
    assert r.status_code == 403
    assert n.post(f"/api/findings/{f['id']}/decide", action="edit", text="another brand").status_code == 200


def test_after_the_guideline_is_deleted_nobody_reads_its_findings_unredacted_by_mistake(tiers, login):
    n = login(NEHA)
    cid, f, _ = _finding(n, BODY, "X-01")
    ira = login(IRA)
    for g in ira.get("/api/kb").get_json()["glossary"]:
        if g["rule_code"] == "X-01":
            ira.c.delete(f"/api/kb/glossary/{g['id']}")
    assert ira.c.delete("/api/kb/rules/X-01").status_code == 200
    d = login(ARJUN).get(f"/api/content/{cid}").get_json()
    gone = [x for x in d["findings"] if x["source_id"] == "X-01"]
    assert all(x["restricted"] for x in gone)   # the source is gone, so it is withheld rather than shown


# ---- comments may only point at this content's own findings
def test_comment_finding_reference_is_validated(seeded, login):
    n = login(NEHA)
    a = n.post("/api/content", title="a", body="Hi Dude", images=[]).get_json()["id"]
    b = n.post("/api/content", title="b", body="Hi Dude", images=[]).get_json()["id"]
    fa = n.get(f"/api/content/{a}").get_json()["findings"][0]["id"]
    ok = n.post(f"/api/content/{a}/comments", body="own finding", finding_id=fa)
    assert ok.status_code == 201
    for bad in (fa, 999999, "1; DROP TABLE findings", True, 1.5):
        r = n.post(f"/api/content/{b}/comments", body="x", finding_id=bad)
        assert r.status_code == 400, (bad, r.status_code)
    assert n.post(f"/api/content/{b}/comments", body="no finding at all").status_code == 201
