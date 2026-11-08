"""Guideline insights: which rules authors trip over, and which ones people dispute.

Counts come from what was actually decided, so they are evidence for the guideline owners, not a score for
any individual. Nothing here names a person."""
from __future__ import annotations

import datetime as dt
import sqlite3

DISPUTED_MIN_DECISIONS = 2   # need at least this many decisions before calling a rule "often disputed"
DISPUTED_RATE = 0.5


def _hours(a: str, b: str) -> float:
    return (dt.datetime.fromisoformat(b) - dt.datetime.fromisoformat(a)).total_seconds() / 3600


def compute(conn: sqlite3.Connection) -> dict:
    status = {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) n FROM content GROUP BY status")}

    # What authors wrote first: findings on version 1 of each piece (later versions are mostly fixes).
    flagged = {r["source_id"]: r["n"] for r in conn.execute(
        "SELECT source_id, COUNT(*) n FROM findings WHERE version=1 GROUP BY source_id")}
    # Real decisions only: a dismissal carried into a later version is not a new decision.
    decided = {}
    for r in conn.execute(
            "SELECT source_id, decision, COUNT(*) n FROM findings "
            "WHERE decision IN ('accepted','edited','dismissed') AND decision_reason NOT LIKE '(carried over)%' "
            "GROUP BY source_id, decision"):
        decided.setdefault(r["source_id"], {})[r["decision"]] = r["n"]

    titles = {r["code"]: r["title"] for r in conn.execute("SELECT code, title FROM rules")}
    titles.update({r["code"]: r["statement"] for r in conn.execute("SELECT code, statement FROM facts")})
    quotes = {r["source_id"]: r["source_quote"] for r in conn.execute(
        "SELECT source_id, source_quote FROM findings GROUP BY source_id")}

    rules = []
    for code in sorted(set(flagged) | set(decided)):
        d = decided.get(code, {})
        fixed, dismissed = d.get("accepted", 0) + d.get("edited", 0), d.get("dismissed", 0)
        total = fixed + dismissed
        rate = dismissed / total if total else 0.0
        rules.append({
            "code": code, "title": titles.get(code, code), "quote": quotes.get(code, ""),
            "flagged": flagged.get(code, 0), "fixed": fixed, "dismissed": dismissed,
            "dismissal_rate": round(rate, 2),
            "often_disputed": total >= DISPUTED_MIN_DECISIONS and rate >= DISPUTED_RATE,
        })
    rules.sort(key=lambda r: (-r["flagged"], r["code"]))

    # Time from "submitted" to "approved", per piece of content.
    hours = []
    for c in conn.execute("SELECT DISTINCT content_id FROM audit WHERE action='approved'"):
        rows = conn.execute(
            "SELECT action, created_at FROM audit WHERE content_id=? AND action IN ('submitted','approved') "
            "ORDER BY id", (c["content_id"],)).fetchall()
        sub = next((r["created_at"] for r in reversed(rows) if r["action"] == "submitted"), None)
        app_ = next((r["created_at"] for r in reversed(rows) if r["action"] == "approved"), None)
        if sub and app_:
            hours.append(max(0.0, _hours(sub, app_)))

    ai = {r["decision"]: r["n"] for r in conn.execute(
        "SELECT decision, COUNT(*) n FROM findings WHERE ai_generated=1 AND decision_reason NOT LIKE '(carried over)%' "
        "GROUP BY decision")}
    changes = conn.execute("SELECT COUNT(*) n FROM audit WHERE action='changes_requested'").fetchone()["n"]

    return {
        "content": {"total": sum(status.values()), **{k: status.get(k, 0) for k in
                    ("draft", "in_review", "changes_requested", "approved")}},
        "avg_hours_to_approve": round(sum(hours) / len(hours), 1) if hours else None,
        "changes_requested": changes,
        "rules": rules,
        "ai": {"suggested": sum(ai.values()), "accepted": ai.get("accepted", 0) + ai.get("edited", 0),
               "dismissed": ai.get("dismissed", 0)},
    }
