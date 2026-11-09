import subprocess
import sqlite3
import sys
from pathlib import Path

import pytest

from brandguard import db as dbm

ROOT = Path(__file__).resolve().parent.parent
LATEST = max(n for n, _, _ in dbm.MIGRATIONS)


def _version1(path):
    """A database as the first release made it: baseline schema, no version number, real data in it."""
    conn = sqlite3.connect(path)
    conn.executescript(dbm.SCHEMA)
    conn.executemany("INSERT INTO users(id, name, role, is_external) VALUES (?,?,?,?)", dbm.DEFAULT_USERS)
    conn.execute("INSERT INTO content(id, title, author_id, created_at) VALUES (1,'Old post',1,'2026-01-01')")
    conn.execute("INSERT INTO llm_log(content_id, version, model, payload, created_at) VALUES (1,1,'m','full prompt','2026-01-01T00:00:00+00:00')")
    conn.commit()
    conn.close()


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_a_new_database_is_fully_migrated(tmp_path):
    conn = dbm.connect(str(tmp_path / "n.db"))
    dbm.init(conn)
    assert dbm.schema_version(conn) == LATEST
    assert {"password_hash", "session_epoch", "active", "email"} <= _columns(conn, "users")
    assert {"content_sha256", "chars", "rules", "status"} <= _columns(conn, "llm_log")
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_findings_content_version", "idx_audit_content", "idx_users_email"} <= names


def test_an_old_database_is_upgraded_and_keeps_its_data(tmp_path):
    path = str(tmp_path / "old.db")
    _version1(path)
    conn = dbm.connect(path)
    assert dbm.schema_version(conn) == 0
    dbm.init(conn)
    assert dbm.schema_version(conn) == LATEST
    assert conn.execute("SELECT title FROM content WHERE id=1").fetchone()[0] == "Old post"
    row = conn.execute("SELECT payload, chars, status FROM llm_log").fetchone()
    assert tuple(row) == ("full prompt", 0, "")           # old rows survive; new columns take defaults
    assert conn.execute("SELECT active, session_epoch FROM users WHERE id=4").fetchone()[:] == (1, 0)


def test_running_init_again_changes_nothing(tmp_path):
    conn = dbm.connect(str(tmp_path / "r.db"))
    dbm.init(conn)
    assert dbm.migrate(conn) == []
    dbm.init(conn)
    assert dbm.schema_version(conn) == LATEST


def test_a_failing_migration_rolls_back_completely(tmp_path):
    conn = dbm.connect(str(tmp_path / "f.db"))
    dbm.init(conn)

    def broken(c):
        c.execute("ALTER TABLE content ADD COLUMN oops TEXT")   # a change that must not survive
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        dbm.migrate(conn, [(LATEST + 1, "broken", broken)])
    assert dbm.schema_version(conn) == LATEST
    assert "oops" not in _columns(conn, "content")
    assert dbm.migrate(conn) == []                              # and the database is still usable
    conn.execute("INSERT INTO content(title, author_id, created_at) VALUES ('ok',1,'now')")


def test_two_processes_migrating_at_once_do_not_clash(tmp_path):
    path = str(tmp_path / "race.db")
    _version1(path)
    code = ("import sys; sys.path.insert(0, %r); from brandguard import db; c = db.connect(%r); "
            "db.init(c); print(db.schema_version(c))" % (str(ROOT), path))
    procs = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for _ in range(4)]
    for p in procs:
        out, err = p.communicate(timeout=60)
        assert p.returncode == 0, err
        assert out.strip() == str(LATEST)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM findings WHERE content_id=1 AND version=1",
    "SELECT * FROM claims WHERE content_id=1 AND version=1",
    "SELECT * FROM comments WHERE content_id=1",
    "SELECT * FROM audit WHERE content_id=1 ORDER BY id",
    "SELECT * FROM content WHERE author_id=1 AND status='draft'",
    "SELECT source_id, COUNT(*) FROM findings WHERE version=1 GROUP BY source_id",
    "SELECT * FROM rules WHERE guideline_id=1",
])
def test_the_main_queries_use_an_index(tmp_path, sql):
    conn = dbm.connect(str(tmp_path / "p.db"))
    dbm.init(conn)
    plan = " | ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql))
    assert "USING" in plan and "INDEX" in plan, plan
    assert "SCAN findings" not in plan and "SCAN audit" not in plan and "SCAN comments" not in plan


def test_killed_mid_migration_leaves_the_database_recoverable(tmp_path):
    """A process killed in the middle of a migration changes nothing; the next start finishes the job."""
    import signal
    import time
    path = str(tmp_path / "kill.db")
    conn = dbm.connect(path)
    dbm.init(conn)
    conn.close()
    code = (
        "import sys, time; sys.path.insert(0, %r)\n"
        "from brandguard import db\n"
        "c = db.connect(%r)\n"
        "def slow(conn):\n"
        "    conn.execute('ALTER TABLE content ADD COLUMN half_done TEXT')\n"
        "    print('started', flush=True); time.sleep(60)\n"
        "db.migrate(c, [(%d, 'slow', slow)])\n" % (str(ROOT), path, LATEST + 1))
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "started"
    proc.send_signal(signal.SIGKILL)
    proc.wait()
    time.sleep(0.2)
    after = dbm.connect(path)
    assert dbm.schema_version(after) == LATEST and "half_done" not in _columns(after, "content")
    assert after.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    dbm.init(after)                                    # a normal start works and the app is healthy
    assert dbm.schema_version(after) == LATEST
    after.close()


def test_migrations_are_append_only_and_numbered_in_order():
    numbers = [n for n, _, _ in dbm.MIGRATIONS]
    assert numbers == list(range(2, 2 + len(numbers)))
