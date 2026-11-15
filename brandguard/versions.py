"""Version history for guideline rules.

The `rules` table always holds the PUBLISHED text, because that is what reviews are checked against.
`rule_versions` is an append-only history around it:

  draft      a proposed change, not used by any review (at most one per rule)
  published  the version that matches `rules` right now (exactly one per rule)
  archived   a version that was published earlier

History is never edited or deleted by publish or rollback. A rollback publishes a NEW version that copies
the old text, so the record of what was live, and when, stays complete. Anything that changes `rules`
outside this module (a direct edit, an import, the demo seed) is noticed by `sync` and recorded as a version.
"""
import difflib
import re
import sqlite3
from typing import Optional

from .errors import NotFound
from .workflow import now

MAX_TEXT = 4000
MAX_TITLE = 200
MAX_NOTE = 300


def _rule(conn, code: str) -> sqlite3.Row:
    row = conn.execute("SELECT code, title, text FROM rules WHERE code=?", (code,)).fetchone()
    if not row:
        raise NotFound("No such rule")
    return row


def _next(conn, code: str) -> int:
    return (conn.execute("SELECT COALESCE(MAX(version),0) FROM rule_versions WHERE rule_code=?", (code,)).fetchone()[0]) + 1


def _clean(value, what: str, limit: int, required: bool = True) -> str:
    if value is None or not isinstance(value, str):
        if required:
            raise ValueError(f"{what} is required")
        return ""
    value = value.strip()
    if required and not value:
        raise ValueError(f"{what} cannot be empty")
    if len(value) > limit:
        raise ValueError(f"{what} is too long (at most {limit} characters)")
    return value


def sync(conn, code: str, user_id: Optional[int] = None, note: str = "") -> None:
    """Make the history agree with the live rule: create version 1 on first use, and record a new
    published version if the live text was changed some other way. Does not commit."""
    live = _rule(conn, code)
    cur = conn.execute("SELECT * FROM rule_versions WHERE rule_code=? AND status='published'", (code,)).fetchone()
    if cur and cur["title"] == live["title"] and cur["text"] == live["text"]:
        return
    stamp = now()
    if cur:
        conn.execute("UPDATE rule_versions SET status='archived' WHERE id=?", (cur["id"],))
    n = _next(conn, code)
    conn.execute(
        "INSERT INTO rule_versions(rule_code, version, title, text, status, note, created_by, created_at, published_at)"
        " VALUES (?,?,?,?,'published',?,?,?,?)",
        (code, n, live["title"], live["text"],
         note or ("Starting version" if n == 1 else "Changed directly in the knowledge base"), user_id, stamp, stamp))


def list_versions(conn, code: str) -> dict:
    _rule(conn, code)
    sync(conn, code)
    conn.commit()
    rows = conn.execute(
        "SELECT v.version, v.title, v.text, v.status, v.note, v.created_at, v.published_at, u.name AS author "
        "FROM rule_versions v LEFT JOIN users u ON u.id=v.created_by WHERE v.rule_code=? ORDER BY v.version DESC", (code,)).fetchall()
    versions = [dict(r) for r in rows]
    return {"code": code,
            "published": next((v for v in versions if v["status"] == "published"), None),
            "draft": next((v for v in versions if v["status"] == "draft"), None),
            "versions": versions}


def save_draft(conn, code: str, user_id: int, text, title=None, note=None) -> int:
    """Create the draft, or replace the existing one. Nothing a review uses changes until it is published."""
    live = _rule(conn, code)
    text = _clean(text, "Rule text", MAX_TEXT)
    title = _clean(title, "Title", MAX_TITLE, required=False) or live["title"]
    note = _clean(note, "Note", MAX_NOTE, required=False)
    sync(conn, code, user_id)
    draft = conn.execute("SELECT * FROM rule_versions WHERE rule_code=? AND status='draft'", (code,)).fetchone()
    if draft:
        conn.execute("UPDATE rule_versions SET title=?, text=?, note=?, created_by=?, created_at=? WHERE id=?",
                     (title, text, note, user_id, now(), draft["id"]))
        version = draft["version"]
    else:
        version = _next(conn, code)
        conn.execute("INSERT INTO rule_versions(rule_code, version, title, text, status, note, created_by, created_at)"
                     " VALUES (?,?,?,?,'draft',?,?,?)", (code, version, title, text, note, user_id, now()))
    conn.commit()
    return version


def discard_draft(conn, code: str) -> None:
    _rule(conn, code)
    if not conn.execute("DELETE FROM rule_versions WHERE rule_code=? AND status='draft'", (code,)).rowcount:
        raise NotFound("There is no draft to discard")
    conn.commit()


def _make_live(conn, code: str, title: str, text: str) -> None:
    conn.execute("UPDATE rules SET title=?, text=? WHERE code=?", (title, text, code))


def publish(conn, code: str, user_id: int) -> int:
    """The draft becomes the live rule. The previous version is archived, not removed."""
    _rule(conn, code)
    sync(conn, code, user_id)
    draft = conn.execute("SELECT * FROM rule_versions WHERE rule_code=? AND status='draft'", (code,)).fetchone()
    if not draft:
        raise ValueError("There is no draft to publish. Save a draft first.")
    cur = conn.execute("SELECT * FROM rule_versions WHERE rule_code=? AND status='published'", (code,)).fetchone()
    if cur and cur["title"] == draft["title"] and cur["text"] == draft["text"]:
        raise ValueError("The draft is identical to the published version, so there is nothing to publish.")
    if cur:
        conn.execute("UPDATE rule_versions SET status='archived' WHERE id=?", (cur["id"],))
    conn.execute("UPDATE rule_versions SET status='published', published_at=?, created_by=? WHERE id=?", (now(), user_id, draft["id"]))
    _make_live(conn, code, draft["title"], draft["text"])
    conn.commit()
    return draft["version"]


def rollback(conn, code: str, version: int, user_id: int) -> int:
    """Publish a new version that copies an older one. The old version and everything after it stay in the history."""
    _rule(conn, code)
    sync(conn, code, user_id)
    old = conn.execute("SELECT * FROM rule_versions WHERE rule_code=? AND version=? AND status!='draft'", (code, version)).fetchone()
    if not old:
        raise NotFound("No such published version")
    cur = conn.execute("SELECT * FROM rule_versions WHERE rule_code=? AND status='published'", (code,)).fetchone()
    if cur["version"] == old["version"]:
        raise ValueError(f"Version {version} is already the published version.")
    conn.execute("UPDATE rule_versions SET status='archived' WHERE id=?", (cur["id"],))
    n = _next(conn, code)
    stamp = now()
    conn.execute("INSERT INTO rule_versions(rule_code, version, title, text, status, note, created_by, created_at, published_at)"
                 " VALUES (?,?,?,?,'published',?,?,?,?)",
                 (code, n, old["title"], old["text"], f"Rolled back to version {version}", user_id, stamp, stamp))
    _make_live(conn, code, old["title"], old["text"])
    conn.commit()
    return n


def forget(conn, code: str) -> None:
    """The rule itself was deleted, so its history goes with it."""
    conn.execute("DELETE FROM rule_versions WHERE rule_code=?", (code,))


_TOKEN = re.compile(r"\s+|[^\s]+")


def compare(conn, code: str, a: int, b: int) -> dict:
    """Word-level difference between two versions, as segments a person can read without diff notation."""
    _rule(conn, code)
    sync(conn, code)
    conn.commit()
    rows = {}
    for n in (a, b):
        r = conn.execute("SELECT version, title, text, status FROM rule_versions WHERE rule_code=? AND version=?", (code, n)).fetchone()
        if not r:
            raise NotFound(f"Version {n} does not exist")
        rows[n] = r
    x, y = _TOKEN.findall(rows[a]["text"]), _TOKEN.findall(rows[b]["text"])
    segments: list[dict] = []

    def add(op: str, tokens: list[str]) -> None:
        text = "".join(tokens)
        if not text:
            return
        if segments and segments[-1]["op"] == op:
            segments[-1]["text"] += text
        else:
            segments.append({"op": op, "text": text})

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, x, y, autojunk=False).get_opcodes():
        if tag == "equal":
            add("same", x[i1:i2])
        else:
            add("removed", x[i1:i2])
            add("added", y[j1:j2])
    return {"code": code, "from": {"version": a, "title": rows[a]["title"], "status": rows[a]["status"]},
            "to": {"version": b, "title": rows[b]["title"], "status": rows[b]["status"]},
            "title_changed": rows[a]["title"] != rows[b]["title"], "segments": segments,
            "identical": rows[a]["text"] == rows[b]["text"] and rows[a]["title"] == rows[b]["title"]}
