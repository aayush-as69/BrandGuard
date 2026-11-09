"""SQLite storage (dev). Plain sqlite3 so the project has no extra dependencies."""
from __future__ import annotations

import datetime as dt
import sqlite3
import time
from typing import Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('creator','manager','reviewer','admin')),
  is_external INTEGER NOT NULL DEFAULT 0,
  org TEXT NOT NULL DEFAULT 'Brewline Coffee'
);

-- Knowledge base ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS guidelines(
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  access_level TEXT NOT NULL DEFAULT 'internal',
  imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rules(
  id INTEGER PRIMARY KEY,
  guideline_id INTEGER NOT NULL REFERENCES guidelines(id) ON DELETE CASCADE,
  code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts(
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  statement TEXT NOT NULL,
  data TEXT NOT NULL DEFAULT '{}',
  source TEXT NOT NULL DEFAULT '',
  access_level TEXT NOT NULL DEFAULT 'internal'
);
CREATE TABLE IF NOT EXISTS glossary(
  id INTEGER PRIMARY KEY,
  term TEXT NOT NULL,
  preferred TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'banned',
  rule_code TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS assets(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  access_level TEXT NOT NULL DEFAULT 'internal'
);
CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- Content, versions, findings -------------------------------------------------
CREATE TABLE IF NOT EXISTS content(
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  author_id INTEGER NOT NULL REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK(status IN ('draft','in_review','changes_requested','approved')),
  current_version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS versions(
  id INTEGER PRIMARY KEY,
  content_id INTEGER NOT NULL REFERENCES content(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  body TEXT NOT NULL,
  images TEXT NOT NULL DEFAULT '[]',
  created_by INTEGER NOT NULL REFERENCES users(id),
  note TEXT NOT NULL DEFAULT '',
  review_meta TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(content_id, version)
);
CREATE TABLE IF NOT EXISTS findings(
  id INTEGER PRIMARY KEY,
  content_id INTEGER NOT NULL REFERENCES content(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  category TEXT NOT NULL,
  issue TEXT NOT NULL,
  span_text TEXT NOT NULL DEFAULT '',
  span_start INTEGER NOT NULL DEFAULT -1,
  span_end INTEGER NOT NULL DEFAULT -1,
  target TEXT NOT NULL DEFAULT 'body',
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_quote TEXT NOT NULL,
  severity TEXT NOT NULL,
  confidence TEXT NOT NULL,
  suggested_fix TEXT,
  fix_note TEXT NOT NULL DEFAULT '',
  ai_generated INTEGER NOT NULL DEFAULT 0,
  needs_reviewer INTEGER NOT NULL DEFAULT 0,
  decision TEXT NOT NULL DEFAULT 'open'
    CHECK(decision IN ('open','accepted','edited','dismissed')),
  decision_reason TEXT NOT NULL DEFAULT '',
  decision_text TEXT,
  decided_by INTEGER REFERENCES users(id),
  decided_at TEXT
);
CREATE TABLE IF NOT EXISTS claims(
  id INTEGER PRIMARY KEY,
  content_id INTEGER NOT NULL REFERENCES content(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  text TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('supported','contradicted','no_approved_source')),
  source_id TEXT NOT NULL DEFAULT ''
);

-- Collaboration and audit -----------------------------------------------------
CREATE TABLE IF NOT EXISTS comments(
  id INTEGER PRIMARY KEY,
  content_id INTEGER NOT NULL REFERENCES content(id) ON DELETE CASCADE,
  finding_id INTEGER,
  user_id INTEGER NOT NULL REFERENCES users(id),
  body TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY,
  content_id INTEGER,
  user_id INTEGER,
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
-- Everything sent to an external AI service, for disclosure.
CREATE TABLE IF NOT EXISTS llm_log(
  id INTEGER PRIMARY KEY,
  content_id INTEGER,
  version INTEGER,
  model TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""

DEFAULT_USERS = [
    (1, "Neha", "creator", 1),    # agency creator: external, sees only her own work
    (2, "Arjun", "manager", 0),   # brand manager
    (3, "Meera", "reviewer", 0),  # claims approver
    (4, "Ira", "admin", 0),       # guideline owner
    (5, "Rahul", "creator", 0),   # in-house creator
]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# --------------------------------------------------------------------- migrations
# SCHEMA above is version 1 (the baseline). Every later change is a numbered migration below, applied once,
# in order, inside a transaction: either all of it happens and the version number moves, or none of it does.
# NEVER edit a migration that has shipped; add a new one.
def _m2_indexes(conn: sqlite3.Connection) -> None:
    for stmt in (
        "CREATE INDEX IF NOT EXISTS idx_findings_content_version ON findings(content_id, version)",
        "CREATE INDEX IF NOT EXISTS idx_findings_version_source ON findings(version, source_id)",
        "CREATE INDEX IF NOT EXISTS idx_claims_content_version ON claims(content_id, version)",
        "CREATE INDEX IF NOT EXISTS idx_comments_content ON comments(content_id)",
        "CREATE INDEX IF NOT EXISTS idx_audit_content ON audit(content_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit(action, content_id)",
        "CREATE INDEX IF NOT EXISTS idx_content_author_status ON content(author_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_content_status ON content(status)",
        "CREATE INDEX IF NOT EXISTS idx_rules_guideline ON rules(guideline_id)",
        "CREATE INDEX IF NOT EXISTS idx_llm_log_created ON llm_log(created_at)",
    ):
        conn.execute(stmt)


def _m3_llm_log_metadata(conn: sqlite3.Connection) -> None:
    """The AI log keeps audit metadata by default; the full prompt is optional (see llm.py)."""
    for col in ("content_sha256 TEXT NOT NULL DEFAULT ''", "chars INTEGER NOT NULL DEFAULT 0",
                "rules TEXT NOT NULL DEFAULT '[]'", "status TEXT NOT NULL DEFAULT ''"):
        conn.execute(f"ALTER TABLE llm_log ADD COLUMN {col}")


def _m4_accounts(conn: sqlite3.Connection) -> None:
    for col in ("email TEXT", "password_hash TEXT", "active INTEGER NOT NULL DEFAULT 1",
                "session_epoch INTEGER NOT NULL DEFAULT 0", "last_login TEXT"):
        conn.execute(f"ALTER TABLE users ADD COLUMN {col}")
    conn.execute("CREATE UNIQUE INDEX idx_users_email ON users(lower(email)) WHERE email IS NOT NULL")


def _m5_mfa(conn: sqlite3.Connection) -> None:
    for col in ("totp_secret TEXT", "totp_pending TEXT", "totp_last INTEGER NOT NULL DEFAULT 0"):
        conn.execute(f"ALTER TABLE users ADD COLUMN {col}")


MIGRATIONS: list[tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (2, "indexes on the main query paths", _m2_indexes),
    (3, "AI log keeps metadata, not just the prompt", _m3_llm_log_metadata),
    (4, "individual accounts: email, password hash, active flag, session epoch", _m4_accounts),
    (5, "two-step sign-in (TOTP) columns", _m5_mfa),
]


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection, migrations=None) -> list[int]:
    """Apply every migration newer than the database's version. Returns the versions applied.
    Safe to run from several processes at once: the first to take the write lock does the work."""
    applied: list[int] = []
    for number, _, fn in (MIGRATIONS if migrations is None else migrations):
        if schema_version(conn) >= number:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            if schema_version(conn) < number:  # re-check: another process may have just done it
                fn(conn)
                conn.execute(f"PRAGMA user_version = {int(number)}")
                applied.append(number)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return applied


def _enable_wal(conn: sqlite3.Connection) -> None:
    """Switching to WAL needs a lock that SQLite's busy timeout does not always wait for, so retry briefly
    when several processes start together. (Once the database is in WAL mode this is a no-op.)"""
    for attempt in range(60):
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) or attempt == 59:
                raise
            time.sleep(0.25)


def init(conn: sqlite3.Connection, demo_users: bool = True) -> None:
    """Create or upgrade the database. `demo_users` adds the five demo identities to an empty database."""
    _enable_wal(conn)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")  # under the lock, so a second process can never move the version backwards
    try:
        if schema_version(conn) == 0:
            conn.execute("PRAGMA user_version = 1")  # the baseline schema is in place
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    migrate(conn)
    if demo_users and conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO users(id, name, role, is_external) VALUES (?,?,?,?)", DEFAULT_USERS
        )
    conn.commit()
