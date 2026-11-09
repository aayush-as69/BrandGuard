import json

import pytest
from conftest import NEHA


@pytest.fixture()
def client(app):
    return app.test_client()


def test_cross_origin_write_refused(client):
    r = client.post("/api/login", json={"user_id": NEHA}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_null_origin_and_cross_site_fetch_refused(client):
    assert client.post("/api/login", json={"user_id": NEHA}, headers={"Origin": "null"}).status_code == 403
    assert client.post("/api/login", json={"user_id": NEHA},
                       headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_same_origin_and_no_origin_allowed(client):
    assert client.post("/api/login", json={"user_id": NEHA}, headers={"Origin": "http://localhost"}).status_code != 403
    assert client.post("/api/login", json={"user_id": NEHA}).status_code != 403


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json["status"] == "ok" and r.json["schema_version"] >= 4


def test_json_log_has_no_content(client, monkeypatch, capsys):
    monkeypatch.setenv("BRANDGUARD_LOG_JSON", "1")
    client.post("/api/login", json={"user_id": NEHA, "secret": "SECRET-VALUE"})
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["path"] == "/api/login" and "SECRET-VALUE" not in json.dumps(line)
