"""Several OS processes write to one database at once, as gunicorn workers do."""
import subprocess
import sys
import textwrap
from pathlib import Path

from brandguard.app import create_app

ROOT = Path(__file__).resolve().parents[1]

WORKER = textwrap.dedent("""
    import sys
    from brandguard.app import create_app
    app = create_app(sys.argv[1])
    c = app.test_client()
    c.post("/api/login", json={"user_id": 1})
    bad = 0
    for i in range(15):
        r = c.post("/api/content", json={"title": f"p{sys.argv[2]}-{i}", "body": "Hello there. Welcome.", "images": []})
        bad += r.status_code != 201
    sys.exit(bad)
""")


def test_four_processes_write_concurrently(tmp_path):
    db = str(tmp_path / "m.db")
    create_app(db)  # first boot creates and migrates
    procs = [subprocess.Popen([sys.executable, "-c", WORKER, db, str(n)], cwd=ROOT) for n in range(4)]
    assert [p.wait(timeout=120) for p in procs] == [0, 0, 0, 0]
    c = create_app(db).test_client()
    c.post("/api/login", json={"user_id": 4})
    assert c.get("/api/content?limit=200").headers["X-Total-Count"] == "60"
    assert c.get("/healthz").get_json()["status"] == "ok"
