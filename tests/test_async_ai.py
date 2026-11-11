"""AI review runs after the rule findings are already shown."""
import json
import threading

import pytest

from brandguard import db as dbm
from brandguard import workflow as wf
from brandguard.app import create_app
from conftest import NEHA, IRA, Session

BODY = "Hi there, our Brewline blend is a cheap way to wake up. Come now!"


@pytest.fixture()
def app_async(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AI_ASYNC", "1")
    gate = threading.Event()

    def call(system, user, model):
        gate.wait(10)
        return json.dumps([{"rule_code": "G-01", "quote": "x", "span": "cheap way to wake up", "issue": "reads as cheap",
                            "severity": "low", "confidence": "low", "fix": ""}])
    app = create_app(str(tmp_path / "a.db"), llm_call=call)
    app.gate = gate
    Session(app, IRA).post("/api/kb/seed")
    return app


def _wait(app):
    for f in list(app.ai_futures):
        f.result(timeout=20)


def test_rule_findings_return_before_the_ai_finishes(app_async):
    n = Session(app_async, NEHA)
    cid = n.post("/api/content", title="t", body=BODY, images=[]).get_json()["id"]  # returns while the AI is blocked
    d = n.get(f"/api/content/{cid}").get_json()
    assert d["review_meta"]["llm_status"].startswith("pending")
    assert d["findings"], "rule-based findings are there already"
    assert n.post(f"/api/content/{cid}/submit").status_code == 400  # not while the AI check is running
    app_async.gate.set()
    _wait(app_async)
    d = n.get(f"/api/content/{cid}").get_json()
    assert d["review_meta"]["llm_status"].startswith("used")
    assert not d["review_meta"]["llm_status"].startswith("pending")


def test_ai_failure_never_leaves_review_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AI_ASYNC", "1")

    def boom(*a):
        raise RuntimeError("provider down")
    app = create_app(str(tmp_path / "b.db"), llm_call=boom)
    Session(app, IRA).post("/api/kb/seed")
    n = Session(app, NEHA)
    cid = n.post("/api/content", title="t", body=BODY, images=[]).get_json()["id"]
    _wait(app)
    status = n.get(f"/api/content/{cid}").get_json()["review_meta"]["llm_status"]
    assert status.startswith("failed")
    assert n.post(f"/api/content/{cid}/submit").status_code == 200  # a failed AI check does not block the author


def test_new_version_discards_a_stale_ai_result(app_async):
    n = Session(app_async, NEHA)
    cid = n.post("/api/content", title="t", body=BODY, images=[]).get_json()["id"]
    n.post(f"/api/content/{cid}/revise", body=BODY + " Enjoy.", images=[])
    app_async.gate.set()
    _wait(app_async)
    conn = dbm.connect(app_async.config["DB_PATH"])
    v1 = json.loads(conn.execute("SELECT review_meta FROM versions WHERE content_id=? AND version=1", (cid,)).fetchone()[0])
    assert v1["llm_status"].startswith("pending")  # v1 was superseded, its late AI answer was not applied
    assert conn.execute("SELECT COUNT(*) FROM findings WHERE content_id=? AND version=1 AND ai_generated=1", (cid,)).fetchone()[0] == 0


def test_interrupted_reviews_are_settled_at_start(app_async, tmp_path):
    n = Session(app_async, NEHA)
    cid = n.post("/api/content", title="t", body=BODY, images=[]).get_json()["id"]
    conn = dbm.connect(app_async.config["DB_PATH"])
    meta = json.loads(conn.execute("SELECT review_meta FROM versions WHERE content_id=?", (cid,)).fetchone()[0])
    assert wf.settle_interrupted_reviews(conn) == 0  # fresh: another worker may still be running it
    meta["pending_since"] = "2000-01-01T00:00:00+00:00"
    conn.execute("UPDATE versions SET review_meta=? WHERE content_id=?", (json.dumps(meta), cid))
    conn.commit()
    assert wf.settle_interrupted_reviews(conn) == 1
    app_async.gate.set()
    _wait(app_async)
