"""What the AI request log keeps, who can read it, how long it lives, and the author's opt-out."""
import datetime as dt
import hashlib
import json
import sqlite3

import pytest

from brandguard.app import create_app
from conftest import ARJUN, IRA, MEERA, NEHA, Session

SECRET_TEXT = "Hi there, our Brewline blend is a cheap way to wake up. CONFIDENTIAL-LAUNCH-PLAN-7781."


def fake_ai(calls):
    def call(system, user, model):
        calls.append(user)
        return "[]"
    return call


@pytest.fixture()
def ai_app(tmp_path):
    calls = []
    app = create_app(str(tmp_path / "ai.db"), llm_call=fake_ai(calls))
    app.calls = calls
    Session(app, IRA).post("/api/kb/seed")
    return app


def _log_rows(app):
    conn = sqlite3.connect(app.config["DB_PATH"])
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute("SELECT * FROM llm_log ORDER BY id")]


def _create(app, body=SECRET_TEXT, **extra):
    n = Session(app, NEHA)
    r = n.post("/api/content", title="t", body=body, images=[], **extra)
    assert r.status_code == 201, r.get_json()
    return n, r.get_json()["id"]


def test_by_default_the_log_keeps_metadata_but_not_the_text(ai_app):
    _create(ai_app)
    (row,) = _log_rows(ai_app)
    assert row["payload"] == ""
    assert row["content_sha256"] == hashlib.sha256(SECRET_TEXT.encode()).hexdigest()
    assert row["chars"] == len(SECRET_TEXT) and json.loads(row["rules"]) and row["status"].startswith("used")
    dump = json.dumps(row)
    assert "CONFIDENTIAL-LAUNCH-PLAN" not in dump and "cheap way" not in dump
    assert ai_app.calls and "CONFIDENTIAL-LAUNCH-PLAN-7781" in ai_app.calls[0]   # it WAS sent; just not kept


def test_the_full_text_is_kept_only_when_explicitly_enabled(ai_app, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AI_LOG", "full")
    _create(ai_app)
    assert "CONFIDENTIAL-LAUNCH-PLAN-7781" in _log_rows(ai_app)[0]["payload"]


def test_only_admins_can_read_a_full_payload(ai_app, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AI_LOG", "full")
    _create(ai_app)
    admin = Session(ai_app, IRA).get("/api/llm-log").get_json()[0]
    assert "CONFIDENTIAL-LAUNCH-PLAN-7781" in admin["payload"]
    for who in (ARJUN, MEERA):
        row = Session(ai_app, who).get("/api/llm-log").get_json()[0]
        assert "payload" not in row and row["has_payload"] is True and row["chars"] == len(SECRET_TEXT)
        assert "CONFIDENTIAL-LAUNCH-PLAN" not in json.dumps(row)
    assert Session(ai_app, NEHA).get("/api/llm-log").status_code == 403


def test_old_log_rows_are_deleted_after_the_retention_period(ai_app, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AI_LOG", "full")
    monkeypatch.setenv("BRANDGUARD_AI_RETENTION_DAYS", "7")
    _create(ai_app)
    conn = sqlite3.connect(ai_app.config["DB_PATH"])
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=8)).isoformat(timespec="seconds")
    conn.execute("UPDATE llm_log SET created_at=?", (old,))
    conn.commit()
    _create(ai_app, body="A fresh post, a little cheap.")        # the next AI call purges the expired row
    rows = _log_rows(ai_app)
    assert len(rows) == 1 and "fresh post" in rows[0]["payload"]
    # ...and a restart purges too
    conn.execute("UPDATE llm_log SET created_at=?", (old,))
    conn.commit()
    create_app(ai_app.config["DB_PATH"])
    assert _log_rows(ai_app) == []


def test_zero_retention_keeps_nothing(ai_app, monkeypatch):
    monkeypatch.setenv("BRANDGUARD_AI_RETENTION_DAYS", "0")
    _create(ai_app)
    _create(ai_app, body="second, also cheap")
    assert len(_log_rows(ai_app)) <= 1      # the previous row is gone by the next call


def test_an_author_can_switch_ai_off_and_nothing_is_sent(ai_app):
    n, cid = _create(ai_app, use_ai=False)
    assert ai_app.calls == [] and _log_rows(ai_app) == []
    meta = n.get(f"/api/content/{cid}").get_json()["review_meta"]
    assert meta["llm_status"].startswith("skipped") and "not sent" in meta["llm_status"]
    assert n.get(f"/api/content/{cid}").get_json()["findings"]            # the rule-based review still ran
    assert n.post(f"/api/content/{cid}/review", use_ai=False).status_code == 200 and ai_app.calls == []
    assert n.post(f"/api/content/{cid}/revise", body="Hi cheap world", images=[], use_ai=False).status_code == 200
    assert ai_app.calls == []
    assert n.post(f"/api/content/{cid}/review", use_ai=True).status_code == 200 and len(ai_app.calls) == 1


def test_use_ai_must_be_a_boolean(ai_app):
    n = Session(ai_app, NEHA)
    assert n.post("/api/content", title="t", body="Hi", images=[], use_ai="no").status_code == 400


def test_config_discloses_the_ai_service_and_what_is_kept(ai_app, app):
    ai = ai_app.test_client().get("/api/config").get_json()["ai"]
    assert ai["enabled"] and ai["provider"] == "Anthropic" and "sent to Anthropic" in ai["notice"]
    assert "without the text itself" in ai["notice"] and ai["retention_days"] == 30
    assert app.test_client().get("/api/config").get_json()["ai"]["enabled"] is False   # no key, no AI, no notice


import os

import pytest


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("BRANDGUARD_LLM") == "off",
                    reason="live AI check: set ANTHROPIC_API_KEY (and have network access) to run")
def test_live_provider_returns_parseable_findings():
    from brandguard import llm
    text = llm.default_call(llm.SYSTEM, "BRAND RULES\nG-01: Keep a warm, friendly tone.\n\n<content>\nBuy now or lose out, loser.\n</content>",
                            os.environ.get("BRANDGUARD_MODEL", llm.DEFAULT_MODEL))
    assert isinstance(llm._parse(text), list)
