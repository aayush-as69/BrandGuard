"""Delete one piece of content (and everything hanging off it) on request.

    python scripts/delete_content.py /data/brandguard.db 42 "ticket DSR-118" "ops@example.com"

Take a backup first (scripts/backup.py). Older backups still contain the content until they expire: see docs/PRIVACY.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brandguard import db, retention  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit(__doc__)
    conn = db.connect(sys.argv[1])
    retention.delete_content(conn, int(sys.argv[2]), sys.argv[4], sys.argv[3])
    print(f"Deleted content #{sys.argv[2]}")
