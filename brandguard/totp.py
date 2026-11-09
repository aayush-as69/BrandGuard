"""Time-based one-time passwords (RFC 6238), standard library only. Works with any authenticator app."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

STEP = 30


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    return f"{(struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 10**6:06d}"


def at(secret: str, now: float | None = None) -> str:
    return _code(secret, int((time.time() if now is None else now) // STEP))


def verify(secret: str, code: str, last_step: int = 0, now: float | None = None) -> int | None:
    """Return the time step the code belongs to, or None. One step of clock drift is allowed, and a step that
    was already used (last_step) is refused, so a code seen over a shoulder cannot be replayed."""
    code = "".join(ch for ch in str(code) if ch.isdigit())
    if len(code) != 6:
        return None
    current = int((time.time() if now is None else now) // STEP)
    for step in (current - 1, current, current + 1):
        if step > last_step and hmac.compare_digest(_code(secret, step), code):
            return step
    return None


def uri(secret: str, account: str, issuer: str = "BrandGuard") -> str:
    label = urllib.parse.quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={urllib.parse.quote(issuer)}&digits=6&period={STEP}"
