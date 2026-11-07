"""SQLite storage (dev). Plain sqlite3 so the project has no extra dependencies."""
from __future__ import annotations

import datetime as dt
import sqlite3

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
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO users(id, name, role, is_external) VALUES (?,?,?,?)", DEFAULT_USERS
        )
    conn.commit()
