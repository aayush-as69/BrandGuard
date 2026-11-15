"""Draw the synthetic Brewline logo and the sample banners used by the demo and the tests.

Run it only to regenerate the files in seed/ (they are committed). Needs Pillow and the DejaVu Sans Bold font.
Everything here is fictional: Brewline Coffee is an invented brand."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SEED = Path(__file__).resolve().parent.parent / "seed"
ESPRESSO, CREMA, COPPER = (0x3B, 0x23, 0x14), (0xF4, 0xE9, 0xD8), (0xB8, 0x73, 0x33)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def logo(ink=ESPRESSO, cut=CREMA) -> Image.Image:
    """A bean mark and the word 'Brewline' on a transparent background, 520 x 140."""
    img = Image.new("RGBA", (520, 140), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((10, 10, 130, 130), fill=ink + (255,))
    d.polygon([(40, 98), (52, 60), (78, 34), (100, 30), (92, 62), (66, 96), (50, 106)], fill=cut + (255,))
    d.text((150, 72), "Brewline", font=ImageFont.truetype(FONT, 70), fill=ink + (255,), anchor="lm")
    return img


def banner(size, bg, logo_width, logo_xy, text, text_colour, text_xy, blocks=()) -> Image.Image:
    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    for box, colour in blocks:
        d.rectangle(box, fill=colour)
    d.text(text_xy, text, font=ImageFont.truetype(FONT, 34), fill=text_colour)
    mark = logo().resize((logo_width, round(logo_width * 140 / 520)), Image.LANCZOS)
    img.paste(mark, logo_xy, mark)
    return img


if __name__ == "__main__":
    logo().save(SEED / "brewline-logo.png", optimize=True)
    # a banner that follows the guidelines
    banner((900, 450), CREMA, 360, (60, 60), "Signature Blend, now in a 250g pouch", ESPRESSO, (60, 300),
           blocks=[((640, 0, 900, 200), COPPER)]).save(SEED / "sample-banner-ok.png", optimize=True)
    # a banner that breaks three rules: a loud off-palette colour, a small logo with no room, pale text on cream
    banner((900, 450), CREMA, 120, (6, 6), "Signature Blend, now in a 250g pouch", (0xC9, 0xB9, 0xA4), (60, 300),
           blocks=[((520, 120, 900, 450), (0x2D, 0x9C, 0xFF)), ((520, 330, 900, 450), (0xFF, 0x3D, 0x8B))]
           ).save(SEED / "sample-banner-bad.png", optimize=True)
