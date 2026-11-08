from conftest import ARJUN, IRA, MEERA, NEHA, RAHUL


def _approved(login, title="Launch note"):
    n = login(NEHA)
    cid = n.post("/api/content", title=title, body="Hello there. Welcome to Brewline.", images=[]).get_json()["id"]
    n.post(f"/api/content/{cid}/submit")
    assert login(ARJUN).post(f"/api/content/{cid}/approve").status_code == 200
    return cid


def test_record_of_approved_content_names_approver_and_text(seeded, login):
    cid = _approved(login)
    r = login(MEERA).get(f"/api/content/{cid}/record")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and r.mimetype == "text/html"
    assert "Approved by <b>Arjun</b>" in html and "Welcome to Brewline." in html and "Audit trail" in html


def test_record_of_unapproved_content_says_so(seeded, login):
    n = login(NEHA)
    cid = n.post("/api/content", title="t", body="Hi Dude.", images=[]).get_json()["id"]
    html = n.get(f"/api/content/{cid}/record").get_data(as_text=True)
    assert "Not approved" in html and "not a clearance" in html
    assert "G-01" in html and "Not decided" in html          # findings with their sources
    assert "Audit trail" not in html                          # creators do not see the audit trail


def test_record_escapes_everything(seeded, login):
    n = login(NEHA)
    cid = n.post("/api/content", title="<script>alert(1)</script>", body="<img src=x onerror=alert(1)> Dude", images=[]).get_json()["id"]
    n.post(f"/api/content/{cid}/comments", body="<b>hi</b>")
    html = n.get(f"/api/content/{cid}/record").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html and "<img src=x" not in html and "<b>hi</b>" not in html
    assert "&lt;script&gt;" in html


def test_record_follows_the_same_access_rules(seeded, login):
    cid = _approved(login)
    assert login(RAHUL).get(f"/api/content/{cid}/record").status_code == 403   # another creator
    assert login(IRA).get(f"/api/content/{cid}/record").status_code == 200
    assert login(NEHA).get(f"/api/content/9999/record").status_code == 404
    anon = seeded.test_client()
    assert anon.get(f"/api/content/{cid}/record").status_code in (401, 403)
