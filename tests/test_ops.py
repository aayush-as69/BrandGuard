import subprocess
import sys
from pathlib import Path

from brandguard import db, retention
from conftest import ARJUN, IRA, NEHA, Session

ROOT = Path(__file__).resolve().parents[1]


def test_deletion_removes_everything_and_leaves_a_tombstone(app):
    n = Session(app, NEHA)
    keep = n.post("/api/content", title="keep", body="Hello there.", images=[]).get_json()["id"]
    gone = n.post("/api/content", title="SECRET-TITLE-XYZ", body="Hello there, Dude!", images=[]).get_json()["id"]
    n.post(f"/api/content/{gone}/comments", body="a comment")
    conn = db.connect(app.config["DB_PATH"])
    retention.delete_content(conn, gone, "ops@example.com", "ticket DSR-1")
    for table in ("versions", "findings", "comments", "claims", "audit", "llm_log"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE content_id=?", (gone,)).fetchone()[0] == 0, table
    assert conn.execute("SELECT COUNT(*) FROM content WHERE id=?", (keep,)).fetchone()[0] == 1
    tomb = conn.execute("SELECT detail FROM audit WHERE action='content_deleted'").fetchone()[0]
    assert "DSR-1" in tomb and "SECRET-TITLE-XYZ" not in tomb
    try:
        retention.delete_content(conn, keep, "ops", " ")
        raise AssertionError("a reason is required")
    except ValueError:
        pass
    finally:
        conn.close()


def test_smoke_script_passes_against_a_real_server(tmp_path):
    import os
    import socket
    import time
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, BRANDGUARD_DB=str(tmp_path / "s.db"), PORT=str(port), BRANDGUARD_AUTH="accounts",
               BRANDGUARD_ADMIN_EMAIL="boss@example.com", BRANDGUARD_ADMIN_PASSWORD="correct-horse-battery")
    env.pop("BRANDGUARD_ENV", None)
    srv = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.2)
        out = subprocess.run([sys.executable, "scripts/smoke_test.py", f"http://127.0.0.1:{port}", "--email", "boss@example.com",
                              "--password", "correct-horse-battery"], cwd=ROOT, capture_output=True, text=True)
        # plain http is flagged (production must be https); everything else must pass
        failed = [l for l in out.stdout.splitlines() if l.startswith("FAIL")]
        assert failed == ["FAIL served over HTTPS - use the https:// address; production cookies are Secure"], out.stdout
    finally:
        srv.terminate()


def test_hsts_only_in_production(tmp_path, monkeypatch):
    from brandguard.app import create_app
    assert "Strict-Transport-Security" not in create_app(str(tmp_path / "a.db")).test_client().get("/healthz").headers
    monkeypatch.setenv("BRANDGUARD_ENV", "production")
    monkeypatch.setenv("BRANDGUARD_SECRET", "s" * 24)
    monkeypatch.setenv("BRANDGUARD_ADMIN_EMAIL", "a@b.co")
    monkeypatch.setenv("BRANDGUARD_ADMIN_PASSWORD", "long-enough-pass")
    assert "Strict-Transport-Security" in create_app(str(tmp_path / "b.db")).test_client().get("/healthz").headers


def test_global_search_is_scoped_and_bounded(seeded, login):
    n = login(NEHA)
    cid = n.post("/api/content", title="Searchable Campaign", body="hello searchneedle", images=[]).get_json()["id"]
    r = n.get("/api/search?q=searchneedle")
    assert r.status_code == 200
    assert any(x["kind"] == "content" and x["id"] == cid for x in r.get_json()["results"])
    assert n.get("/api/search?q=x").get_json()["results"] == []


def test_global_search_respects_knowledge_clearance(seeded, login):
    r = login(NEHA).get("/api/search?q=Rivalbrew")
    assert all(x.get("id") != "Z-01" for x in r.get_json()["results"])
    manager = login(ARJUN).get("/api/search?q=Rivalbrew")
    assert any(x.get("id") == "Z-01" for x in manager.get_json()["results"])
