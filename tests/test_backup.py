import importlib.util
import sqlite3
from pathlib import Path

import pytest

from brandguard.app import create_app
from conftest import IRA, NEHA, Session

spec = importlib.util.spec_from_file_location("backup", Path(__file__).resolve().parents[1] / "scripts" / "backup.py")
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def _app_with_content(tmp_path):
    app = create_app(str(tmp_path / "live.db"))
    Session(app, IRA).post("/api/kb/seed")
    Session(app, NEHA).post("/api/content", title="Keep me", body="Hello there.", images=[])
    return app


def test_plain_backup_and_restore_round_trip(tmp_path, monkeypatch):
    monkeypatch.delenv("BRANDGUARD_BACKUP_KEY", raising=False)
    app = _app_with_content(tmp_path)
    out = tmp_path / "b.db"
    backup.backup(app.config["DB_PATH"], str(out))
    new = tmp_path / "restored.db"
    backup.restore(str(out), str(new))
    assert sqlite3.connect(new).execute("SELECT title FROM content").fetchone()[0] == "Keep me"
    assert create_app(str(new)).test_client().get("/healthz").get_json()["status"] == "ok"


def test_encrypted_backup_hides_content_and_needs_the_key(tmp_path, monkeypatch):
    fernet = pytest.importorskip("cryptography.fernet")
    key = fernet.Fernet.generate_key().decode()
    monkeypatch.setenv("BRANDGUARD_BACKUP_KEY", key)
    app = _app_with_content(tmp_path)
    out = tmp_path / "b.enc"
    backup.backup(app.config["DB_PATH"], str(out))
    assert b"Keep me" not in out.read_bytes() and b"SQLite format" not in out.read_bytes()
    monkeypatch.delenv("BRANDGUARD_BACKUP_KEY")
    with pytest.raises(SystemExit):
        backup.restore(str(out), str(tmp_path / "x.db"))
    monkeypatch.setenv("BRANDGUARD_BACKUP_KEY", key)
    backup.restore(str(out), str(tmp_path / "x.db"))
    assert sqlite3.connect(tmp_path / "x.db").execute("SELECT COUNT(*) FROM content").fetchone()[0] == 1
