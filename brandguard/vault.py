"""Encrypt small secrets (two-step sign-in keys) before they are stored.

The key comes from BRANDGUARD_DATA_KEY when set (preferred: it can be rotated on its own), otherwise from the session signing
secret. Anyone who copies the database file or a backup without that key cannot read the secrets. Values carry an "enc1:" prefix;
older plain values still read correctly and are re-encrypted the next time they are written."""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc1:"


def _fernet(fallback: str) -> Fernet:
    material = os.environ.get("BRANDGUARD_DATA_KEY") or fallback
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"brandguard-vault\0" + material.encode()).digest()))


def seal(value: str, fallback_key: str) -> str:
    return PREFIX + _fernet(fallback_key).encrypt(value.encode()).decode()


def unseal(stored: str | None, fallback_key: str) -> str | None:
    if not stored:
        return None
    if not stored.startswith(PREFIX):
        return stored  # written before encryption existed
    try:
        return _fernet(fallback_key).decrypt(stored[len(PREFIX):].encode()).decode()
    except InvalidToken:
        return None  # wrong key: treated as "no valid secret", never as a crash or a bypass
