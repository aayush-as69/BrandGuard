"""Consistent, optionally encrypted backup and restore of the BrandGuard database.

    python scripts/backup.py backup  /data/brandguard.db  /backups/bg-2026-11-09.db.enc
    python scripts/backup.py restore /backups/bg-2026-11-09.db.enc  /data/brandguard.db

Set BRANDGUARD_BACKUP_KEY (a Fernet key: python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
to encrypt the backup file. Without it the backup is a plain SQLite file, so keep it somewhere protected.
Backups use SQLite's online backup API, so they are safe while the app is running. Restore with the app stopped.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path


def _fernet():
    key = os.environ.get("BRANDGUARD_BACKUP_KEY")
    if not key:
        return None
    from cryptography.fernet import Fernet
    return Fernet(key.encode())


def backup(db: str, out: str) -> None:
    if not Path(db).exists():
        raise SystemExit(f"No database at {db}")
    with tempfile.TemporaryDirectory() as tmp:
        copy = str(Path(tmp) / "copy.db")
        src, dst = sqlite3.connect(db), sqlite3.connect(copy)
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
        data = Path(copy).read_bytes()
    f = _fernet()
    Path(out).write_bytes(f.encrypt(data) if f else data)
    os.chmod(out, 0o600)
    print(f"Backed up {db} to {out}" + (" (encrypted)" if f else " (NOT encrypted)"))


def restore(src: str, db: str) -> None:
    data = Path(src).read_bytes()
    f = _fernet()
    if f:
        data = f.decrypt(data)
    elif not data.startswith(b"SQLite format 3"):
        raise SystemExit("This backup looks encrypted: set BRANDGUARD_BACKUP_KEY")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
        tmp.write(data)
    check = sqlite3.connect(tmp.name)
    try:
        ok = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if ok != "ok":
        os.unlink(tmp.name)
        raise SystemExit(f"Backup failed its integrity check: {ok}")
    for suffix in ("-wal", "-shm"):
        Path(db + suffix).unlink(missing_ok=True)
    Path(tmp.name).replace(db)
    print(f"Restored {src} to {db}")


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ("backup", "restore"):
        raise SystemExit(__doc__)
    (backup if sys.argv[1] == "backup" else restore)(sys.argv[2], sys.argv[3])
