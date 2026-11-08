from conftest import ARJUN, IRA, MEERA, NEHA, RAHUL


def _content(login, body):
    n = login(NEHA)
    cid = n.post("/api/content", title="t", body=body, images=[]).get_json()["id"]
    return n, cid


def test_insights_count_mistakes_and_disputes(seeded, login):
    # Two pieces both use slang; the author dismisses it once, fixes it once.
    n1, c1 = _content(login, "Hi Dude, welcome.")
    n2, c2 = _content(login, "Hey Dude, welcome back.")
    f1 = n1.get(f"/api/content/{c1}").get_json()["findings"][0]["id"]
    f2 = n2.get(f"/api/content/{c2}").get_json()["findings"][0]["id"]
    assert login(NEHA).post(f"/api/findings/{f1}/decide", action="dismiss", reason="friendly tone").status_code == 200
    assert login(NEHA).post(f"/api/findings/{f2}/decide", action="dismiss", reason="friendly tone").status_code == 200
    d = login(ARJUN).get("/api/insights").get_json()
    rule = next(r for r in d["rules"] if r["code"] == "G-01")
    assert rule["flagged"] == 2 and rule["dismissed"] == 2 and rule["dismissal_rate"] == 1.0
    assert rule["often_disputed"] is True and rule["title"]
    assert d["content"]["total"] == 2 and d["content"]["draft"] == 2


def test_carried_over_dismissals_are_not_double_counted(seeded, login):
    n, cid = _content(login, "Hi Dude, welcome. Our cheap beans.")
    d0 = n.get(f"/api/content/{cid}").get_json()
    dude = next(f["id"] for f in d0["findings"] if f["span_text"] == "Dude")
    n.post(f"/api/findings/{dude}/decide", action="dismiss", reason="friendly tone")
    cheap = next(f["id"] for f in d0["findings"] if "cheap" in f["span_text"])
    n.post(f"/api/findings/{cheap}/decide", action="accept")  # new version, dismissal carried over
    rule = next(r for r in login(ARJUN).get("/api/insights").get_json()["rules"] if r["code"] == "G-01")
    assert rule["dismissed"] == 1


def test_time_to_approval_and_change_requests(seeded, login):
    n, cid = _content(login, "Hello there. Welcome to Brewline.")
    assert n.post(f"/api/content/{cid}/submit").status_code == 200
    assert login(ARJUN).post(f"/api/content/{cid}/approve").status_code == 200
    d = login(MEERA).get("/api/insights").get_json()
    assert d["content"]["approved"] == 1 and d["avg_hours_to_approve"] is not None and d["avg_hours_to_approve"] >= 0


def test_insights_are_for_guideline_owners_only(seeded, login):
    assert login(IRA).get("/api/insights").status_code == 200
    assert login(MEERA).get("/api/insights").status_code == 200
    assert login(NEHA).get("/api/insights").status_code == 403
    assert login(RAHUL).get("/api/insights").status_code == 403


def test_insights_show_no_person_names(seeded, login):
    n, cid = _content(login, "Hi Dude.")
    f = n.get(f"/api/content/{cid}").get_json()["findings"][0]["id"]
    n.post(f"/api/findings/{f}/decide", action="dismiss", reason="ok")
    text = login(IRA).get("/api/insights").get_data(as_text=True)
    assert "Neha" not in text and "Arjun" not in text


def test_insights_on_an_empty_database(app, login):
    d = login(IRA).get("/api/insights").get_json()
    assert d["rules"] == [] and d["avg_hours_to_approve"] is None
