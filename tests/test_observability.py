from __future__ import annotations

from brandguard import db, metrics


def test_ai_observability_migration_adds_telemetry_columns(tmp_path):
    conn = db.connect(str(tmp_path / "bg.db"))
    db.init(conn, demo_users=False)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(llm_log)")}
    assert {"request_id", "provider", "latency_ms", "accepted", "discarded"} <= cols
    assert db.schema_version(conn) >= 8


def test_dashboard_metrics_are_read_only(tmp_path):
    conn = db.connect(str(tmp_path / "bg.db"))
    db.init(conn, demo_users=False)
    out = metrics.dashboard(conn)
    assert set(out) == {"reviews", "findings", "ai"}
    assert out["reviews"]["total"] == 0
    assert out["findings"]["total"] == 0
    assert out["ai"]["requests"] == 0


def test_dashboard_counts_ai_verification_metadata(tmp_path):
    conn = db.connect(str(tmp_path / "bg.db"))
    db.init(conn, demo_users=False)
    conn.execute(
        "INSERT INTO llm_log(content_id, version, model, payload, created_at, request_id, provider, "
        "latency_ms, accepted, discarded, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (None, 1, "test", "", "2026-11-14T00:00:00+00:00", "abc", "test-provider", 120.0, 2, 1, "used test"),
    )
    conn.commit()
    out = metrics.dashboard(conn)
    assert out["ai"]["requests"] == 1
    assert out["ai"]["successful"] == 1
    assert out["ai"]["accepted"] == 2
    assert out["ai"]["discarded"] == 1
    assert out["ai"]["avg_latency_ms"] == 120.0
