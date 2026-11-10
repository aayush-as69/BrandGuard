"""Revise/decide/approve flow hardening."""
import pytest

from brandguard import db, workflow as wf
from brandguard.errors import Forbidden
from conftest import ARJUN, MEERA, NEHA


def test_a_manager_who_edited_the_content_cannot_approve_it(seeded, login):
    n, arjun = login(NEHA), login(ARJUN)
    cid = n.post("/api/content", title="t", body="Hello there.", images=[]).get_json()["id"]
    conn = db.connect(seeded.config["DB_PATH"])
    user = dict(conn.execute("SELECT * FROM users WHERE id=?", (ARJUN,)).fetchone())
    c = wf.get_content(conn, user, cid)
    wf._new_version(conn, c, ARJUN, "Hello there, friend.", [], "Edited by manager", None)
    conn.close()
    n.post(f"/api/content/{cid}/submit")
    r = arjun.post(f"/api/content/{cid}/approve")
    assert r.status_code == 403
    assert login(MEERA).post(f"/api/content/{cid}/approve").status_code == 200


def test_stale_status_changes_are_refused(seeded, login):
    n = login(NEHA)
    cid = n.post("/api/content", title="t", body="Hello there.", images=[]).get_json()["id"]
    conn = db.connect(seeded.config["DB_PATH"])
    user = dict(conn.execute("SELECT * FROM users WHERE id=?", (NEHA,)).fetchone())
    n.post(f"/api/content/{cid}/submit")
    reviewer = dict(conn.execute("SELECT * FROM users WHERE id=?", (MEERA,)).fetchone())
    wf.request_changes(conn, reviewer, cid, "fix")
    with pytest.raises((ValueError, Forbidden)):
        wf.request_changes(conn, reviewer, cid, "again")
    conn.close()


def test_docx_tables_are_read_in_order_and_merged_cells_once():
    import io
    import docx
    from brandguard import kb
    d = docx.Document()
    d.add_paragraph("Voice rules")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "R1", "Never say cheap"
    a = t.cell(1, 0).merge(t.cell(1, 1))
    a.text = "Merged note"
    d.add_paragraph("After the table")
    buf = io.BytesIO(); d.save(buf)
    out = kb.extract_text("g.docx", buf.getvalue()).splitlines()
    assert out == ["Voice rules", "R1 | Never say cheap", "Merged note", "After the table"]


def test_pdf_running_headers_and_page_numbers_are_dropped():
    from brandguard import kb
    pages = [f"Brewline Brand Guide\nRule {i}: keep it warm.\nPage {i}" for i in range(1, 5)]
    out = "\n".join(kb._drop_running_lines(pages))
    assert "Brewline Brand Guide" not in out and "Page 2" not in out
    assert "Rule 3: keep it warm." in out
    assert kb._drop_running_lines(pages[:2]) == pages[:2]
