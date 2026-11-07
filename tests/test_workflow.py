"""API and workflow tests: roles, human control, versions, approval, privacy."""
from conftest import ARJUN, IRA, MEERA, NEHA, RAHUL


def create_demo(session, demo, title=None):
    r = session.post("/api/content", title=title or demo["title"], body=demo["body"], images=demo["images"])
    assert r.status_code == 201, r.get_json()
    return r.get_json()["id"]


def detail(session, cid):
    return session.get(f"/api/content/{cid}").get_json()


def finding(d, source_id, span=None):
    return next(f for f in d["findings"] if f["source_id"] == source_id and (span is None or f["span_text"] == span))


def test_login_required(app):
    assert app.test_client().get("/api/content").status_code == 401


def test_creating_content_runs_review_with_cited_findings(seeded, login, demo):
    neha = login(NEHA)
    cid = create_demo(neha, demo)
    d = detail(neha, cid)
    assert len(d["findings"]) >= 10 and d["content"]["status"] == "draft"
    assert all(f["source_quote"] and f["source_id"] for f in d["findings"])
    assert any(c["status"] == "supported" for c in d["claims"])
    assert d["permissions"]["can_submit"] and not d["permissions"]["can_approve"]


def test_accept_applies_fix_only_on_human_click_and_keeps_history(seeded, login, demo):
    neha = login(NEHA)
    cid = create_demo(neha, demo)
    d = detail(neha, cid)
    assert "₹399" in d["body"]  # nothing was changed automatically
    f = finding(d, "F-01")
    r = neha.post(f"/api/findings/{f['id']}/decide", action="accept")
    assert r.status_code == 200 and r.get_json()["new_version"] == 2
    d2 = detail(neha, cid)
    assert "₹449" in d2["body"] and "₹399" not in d2["body"]
    assert d2["content"]["current_version"] == 2
    assert not [x for x in d2["findings"] if x["source_id"] == "F-01"]
    assert any(h["id"] == f["id"] and h["decision"] == "accepted" for h in d2["history"])
    assert [v["version"] for v in d2["versions"]] == [2, 1]


def test_edit_uses_the_persons_own_text(seeded, login, demo):
    neha = login(NEHA)
    cid = create_demo(neha, demo)
    f = finding(detail(neha, cid), "G-04")
    assert neha.post(f"/api/findings/{f['id']}/decide", action="edit", text="a coffee we are proud of").status_code == 200
    assert "a coffee we are proud of is finally here" in detail(neha, cid)["body"]


def test_alt_text_fix_requires_a_person_to_write_it(seeded, login, demo):
    neha = login(NEHA)
    cid = create_demo(neha, demo)
    f = next(x for x in detail(neha, cid)["findings"] if x["target"].startswith("image.alt"))
    assert f["suggested_fix"] is None
    assert neha.post(f"/api/findings/{f['id']}/decide", action="accept").status_code == 400
    ok = neha.post(f"/api/findings/{f['id']}/decide", action="edit", text="Copper pouch of Signature Blend on a wooden table")
    assert ok.status_code == 200
    assert detail(neha, cid)["images"][0]["alt"].startswith("Copper pouch")


def test_dismiss_needs_reason_and_risky_dismissals_need_a_manager(seeded, login, demo):
    neha = login(NEHA)
    cid = create_demo(neha, demo)
    d = detail(neha, cid)
    claim = finding(d, "G-04")
    tone = finding(d, "G-01", "Dude")
    assert neha.post(f"/api/findings/{tone['id']}/decide", action="dismiss").status_code == 400
    assert neha.post(f"/api/findings/{tone['id']}/decide", action="dismiss", reason="Casual campaign").status_code == 200
    r = neha.post(f"/api/findings/{claim['id']}/decide", action="dismiss", reason="trust me")
    assert r.status_code == 403
    assert "manager or reviewer" in r.get_json()["error"]


def test_dismissals_carry_over_to_new_versions(seeded, login, demo):
    neha = login(NEHA)
    cid = create_demo(neha, demo)
    tone = finding(detail(neha, cid), "G-01", "Dude")
    neha.post(f"/api/findings/{tone['id']}/decide", action="dismiss", reason="Casual campaign")
    price = finding(detail(neha, cid), "F-01")
    neha.post(f"/api/findings/{price['id']}/decide", action="accept")  # creates v2 and re-reviews
    again = finding(detail(neha, cid), "G-01", "Dude")
    assert again["decision"] == "dismissed" and "Casual campaign" in again["decision_reason"]


def test_full_approval_flow(seeded, login, demo):
    neha, arjun, meera = login(NEHA), login(ARJUN), login(MEERA)
    cid = create_demo(neha, demo)
    # clear everything by accepting suggestions where they exist; edit where they do not
    for _ in range(30):
        open_ = [f for f in detail(neha, cid)["findings"] if f["decision"] == "open"]
        if not open_:
            break
        f = open_[0]
        if f["suggested_fix"]:
            r = neha.post(f"/api/findings/{f['id']}/decide", action="accept")
        else:
            r = neha.post(f"/api/findings/{f['id']}/decide", action="edit", text="Copper pouch of Signature Blend")
        assert r.status_code == 200, r.get_json()
    d = detail(neha, cid)
    assert d["findings"] == []
    assert "₹449" in d["body"] and "15 December 2026" in d["body"] and "medium-dark roast" in d["body"]

    assert neha.post(f"/api/content/{cid}/approve").status_code == 403  # author cannot approve
    assert neha.post(f"/api/content/{cid}/submit").status_code == 200
    assert detail(neha, cid)["content"]["status"] == "in_review"
    assert neha.post(f"/api/content/{cid}/submit").status_code == 403  # no longer editable by author
    bad = arjun.post(f"/api/content/{cid}/request-changes", note="")
    assert bad.status_code == 400
    assert arjun.post(f"/api/content/{cid}/request-changes", note="Add a second image").status_code == 200
    assert detail(neha, cid)["content"]["status"] == "changes_requested"
    assert any("Changes requested" in c["body"] for c in detail(neha, cid)["comments"])
    neha.post(f"/api/content/{cid}/submit")
    assert meera.post(f"/api/content/{cid}/approve").status_code == 200
    final = detail(meera, cid)
    assert final["content"]["status"] == "approved" and final["content"]["approved_by"] == "Meera"
    assert {"submitted", "changes_requested", "approved"} <= {a["action"] for a in final["audit"]}
    # approved content is locked
    assert neha.post(f"/api/content/{cid}/revise", body="changed", images=[]).status_code == 403
    assert meera.post(f"/api/content/{cid}/review").status_code == 403


def test_cannot_approve_with_open_findings(seeded, login, demo):
    neha, arjun = login(NEHA), login(ARJUN)
    cid = create_demo(neha, demo)
    neha.post(f"/api/content/{cid}/submit")
    r = arjun.post(f"/api/content/{cid}/approve")
    assert r.status_code == 400 and "decision" in r.get_json()["error"]


def test_dismissed_claim_requires_a_reviewer_to_approve(seeded, login, demo):
    neha, arjun, meera = login(NEHA), login(ARJUN), login(MEERA)
    cid = create_demo(neha, demo)
    body = "Hello,\n\nIndia's #1 coffee is here.\n\nWarmly, Brewline"
    neha.post(f"/api/content/{cid}/revise", body=body, images=[])
    f = finding(detail(neha, cid), "G-04")
    neha.post(f"/api/content/{cid}/submit")
    assert arjun.post(f"/api/findings/{f['id']}/decide", action="dismiss", reason="Legal confirmed by email").status_code == 200
    assert arjun.post(f"/api/content/{cid}/approve").status_code == 403  # manager cannot approve a dismissed claim
    assert meera.post(f"/api/content/{cid}/approve").status_code == 200


def test_external_agency_sees_only_own_work_and_no_confidential_material(seeded, login, demo):
    neha, rahul, arjun = login(NEHA), login(RAHUL), login(ARJUN)
    mine = create_demo(neha, demo)
    theirs = create_demo(rahul, demo, title="Rahul's draft")
    assert [c["id"] for c in neha.get("/api/content").get_json()] == [mine]
    assert neha.get(f"/api/content/{theirs}").status_code == 403
    assert neha.get("/api/kb").status_code == 403
    assert neha.post("/api/kb/seed").status_code == 403
    assert {c["id"] for c in arjun.get("/api/content").get_json()} == {mine, theirs}
    # findings still show the cited rule so the agency can fix the issue
    assert detail(neha, mine)["findings"][0]["source_quote"]
    # the audit trail is not shown to creators
    assert detail(neha, mine)["audit"] == []


def test_internal_creator_sees_guidelines_but_not_confidential_fact_sheet(seeded, login):
    kb = login(RAHUL).get("/api/kb").get_json()
    assert kb["guidelines"] and kb["facts"] == []
    assert len(login(ARJUN).get("/api/kb").get_json()["facts"]) == 4


def test_only_admin_imports_and_import_errors_are_clear(seeded, login):
    assert login(ARJUN).c.post("/api/kb/import", data={"kind": "facts", "text": "[]"}).status_code == 403
    ira = login(IRA)
    bad = ira.c.post("/api/kb/import", data={"kind": "facts", "text": "not json"})
    assert bad.status_code == 400 and "valid JSON" in bad.get_json()["error"]
    bad2 = ira.c.post("/api/kb/import", data={"kind": "glossary", "text": '[{"term":"x","preferred":"y","rule_code":"G-99"}]'})
    assert bad2.status_code == 400 and "G-99" in bad2.get_json()["error"]
    ok = ira.c.post("/api/kb/import", data={"kind": "guidelines", "title": "Extra", "text": "G-20 | Sign-off: End every email with a warm sign-off."})
    assert ok.status_code == 200 and ok.get_json()["rules"] == 1


def test_comments_and_audit_trail(seeded, login, demo):
    neha, arjun = login(NEHA), login(ARJUN)
    cid = create_demo(neha, demo)
    assert arjun.post(f"/api/content/{cid}/comments", body="Please check the price with the fact sheet").status_code == 201
    assert neha.post(f"/api/content/{cid}/comments", body="").status_code == 400
    d = detail(arjun, cid)
    assert d["comments"][0]["author"] == "Arjun"
    assert {"content_created", "review_run", "comment"} <= {a["action"] for a in d["audit"]}


def test_revise_creates_new_version_and_rereviews(seeded, login, demo):
    neha = login(NEHA)
    cid = create_demo(neha, demo)
    body = detail(neha, cid)["body"].replace("a cheap", "an affordable")
    assert neha.post(f"/api/content/{cid}/revise", body=body, images=demo["images"]).status_code == 200
    d = detail(neha, cid)
    assert d["content"]["current_version"] == 2
    assert not [f for f in d["findings"] if f["category"] == "terminology"]
    assert "a affordable" not in d["body"]
