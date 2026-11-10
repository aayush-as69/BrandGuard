"""Failed-sign-in throttle shared by every worker process.

The counts live in the same SQLite database as everything else, so two gunicorn workers (or a restart) see the same
numbers. If the store cannot be read the answer is "refuse", never "allow": a broken throttle must not become an open door.
(On several machines the shared store would be your Postgres or Redis; the call sites here are the only thing to change.)"""
from __future__ import annotations

import logging
import sqlite3
import time

from .errors import RateLimited

WINDOW = 300.0   # seconds a failure counts for
LIMIT = 10       # failures allowed per client address inside the window
EMAIL_LIMIT = 40 # per target email: high enough that one attacker cannot lock a colleague out from a single address,
                 # low enough to bound a distributed guessing run (about 11,000 guesses a day per account)
log = logging.getLogger("brandguard.throttle")


def check(conn: sqlite3.Connection, *keys: str, now: float | None = None) -> None:
    """Raise RateLimited if any key already has LIMIT failures inside the window."""
    now = time.time() if now is None else now
    try:
        conn.execute("DELETE FROM login_failures WHERE at < ?", (now - WINDOW,))
        for key in keys:
            n = conn.execute("SELECT COUNT(*) FROM login_failures WHERE key=?", (key,)).fetchone()[0]
            if n >= (EMAIL_LIMIT if key.startswith("email:") else LIMIT):
                conn.commit()
                raise RateLimited("Too many failed attempts. Try again in a few minutes.")
        conn.commit()
    except sqlite3.Error:
        log.exception("sign-in throttle store unavailable; refusing the attempt")
        raise RateLimited("Sign-in is temporarily unavailable. Try again shortly.")


def record(conn: sqlite3.Connection, *keys: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    try:
        conn.executemany("INSERT INTO login_failures(key, at) VALUES (?,?)", [(k, now) for k in keys])
        conn.commit()
    except sqlite3.Error:
        log.exception("could not record a failed sign-in")
