import io

import pytest

PIL = pytest.importorskip("PIL.Image")

from conftest import NEHA, Session  # noqa: E402


def _png(bg, fg, size=(120, 60)):
    img = PIL.new("RGB", size, bg)
    for x in range(20, 100):
        for y in range(20, 40):
            img.putpixel((x, y), fg)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _post(app, data, name="b.png"):
    n = Session(app, NEHA)
    return n.c.post("/api/image/analyze", data={"image": (io.BytesIO(data), name)}, content_type="multipart/form-data")


def test_reads_size_and_colours_from_pixels(app):
    r = _post(app, _png((255, 255, 255), (0, 0, 0)))
    j = r.get_json()
    assert r.status_code == 200 and (j["width"], j["height"]) == (120, 60)
    assert j["bg_color"] == "#ffffff" and j["text_color"] == "#000000"


def test_low_contrast_pixels_are_reported(app):
    j = _post(app, _png((200, 200, 200), (190, 190, 190))).get_json()
    from brandguard.engine import contrast_ratio
    assert contrast_ratio(j["text_color"], j["bg_color"]) < 4.5


def test_rejects_non_images_and_needs_sign_in(app):
    assert _post(app, b"this is not an image").status_code == 400
    assert app.test_client().post("/api/image/analyze").status_code == 401
    assert Session(app, NEHA).c.post("/api/image/analyze", data={}).status_code == 400
