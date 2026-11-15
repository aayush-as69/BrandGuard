"""Read an uploaded image's pixels (Pillow): size, and an estimate of the background and text colours.

The estimate is the most common colour (background) and the common colour that contrasts most with it (text).
It is a starting point the author can correct, not text recognition."""
from __future__ import annotations

import io

from .engine import contrast_ratio

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 25_000_000


class ImageError(ValueError):
    pass


def analyse(data: bytes) -> dict:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - Pillow is a declared dependency
        raise ImageError("Image reading needs the Pillow package on the server") from exc
    if len(data) > MAX_BYTES:
        raise ImageError("That image is larger than 5 MB")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))
        width, height = img.size
        if width * height > MAX_PIXELS:  # check the declared size before decoding: a small file can unpack to gigabytes
            raise ImageError("That image has too many pixels (limit 25 million)")
        img = img.convert("RGBA")
    except ImageError:
        raise
    except Exception as exc:
        raise ImageError("That file is not an image this server can read (use PNG, JPEG, GIF or WebP)") from exc
    img.thumbnail((160, 160))
    flat = Image.new("RGB", img.size, (255, 255, 255))
    flat.paste(img, mask=img.split()[3])  # transparent areas read as white
    q = flat.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette = q.getpalette() or []
    counts = sorted(q.getcolors() or [], reverse=True)  # [(pixels, index)]
    total = sum(c for c, _ in counts) or 1
    colours = [(c / total, "#%02x%02x%02x" % tuple(palette[i * 3:i * 3 + 3])) for c, i in counts]
    background = colours[0][1]
    candidates = [(contrast_ratio(h, background) or 0, h) for share, h in colours[1:] if share >= 0.01]
    text = max(candidates)[1] if candidates else None
    return {"width": width, "height": height, "bg_color": background, "text_color": text,
            "note": "Colours are estimated from the pixels (most common colour and the one that contrasts most with it). "
                    "Check them before relying on the contrast result."}
