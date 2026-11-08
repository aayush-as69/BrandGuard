"""Second code review: false positives, dismissal scope, size limits, imports."""
import io
import json

import pytest

from conftest import ARJUN, IRA, NEHA


@pytest.fixture()
def neha(seeded, login):
    return login(NEHA)


def review(neha, body, images=None):
    cid = neha.post("/api/content", title="t", body=body, images=images or []).get_json()["id"]
    return cid, neha.get(f"/api/content/{cid}").get_json()


def issues(d):
    return [(f["source_id"], f["span_text"], f["confidence"]) for f in d["findings"]]


# ---- 1. other amounts are not asserted to be wrong prices
def test_unrelated_amount_is_a_question_not_a_high_confidence_error(neha):
    _, d = review(neha, "Free delivery on orders above ₹999.")
    (f,) = d["findings"]
    assert f["confidence"] == "low" and f["needs_reviewer"] and f["suggested_fix"] is None
    assert not any(c["status"] == "contradicted" for c in d["claims"])


def test_named_product_price_is_still_a_confident_error(neha):
    _, d = review(neha, "Our 250g signature blend is ₹399.")
    f = next(x for x in d["findings"] if x["source_id"] == "F-01")
    assert f["confidence"] == "high" and f["suggested_fix"] == "₹449"


# ---- 4. currency/tax abbreviations are not shouting
def test_common_abbreviations_are_not_flagged_as_capitals(neha):
    _, d = review(neha, "Prices in INR include GST. See MRP on the pack.")
    assert d["findings"] == []


def test_real_shouting_is_still_flagged(neha):
    _, d = review(neha, "This is AMAZING coffee.")
    assert [f["span_text"] for f in d["findings"]] == ["AMAZING"]


# ---- 5. negation
def test_negated_contradiction_is_not_flagged(neha):
    assert review(neha, "This is not a light roast.")[1]["findings"] == []
    assert any(f["span_text"].lower() == "light roast" for f in review(neha, "A smooth light roast.")[1]["findings"])


# ---- 6. dates
def test_date_that_only_relates_to_the_launch_is_ignored(neha):
    assert review(neha, "3 March 2027, after the launch.")[1]["findings"] == []


def test_year_less_wrong_date_is_caught_and_right_one_passes(neha):
    _, bad = review(neha, "We launch on 20 December.")
    (f,) = bad["findings"]
    assert f["source_id"] == "F-02" and f["suggested_fix"] == "15 December"
    assert review(neha, "We launch on 15 December.")[1]["findings"] == []


# ---- 2. a dismissal covers that spot, not every identical word
def test_dismissal_does_not_cover_a_new_occurrence(neha):
    cid, d = review(neha, "Hi Dude, welcome.")
    fid = next(f["id"] for f in d["findings"] if f["span_text"] == "Dude")
    assert neha.post(f"/api/findings/{fid}/decide", action="dismiss", reason="friendly tone").status_code == 200
    neha.post(f"/api/content/{cid}/revise", body="Hi Dude, welcome.\n\nDude, a different paragraph added later.", images=[])
    got = neha.get(f"/api/content/{cid}").get_json()["findings"]
    by_start = {f["span_start"]: f for f in got if f["span_text"] == "Dude"}
    assert by_start[3]["decision"] == "dismissed"       # the one a person looked at
    assert by_start[19]["decision"] == "open"           # the new one nobody has seen


def test_dismissal_survives_an_unrelated_edit(neha):
    cid, d = review(neha, "Hi Dude, welcome. Our cheap beans.")
    dude = next(f["id"] for f in d["findings"] if f["span_text"] == "Dude")
    neha.post(f"/api/findings/{dude}/decide", action="dismiss", reason="friendly tone")
    cheap = next(f for f in neha.get(f"/api/content/{cid}").get_json()["findings"] if "cheap" in f["span_text"])
    neha.post(f"/api/findings/{cheap['id']}/decide", action="accept")
    d2 = neha.get(f"/api/content/{cid}").get_json()
    assert next(f for f in d2["findings"] if f["span_text"] == "Dude")["decision"] == "dismissed"


# ---- 3. size limits
def test_huge_content_stays_fast_and_response_small(neha):
    import time
    t = time.time()
    cid, d = review(neha, "#1 " * 16600)
    assert time.time() - t < 3
    assert len(d["findings"]) == 300
    assert d["review_meta"]["truncated"] == 16600 - 300
    assert len(json.dumps(d)) < 1_000_000
    assert all(len(c["text"]) <= 301 for c in d["claims"])


def test_cannot_submit_while_findings_are_hidden(neha):
    cid, _ = review(neha, "cheap " * 400)
    r = neha.post(f"/api/content/{cid}/submit")
    assert r.status_code == 400 and "not shown" in r.get_json()["error"]


def test_claims_are_not_repeated(neha):
    _, d = review(neha, "Dude, we are #1 coffee. " * 1)
    texts = [(c["text"], c["status"]) for c in d["claims"]]
    assert len(texts) == len(set(texts))


# ---- 8. BOM
def test_json_with_byte_order_mark_imports(app, login):
    ira = login(IRA)
    ira.post("/api/kb/seed")
    data = "﻿" + json.dumps([{"name": "Logo", "kind": "image"}])
    r = ira.c.post("/api/kb/import", data={"kind": "assets", "file": (io.BytesIO(data.encode("utf-8")), "a.json")},
                   content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()


# ---- 10. no leaked boot connection
def test_creating_the_app_does_not_leak_connections(tmp_path):
    import gc
    import warnings

    from brandguard.app import create_app
    with warnings.catch_warnings():
        warnings.simplefilter("error", ResourceWarning)
        create_app(str(tmp_path / "x.db"))
        gc.collect()
