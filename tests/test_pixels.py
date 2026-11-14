"""Measured image checks: palette, logo and text contrast come from real pixels, not typed-in colours."""
import io
import json

import pytest
from PIL import Image, ImageDraw

from brandguard import db as dbm, engine, kb as kbm, pixels
from conftest import RAHUL, ROOT

INK = {"ink": ["#3B2314", "#F4E9D8"]}


def banner(kind):
    return Image.open(ROOT / "seed" / f"sample-banner-{kind}.png").convert("RGB")


@pytest.fixture()
def conn(tmp_path):
    c = dbm.connect(str(tmp_path / "p.db"))
    dbm.init(c)
    kbm.seed_demo(c, ROOT / "seed")
    return c


def review(conn, kind, text="#3B2314", logo=True):
    m = pixels.measure(banner(kind), INK, text)
    img = {"name": f"{kind}.png", "alt": "Signature Blend banner", "text_color": text, "bg_color": "", "logo": logo, "measure": m}
    return engine.review(engine.load_kb(conn), "Hello, meet our new pouch.", [img]).findings


def test_on_brand_banner_passes_every_measured_check(conn):
    assert [f.source_id for f in review(conn, "ok")] == []


def test_off_brand_banner_breaks_palette_logo_and_contrast(conn):
    found = {f.source_id: f for f in review(conn, "bad", text="#C9B9A4")}
    assert set(found) == {"G-06", "G-08", "G-09"}
    assert "outside the brand palette" in found["G-08"].issue and "#2D9CFF" in found["G-08"].issue
    assert "of the image width" in found["G-09"].issue
    assert "measured at" in found["G-06"].issue


def test_measurements_are_real_pixel_numbers():
    ok = pixels.measure(banner("ok"), INK, "#3B2314")
    assert ok["logo"]["found"] and 300 <= ok["logo"]["w"] <= 360
    assert min(ok["logo"]["clear"].values()) >= 40
    assert ok["text"]["worst"]["ratio"] > 10
    bad = pixels.measure(banner("bad"), INK, "#C9B9A4")
    assert bad["logo"]["w"] < 140 and min(bad["logo"]["clear"].values()) < 15
    assert bad["text"]["worst"]["ratio"] < 2


def test_no_logo_is_reported_when_the_image_should_carry_one(conn):
    blank = Image.new("RGB", (900, 450), "#F4E9D8")
    ImageDraw.Draw(blank).rectangle((600, 300, 800, 400), fill="#B87333")
    assert pixels.measure(blank, INK)["logo"]["found"] is False
    img = {"name": "x.png", "alt": "A plain banner", "logo": True, "measure": pixels.measure(blank, INK)}
    out = engine.review(engine.load_kb(conn), "Hello there.", [img]).findings
    assert [f.source_id for f in out] == ["G-09"] and "not found" in out[0].issue


def test_logo_is_only_checked_when_the_author_says_the_image_has_one(conn):
    assert [f.source_id for f in review(conn, "bad", text="#3B2314", logo=False)] == ["G-08"]


def test_greys_and_brand_shades_are_not_off_palette(conn):
    grey = Image.new("RGB", (400, 200), "#808080")
    ImageDraw.Draw(grey).rectangle((0, 0, 200, 200), fill="#B87333")
    img = {"name": "g.png", "alt": "Grey and copper", "measure": pixels.measure(grey)}
    assert engine.review(engine.load_kb(conn), "Hello there.", [img]).findings == []


def test_without_a_measurement_the_old_typed_colour_check_still_works(conn):
    img = {"name": "h.png", "alt": "A hero image", "text_color": "#9A9A9A", "bg_color": "#FFFFFF"}
    out = engine.review(engine.load_kb(conn), "Hello there.", [img]).findings
    assert [f.source_id for f in out] == ["G-06"] and "measured" not in out[0].issue


# ---- through the API
def upload(client, kind, **form):
    data = (ROOT / "seed" / f"sample-banner-{kind}.png").read_bytes()
    return client.post("/api/image/analyze", data={"image": (io.BytesIO(data), f"{kind}.png"), **form},
                       content_type="multipart/form-data")


def test_api_reads_a_file_and_the_measurement_drives_the_review(seeded, login):
    rahul = login(RAHUL)
    r = upload(rahul.c, "bad").get_json()
    assert r["check_id"] and r["logo"] is True
    body = {"title": "Banner", "body": "Hello, meet our new pouch.", "use_ai": False,
            "images": [{"name": "bad.png", "alt": "Signature Blend banner", "text_color": r["text_color"], "bg_color": r["bg_color"],
                        "logo": True, "check_id": r["check_id"]}]}
    cid = rahul.post("/api/content", **body).get_json()["id"]
    detail = rahul.get(f"/api/content/{cid}").get_json()
    codes = {f["source_id"] for f in detail["findings"]}
    assert {"G-08", "G-09"} <= codes
    assert detail["images"][0]["check_id"] == r["check_id"] and detail["images"][0]["logo"] is True
    # a palette finding has no one-click fix: accepting it is refused, dismissing it is allowed
    pal = next(f for f in detail["findings"] if f["source_id"] == "G-08")
    assert rahul.post(f"/api/findings/{pal['id']}/decide", action="accept").status_code == 400


def test_someone_elses_measurement_cannot_be_attached(seeded, login):
    rahul, other = login(RAHUL), login(2)
    cid = upload(rahul.c, "ok").get_json()["check_id"]
    r = other.post("/api/content", title="T", body="Hello there.", use_ai=False,
                   images=[{"name": "a.png", "alt": "A banner image", "check_id": cid}])
    assert r.status_code == 400
    bad = rahul.post("/api/content", title="T", body="Hello there.", use_ai=False,
                     images=[{"name": "a.png", "alt": "A banner image", "check_id": "1; DROP"}])
    assert bad.status_code == 400


def test_api_rejects_a_non_image(app, login):
    rahul = login(RAHUL)
    r = rahul.c.post("/api/image/analyze", data={"image": (io.BytesIO(b"not an image"), "x.png")}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_sample_banners_are_served_to_signed_in_users(app, login):
    rahul = login(RAHUL)
    assert rahul.get("/api/image/sample/ok").status_code == 200
    assert rahul.get("/api/image/sample/nope").status_code == 404
    assert app.test_client().get("/api/image/sample/ok").status_code == 401
