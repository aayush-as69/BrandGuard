"""Deleting content on request, and what is kept afterwards (see docs/PRIVACY.md).

Deleting removes the content, its versions, findings, claims, comments, its audit entries and any AI log rows that name it.
It leaves one tombstone in the audit table (who deleted what, when, why) with no content in it, so the deletion itself is accountable."""
from __future__ import annotations

import sqlite3

from .db import now


def delete_content(conn: sqlite3.Connection, content_id: int, operator: str, reason: str) -> None:
    if not reason.strip():
        raise ValueError("A reason (for example the request reference) is required")
    row = conn.execute("SELECT id, title FROM content WHERE id=?", (content_id,)).fetchone()
    if not row:
        raise ValueError(f"No content with id {content_id}")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM llm_log WHERE content_id=?", (content_id,))
        conn.execute("DELETE FROM audit WHERE content_id=?", (content_id,))
        conn.execute("DELETE FROM content WHERE id=?", (content_id,))  # versions, findings, claims, comments cascade
        conn.execute("INSERT INTO audit(content_id, user_id, action, detail, created_at) VALUES (NULL, NULL, ?, ?, ?)",
                     ("content_deleted", f"content #{content_id} deleted by {operator}: {reason.strip()[:200]}", now()))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
