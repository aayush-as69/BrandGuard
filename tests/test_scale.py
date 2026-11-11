import time

from conftest import NEHA

from brandguard import llm, retrieve


def test_pagination_and_total(seeded, login):
    n = login(NEHA)
    for i in range(5):
        n.post("/api/content", title=f"t{i}", body="Hello there.", images=[])
    r = n.get("/api/content?limit=2&offset=1")
    assert r.status_code == 200 and [c["title"] for c in r.get_json()] == ["t3", "t2"]
    assert r.headers["X-Total-Count"] == "5"
    assert n.get("/api/content?limit=abc").status_code == 400
    assert len(n.get("/api/content?limit=9999").get_json()) == 5


def test_bm25_index_is_cached():
    rules = {"R1": {"title": "Tone", "text": "Be warm and friendly"}, "R2": {"title": "Price", "text": "Quote prices in INR"}}
    retrieve._index.cache_clear()
    assert retrieve.top_rules("friendly tone", rules)[0] == "R1"
    assert retrieve.top_rules("price in inr", rules)[0] == "R2"
    info = retrieve._index.cache_info()
    assert info.misses == 1 and info.hits >= 1
    rules["R2"] = {"title": "Price", "text": "Quote prices in rupees"}  # an edited rule is never served stale
    assert retrieve.top_rules("inr", rules) == []


def test_ai_deadline_is_bounded(monkeypatch):
    class Slow:
        status_code = 503
        headers = {"retry-after": "30"}
        def raise_for_status(self): raise RuntimeError("503")
    import requests
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("BRANDGUARD_AI_TIMEOUT", "3")
    seen = []
    monkeypatch.setattr(requests, "post", lambda *a, **kw: (seen.append(kw["timeout"]), Slow())[1])
    t = time.monotonic()
    try:
        llm.default_call("s", "u", "m")
    except RuntimeError:
        pass
    assert time.monotonic() - t < 3 and len(seen) == 1  # a 30 s retry-after is not honoured past the deadline
    assert seen[0][1] <= 3
