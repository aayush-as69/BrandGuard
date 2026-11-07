import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brandguard.app import create_app  # noqa: E402

NEHA, ARJUN, MEERA, IRA, RAHUL = 1, 2, 3, 4, 5  # seeded user ids


@pytest.fixture()
def app(tmp_path):
    return create_app(str(tmp_path / "test.db"))


@pytest.fixture()
def demo():
    return json.loads((ROOT / "seed" / "demo_email.json").read_text(encoding="utf-8"))


class Session:
    """A logged-in test client with small helpers."""

    def __init__(self, app, uid):
        self.c = app.test_client()
        self.c.post("/api/login", json={"user_id": uid})

    def get(self, url):
        return self.c.get(url)

    def post(self, url, **json_body):
        return self.c.post(url, json=json_body)


@pytest.fixture()
def login(app):
    return lambda uid: Session(app, uid)


@pytest.fixture()
def seeded(app, login):
    """Knowledge base loaded by the admin, plus Neha's demo email already submitted for review."""
    assert login(IRA).post("/api/kb/seed").status_code == 200
    return app
