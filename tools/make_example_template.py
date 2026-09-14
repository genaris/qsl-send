"""Generate the repo's example QSL template.

Produces a synthetic card at the exact size and field-box coordinates the
default config assumes, so the shipped example runs without anyone's real
card — and without photographs of real people.

    python tools/make_example_template.py [output.jpg]

Field boxes must stay in sync with DEFAULT_FIELDS in qsl_send/config.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qsl_send.config import DEFAULT_FIELDS, DEFAULT_TEMPLATE_SIZE  # noqa: E402

WIDTH, HEIGHT = DEFAULT_TEMPLATE_SIZE  # 1583 x 1061

# Sampled from the reference card so generated text keeps the same contrast.
# Saturated flat fill, matching how real QSL cards mark write-in areas — this
# is what qsl_send.detect looks for, so the shipped example is detectable too.
BOX_FILL = (0, 175, 240)
BOX_EDGE = (10, 70, 110)
LABEL = (222, 240, 252)
ACCENT = (127, 201, 240)
PALE = (232, 244, 252)

SKY_TOP = (10, 42, 78)
SKY_BOTTOM = (32, 122, 176)
GROUND = (28, 78, 96)

_BOLD = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
_REGULAR = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in _BOLD if bold else _REGULAR:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def background() -> Image.Image:
    """An abstract sky-over-hills scene — no photographs, no people."""
    img = Image.new("RGB", (WIDTH, HEIGHT), SKY_TOP)
    draw = ImageDraw.Draw(img)

    horizon = int(HEIGHT * 0.62)
    for y in range(horizon):
        t = y / horizon
        draw.line(
            [(0, y), (WIDTH, y)],
            fill=tuple(round(a + (b - a) * t) for a, b in zip(SKY_TOP, SKY_BOTTOM)),
        )
    for y in range(horizon, HEIGHT):
        t = (y - horizon) / max(1, HEIGHT - horizon)
        draw.line(
            [(0, y), (WIDTH, y)],
            fill=tuple(round(a + (b - a) * t) for a, b in zip(SKY_BOTTOM, GROUND)),
        )

    # Sun and a few soft bands, blurred so nothing reads as a real photo.
    glow = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([1180, 120, 1420, 360], fill=(120, 170, 200))
    for i, y in enumerate(range(140, horizon, 90)):
        gd.ellipse([-300 + i * 120, y, 700 + i * 220, y + 60], fill=(40, 70, 95))
    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(70)), 0.55)

    draw = ImageDraw.Draw(img)
    # Rolling hills along the horizon, back to front.
    hills = [
        ((26, 92, 116), horizon - 30, [(0, 40), (340, -35), (700, 25), (1080, -30), (1583, 30)]),
        ((22, 70, 92), horizon + 35, [(0, 30), (420, -25), (900, 35), (1300, -15), (1583, 25)]),
        ((18, 55, 72), horizon + 110, [(0, 20), (500, -20), (1000, 25), (1583, -10)]),
    ]
    for colour, base, points in hills:
        draw.polygon(
            [(-50, HEIGHT)] + [(x, base + dy) for x, dy in points] + [(WIDTH + 50, HEIGHT)],
            fill=colour,
        )

    # A simple antenna mast, the one recognisably "radio" element.
    mast_x = 1290
    draw.line([(mast_x, horizon + 40), (mast_x, 300)], fill=(16, 48, 66), width=7)
    for i, y in enumerate(range(320, horizon + 30, 70)):
        half = 20 + i * 9
        draw.line([(mast_x - half, y), (mast_x + half, y)], fill=(16, 48, 66), width=5)
    for dy, half in ((250, 120), (215, 95), (180, 70)):
        draw.line(
            [(mast_x - half, 300 + (250 - dy)), (mast_x + half, 300 + (250 - dy))],
            fill=(16, 48, 66),
            width=5,
        )
    return img


def draw_text(draw, xy, text, f, fill, shadow=(6, 22, 38), offset=2):
    x, y = xy
    if shadow:
        draw.text((x + offset, y + offset), text, font=f, fill=shadow)
    draw.text((x, y), text, font=f, fill=fill)


def text_size(f: ImageFont.FreeTypeFont, text: str) -> tuple[int, int]:
    left, top, right, bottom = f.getbbox(text)
    return right - left, bottom - top


def vertical_text(img, right_x, top_y, text, f, fill):
    """Draw `text` reading bottom-to-top, its right edge at `right_x`."""
    w, h = text_size(f, text)
    tmp = Image.new("RGBA", (w + 20, h + 20), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text((0, 0), text, font=f, fill=fill)
    rotated = tmp.rotate(90, expand=True)
    img.paste(rotated, (right_x - rotated.width, top_y), rotated)


def build() -> Image.Image:
    img = background()
    draw = ImageDraw.Draw(img)

    # --- header -------------------------------------------------------
    call_font = font(150, True)
    call_w, _ = text_size(call_font, "MY1CLL")
    draw_text(draw, (58, 8), "MY1CLL", call_font, ACCENT, offset=4)
    # Suffix and operator name sit clear of the callsign, never over it.
    draw_text(draw, (58 + call_w + 12, 96), "/A", font(74, True), PALE)
    draw_text(draw, (58 + call_w + 16, 172), "EXAMPLE", font(38, True), (160, 198, 232))
    draw_text(draw, (62, 176), "FT-0000", font(34), (170, 205, 235))

    draw_text(draw, (880, 26), "Sample Field Activity", font(50, True), PALE)
    draw_text(draw, (1010, 88), "QRA Loc.:", font(30), LABEL)
    draw_text(draw, (990, 118), "AA00AA00", font(42, True), PALE)
    draw_text(draw, (1352, 88), "CQ 00", font(30, True), LABEL)
    draw_text(draw, (1348, 118), "ITU 00", font(30, True), LABEL)

    # Station badge, standing in for a club logo.
    draw.ellipse([1432, 18, 1562, 148], fill=(18, 58, 84), outline=ACCENT, width=4)
    draw_text(draw, (1452, 58), "MY1CLL", font(26, True), PALE, shadow=None)
    draw_text(draw, (1466, 88), "EXAMPLE", font(17), LABEL, shadow=None)

    # --- left block ---------------------------------------------------
    draw_text(draw, (105, 726), "Reference XX-00", font(30), (185, 215, 240))
    draw_text(draw, (100, 752), "Example Station", font(76, True), ACCENT, offset=3)
    draw_text(draw, (152, 820), "Sample Location", font(52, True), PALE, offset=3)
    draw_text(draw, (105, 878), "Thanks for the Contact", font(38), PALE)

    vertical_text(
        img, WIDTH - 14, 300, "Replace with your own QSL design",
        font(26), (200, 226, 245),
    )

    # --- the seven field boxes ---------------------------------------
    labels = {
        "date": "DATE",
        "qso_with": "QSO with",
        "name": "Name",
        "qrg": "QRG",
        "utc": "UTC",
        "mode": "Mode",
        "rst": "R-S-T",
    }
    label_font = font(24, True)
    for spec in DEFAULT_FIELDS:
        x, y, w, h = spec["box"]
        draw.rectangle([x, y, x + w, y + h], fill=BOX_FILL, outline=BOX_EDGE, width=2)
        # Centre each label over its box, so the two narrow ones at the right
        # (MODO, R-S-T) cannot collide.
        text = labels[spec["name"]]
        lw, _ = text_size(label_font, text)
        draw_text(draw, (x + (w - lw) / 2, y - 32), text, label_font, LABEL)
    return img


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("template.jpg")
    img = build()
    img.save(out, "JPEG", quality=92, subsampling=1, dpi=(300, 300))
    print(f"wrote {out} ({img.width}x{img.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
