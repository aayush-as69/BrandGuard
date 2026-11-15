"""Measure an uploaded image's real pixels, so visual rules can be checked with numbers.

Three measurements, all done on the pixels (Pillow and numpy, no machine learning):

  palette   which colours the image uses and how much of it each covers
  logo      whether the brand logo is present, its width in pixels, and the clear space on each side
  text      the contrast of text-coloured areas against the background directly behind each one

The measurements are stored as plain numbers. The rules engine compares them with the guideline settings, so a
change to a threshold needs no new upload.

Limits, stated plainly: the logo is found by its shape in its brand colours (primary or reverse), on a fairly plain
background; a busy photo behind the logo can hide it. Positions are accurate to a few pixels on images wider than
~800 px. Text is located by its colour (one text colour per image), not read, so it cannot tell text from any other
shape of that colour.
"""
from __future__ import annotations

import colorsys
import math
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from .engine import contrast_ratio

ROOT = Path(__file__).resolve().parent.parent
LOGO_REFERENCE = ROOT / "seed" / "brewline-logo.png"
WORK_MAX = 800             # the logo search runs on a copy no larger than this
MIN_IOU = 0.45             # how closely the shape must match to count as the logo
INK_TOLERANCE = 70         # RGB distance from the logo colour that still counts as logo ink
BG_TOLERANCE = 30          # RGB distance from the background that still counts as empty space
TEXT_TOLERANCE = 28        # RGB distance from the text colour that still counts as text
PALETTE_COLOURS = 24
MARK_SHARE = 0.23          # the left part of the logo that is the solid bean mark
MAX_INK_SHARE = 0.25        # a logo colour covering more of the image than this is the background
MIN_LOGO_W = 40            # a logo narrower than this (in the working copy) is too small to tell from stray marks


# ---------------------------------------------------------------------------- colour helpers
def rgb_of(hexcolour: str) -> tuple[int, int, int]:
    h = hexcolour.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def hex_of(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(round(c)) for c in rgb)


def _lab(rgb) -> tuple[float, float, float]:
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    x, y, z = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047, 0.2126 * r + 0.7152 * g + 0.0722 * b, \
              (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(a: str, b: str) -> float:
    """Distance between two colours as the eye sees it (CIE76). Around 2 is just noticeable; 18 is clearly different."""
    la, lb = _lab(rgb_of(a)), _lab(rgb_of(b))
    return math.dist(la, lb)


def is_neutral(hexcolour: str) -> bool:
    """White, black and greys: colours with almost no hue."""
    r, g, b = (c / 255 for c in rgb_of(hexcolour))
    return colorsys.rgb_to_hsv(r, g, b)[1] < 0.10


# ---------------------------------------------------------------------------- loading
def flatten(img: Image.Image) -> Image.Image:
    """RGB with transparent areas shown as white."""
    rgba = img.convert("RGBA")
    flat = Image.new("RGB", rgba.size, (255, 255, 255))
    flat.paste(rgba, mask=rgba.split()[3])
    return flat


# ---------------------------------------------------------------------------- palette
def palette(img: Image.Image) -> list[dict]:
    """The image's dominant colours with the share of the picture each covers (shares add up to 1)."""
    small = img.copy()
    small.thumbnail((400, 400))
    q = small.quantize(colors=PALETTE_COLOURS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = q.getpalette() or []
    counts = sorted(q.getcolors() or [], reverse=True)
    total = sum(c for c, _ in counts) or 1
    return [{"hex": hex_of(pal[i * 3:i * 3 + 3]), "share": round(c / total, 4)} for c, i in counts]


# ---------------------------------------------------------------------------- logo
def _reference() -> np.ndarray:
    """The logo's shape as a boolean mask cropped to its bounding box."""
    alpha = np.array(Image.open(LOGO_REFERENCE).convert("RGBA"))[:, :, 3] > 127
    ys, xs = np.where(alpha)
    return alpha[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _ink(arr: np.ndarray, rgb: tuple, tol: int) -> np.ndarray:
    diff = arr.astype(np.int32) - np.array(rgb, dtype=np.int32)
    return (diff * diff).sum(axis=2) <= tol * tol


def _search(ink: np.ndarray, shape: np.ndarray) -> Optional[tuple]:
    """Best match of `shape` (any size) in the boolean image `ink`: (iou, x, y, w, h) at the working size."""
    H, W = ink.shape
    th0, tw0 = shape.shape
    widths = sorted({int(w) for w in np.geomspace(MIN_LOGO_W, max(MIN_LOGO_W + 1, W * 0.95), 26)})
    templates = []
    for w in widths:
        h = max(3, round(w * th0 / tw0))
        if w > W or h > H:
            continue
        t = np.array(Image.fromarray((shape * 255).astype(np.uint8)).resize((w, h), Image.BOX)) > 70
        if t.sum() >= 80:
            templates.append(t)
    if not templates or ink.sum() < 80:
        return None
    hmax, wmax = max(t.shape[0] for t in templates), max(t.shape[1] for t in templates)
    ph, pw = H + hmax, W + wmax
    spectrum = np.fft.rfft2(ink.astype(np.float32), s=(ph, pw))
    integral = np.pad(ink.astype(np.int64).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    found = []
    for t in templates:
        h, w = t.shape
        over = np.fft.irfft2(spectrum * np.conj(np.fft.rfft2(t.astype(np.float32), s=(ph, pw))), s=(ph, pw))
        over = np.rint(over[:H - h + 1, :W - w + 1])
        win = (integral[h:H + 1, w:W + 1] - integral[:H - h + 1, w:W + 1]
               - integral[h:H + 1, :W - w + 1] + integral[:H - h + 1, :W - w + 1])
        iou = over / (t.sum() + win - over)
        iou = np.where(np.abs(win / t.sum() - 1) < 0.35, iou, 0)   # the window must hold about as much ink as the logo
        y, x = np.unravel_index(int(np.argmax(iou)), iou.shape)
        k = max(2, int(w * MARK_SHARE))
        left = integral[y + h, x + k] - integral[y, x + k] - integral[y + h, x] + integral[y, x]
        if abs(left / max(1, int(t[:, :k].sum())) - 1) > 0.3:    # the round bean mark on the left must be there too
            continue
        found.append((float(iou[y, x]), int(x), int(y), w, h))
    # a fragment of the mark can match well at a small size: prefer the largest size that is nearly as good
    if not found:
        return None
    top = max(f[0] for f in found)
    return max((f for f in found if f[0] >= max(MIN_IOU, 0.85 * top)), key=lambda f: f[3], default=max(found))


def _grow(ink: np.ndarray, box: list, reach: int) -> list:
    """Extend a box over logo ink that lies just beyond its edges (gaps up to a few pixels are bridged)."""
    x0, y0, x1, y1 = box
    H, W = ink.shape
    gap = max(5, (x1 - x0) // 16)
    for _ in range(max(0, reach)):
        moved = False
        if x0 > 0 and ink[y0:y1, max(0, x0 - gap):x0].any(): x0 -= 1; moved = True
        if x1 < W and ink[y0:y1, x1:x1 + gap].any(): x1 += 1; moved = True
        if y0 > 0 and ink[max(0, y0 - gap):y0, x0:x1].any(): y0 -= 1; moved = True
        if y1 < H and ink[y1:y1 + gap, x0:x1].any(): y1 += 1; moved = True
        if not moved:
            break
    return [x0, y0, x1, y1]


def find_logo(img: Image.Image, inks: list[str]) -> dict:
    """Locate the logo. Returns {"found": False} or its box in full-size pixels, with the colour variant that matched."""
    arr = np.array(img)
    H, W = arr.shape[:2]
    f = min(1.0, WORK_MAX / max(H, W))
    work = np.array(img.resize((max(1, round(W * f)), max(1, round(H * f))), Image.BOX)) if f < 1 else arr
    shape = _reference()
    best = None
    for colour in inks:
        mask = _ink(work, rgb_of(colour), INK_TOLERANCE)
        if mask.mean() > MAX_INK_SHARE:      # that colour is the background, not a logo
            continue
        hit = _search(mask, shape)
        if hit and (best is None or hit[0] > best[0][0]):
            best = (hit, colour)
    if not best or best[0][0] < MIN_IOU:
        return {"found": False, "score": round(best[0][0], 3) if best else 0.0}
    (iou, x, y, w, h), colour = best
    # refine on the full-size pixels, within a pixel or two of the match, so widths are measured, not guessed
    m = int(math.ceil(1 / f)) + 1
    x0, y0, x1, y1 = max(0, int(x / f) - m), max(0, int(y / f) - m), min(W, int((x + w) / f) + m), min(H, int((y + h) / f) + m)
    ys, xs = np.where(_ink(arr[y0:y1, x0:x1], rgb_of(colour), INK_TOLERANCE))
    box = [x0 + int(xs.min()), y0 + int(ys.min()), x0 + int(xs.max()) + 1, y0 + int(ys.max()) + 1] if len(xs) else None
    guess = [round(x / f), round(y / f), round((x + w) / f), round((y + h) / f)]
    if box:
        box = _grow(_ink(arr, rgb_of(colour), 2 * INK_TOLERANCE), box, int(0.2 * (box[2] - box[0])))
    if not box or abs((box[2] - box[0]) - (guess[2] - guess[0])) > 0.15 * (guess[2] - guess[0]):
        box = guess
    return {"found": True, "score": round(iou, 3), "ink": colour, "x": box[0], "y": box[1],
            "w": box[2] - box[0], "h": box[3] - box[1]}


def clear_space(arr: np.ndarray, box: dict) -> dict:
    """Empty space, in pixels, between the logo and the nearest other content on each side (or the image edge)."""
    H, W = arr.shape[:2]
    x0, y0, x1, y1 = box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"]
    cap = max(64, int(box["h"] * 1.5))

    def walk(limit: int, strip) -> int:
        limit = min(limit, cap)
        if limit <= 0:
            return 0
        probe = np.concatenate([strip(d).reshape(-1, 3) for d in range(3, min(limit, 5) + 1)] or [strip(1).reshape(-1, 3)])
        bg = np.median(probe, axis=0)
        free = 0
        for d in range(1, limit + 1):
            s = strip(d).reshape(-1, 3).astype(np.int32)
            near = ((s - bg) ** 2).sum(axis=1) <= BG_TOLERANCE ** 2
            if d > 3 and near.mean() < 0.98:   # the first strips are the logo's own anti-aliased edge
                break
            free = d
        return free

    return {"left": walk(x0, lambda d: arr[y0:y1, x0 - d]), "right": walk(W - x1, lambda d: arr[y0:y1, x1 + d - 1]),
            "top": walk(y0, lambda d: arr[y0 - d, x0:x1]), "bottom": walk(H - y1, lambda d: arr[y1 + d - 1, x0:x1])}


# ---------------------------------------------------------------------------- text contrast
def text_areas(arr: np.ndarray, text_hex: str) -> dict:
    """Find areas coloured like the text and measure each against the background just around it."""
    H, W = arr.shape[:2]
    tc = np.array(rgb_of(text_hex), dtype=np.int32)
    dist2 = ((arr.astype(np.int32) - tc) ** 2).sum(axis=2)
    is_text, is_other = dist2 <= TEXT_TOLERANCE ** 2, dist2 > 60 ** 2
    cell = max(8, round(max(H, W) / 60))
    gh, gw = math.ceil(H / cell), math.ceil(W / cell)
    ratio = np.full((gh, gw), np.nan)
    bgs: dict[tuple, str] = {}
    for gy in range(gh):
        for gx in range(gw):
            ys, xs = slice(gy * cell, (gy + 1) * cell), slice(gx * cell, (gx + 1) * cell)
            share = is_text[ys, xs].mean()
            if not 0.02 <= share <= 0.6:
                continue
            wy, wx = slice(max(0, (gy - 1) * cell), (gy + 2) * cell), slice(max(0, (gx - 1) * cell), (gx + 2) * cell)
            around = arr[wy, wx][is_other[wy, wx]]
            if len(around) < 0.2 * cell * cell:
                continue
            bg = hex_of(np.median(around, axis=0))
            r = contrast_ratio(text_hex, bg)
            if r is not None:
                ratio[gy, gx], bgs[(gy, gx)] = r, bg
    seen = np.zeros((gh, gw), dtype=bool)
    areas = []
    for gy in range(gh):
        for gx in range(gw):
            if np.isnan(ratio[gy, gx]) or seen[gy, gx]:
                continue
            stack, members = [(gy, gx)], []
            seen[gy, gx] = True
            while stack:
                cy, cx = stack.pop()
                members.append((cy, cx))
                for ny in range(cy - 1, cy + 2):
                    for nx in range(cx - 1, cx + 2):
                        if 0 <= ny < gh and 0 <= nx < gw and not seen[ny, nx] and not np.isnan(ratio[ny, nx]):
                            seen[ny, nx] = True
                            stack.append((ny, nx))
            worst = min(members, key=lambda m: ratio[m])
            ys_, xs_ = [m[0] for m in members], [m[1] for m in members]
            areas.append({"x": min(xs_) * cell, "y": min(ys_) * cell,
                          "w": min(W, (max(xs_) + 1) * cell) - min(xs_) * cell,
                          "h": min(H, (max(ys_) + 1) * cell) - min(ys_) * cell,
                          "ratio": round(float(ratio[worst]), 2), "bg": bgs[worst], "cells": len(members)})
    areas.sort(key=lambda a: -a["cells"])
    areas = areas[:20]
    return {"colour": hex_of(tc), "areas": areas, "worst": min(areas, key=lambda a: a["ratio"]) if areas else None}


# ---------------------------------------------------------------------------- the whole measurement
def measure(img: Image.Image, logo_cfg: Optional[dict] = None, text_hex: Optional[str] = None) -> dict:
    img = flatten(img)
    W, H = img.size
    out: dict = {"v": 1, "width": W, "height": H, "colours": palette(img), "logo": None, "text": None}
    arr = np.array(img)
    if logo_cfg is not None:
        logo = find_logo(img, logo_cfg.get("ink") or ["#3B2314"])
        if logo["found"]:
            logo["clear"] = clear_space(arr, logo)
        out["logo"] = logo
    if text_hex:
        out["text"] = text_areas(arr, text_hex)
    return out
