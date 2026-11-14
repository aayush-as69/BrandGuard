"""Small, database-backed operational metrics for the BrandGuard admin surface.

The module intentionally stays read-only. It gives the UI a compact view of review volume,
finding health, and AI request performance without exposing prompt/content payloads.
"""
from __future__ import annotations

import sqlite3


def dashboard(conn: sqlite3.Connection) -> dict:
    reviews = conn.execute(
        """SELECT
             COUNT(*) AS total,
             SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) AS approved,
             SUM(CASE WHEN status='in_review' THEN 1 ELSE 0 END) AS in_review,
             SUM(CASE WHEN status IN ('draft','changes_requested') THEN 1 ELSE 0 END) AS needs_work
           FROM content"""
    ).fetchone()

    findings = conn.execute(
        """SELECT
             COUNT(*) AS total,
             SUM(CASE WHEN decision='open' THEN 1 ELSE 0 END) AS open,
             SUM(CASE WHEN decision='accepted' THEN 1 ELSE 0 END) AS accepted,
             SUM(CASE WHEN decision='edited' THEN 1 ELSE 0 END) AS edited,
             SUM(CASE WHEN decision='dismissed' THEN 1 ELSE 0 END) AS dismissed
           FROM findings"""
    ).fetchone()

    ai = conn.execute(
        """SELECT
             COUNT(*) AS requests,
             SUM(CASE WHEN status LIKE 'used%' THEN 1 ELSE 0 END) AS successful,
             SUM(CASE WHEN status LIKE 'failed%' THEN 1 ELSE 0 END) AS failed,
             AVG(CASE WHEN latency_ms > 0 THEN latency_ms END) AS avg_latency_ms,
             SUM(COALESCE(accepted, 0)) AS accepted,
             SUM(COALESCE(discarded, 0)) AS discarded
           FROM llm_log"""
    ).fetchone()

    def clean(row):
        return {k: row[k] for k in row.keys()}

    return {
        "reviews": clean(reviews),
        "findings": clean(findings),
        "ai": clean(ai),
    }
