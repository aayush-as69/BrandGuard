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
AI_LIMIT = 30    # paid AI requests allowed per signed-in user inside WINDOW (BRANDGUARD_AI_RATE_LIMIT overrides)
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


def spend(conn: sqlite3.Connection, key: str, limit: int, now: float | None = None) -> None:
    """Count one use of a costly action against `key` and raise RateLimited once it has been used `limit` times
    inside the window (limit <= 0 means no cap). A refused attempt is not counted, so waiting always helps.
    Shares the table and the WINDOW with the sign-in counters; fails closed if the store cannot be used."""
    if limit <= 0:
        return
    now = time.time() if now is None else now
    try:
        conn.execute("DELETE FROM login_failures WHERE at < ?", (now - WINDOW,))
        row_id = conn.execute("INSERT INTO login_failures(key, at) VALUES (?,?)", (key, now)).lastrowid
        n = conn.execute("SELECT COUNT(*) FROM login_failures WHERE key=?", (key,)).fetchone()[0]
        if n > limit:
            conn.execute("DELETE FROM login_failures WHERE rowid=?", (row_id,))
        conn.commit()
    except sqlite3.Error:
        log.exception("AI request throttle store unavailable; refusing the request")
        raise RateLimited("AI requests are temporarily unavailable. Try again shortly.")
    if n > limit:
        raise RateLimited("Too many AI requests in a short time. Wait a few minutes, or switch AI review off for now.")
