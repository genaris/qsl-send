"""Find the blank field boxes in a QSL template automatically.

Most QSL cards leave the write-in areas as flat rectangles of one solid
colour. This locates those rectangles so the box coordinates need not be
measured by hand in an image editor.

The approach is entirely local — no network, no image-recognition service:

1. Histogram the colours in the lower part of the card (where field boxes
   almost always live) to get a shortlist of candidate flat colours.
2. For each candidate, mask matching pixels and group them into connected
   rectangles, keeping those whose size looks like a write-in box.
3. Score each candidate by how many box-like rectangles it yields, not by how
   many pixels it covers — a large flat background can easily outnumber seven
   small boxes, so raw pixel count picks the wrong colour.
4. Sort the winner's boxes into rows (top to bottom), then left to right
   within each row — the order a person reads the card.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass
class DetectedBox:
    x: int
    y: int
    width: int
    height: int
    row: int = 0

    @property
    def box(self) -> list[int]:
        return [self.x, self.y, self.width, self.height]

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass
class Detection:
    boxes: list[DetectedBox]
    colour: tuple[int, int, int]
    size: tuple[int, int]
    rows: int


def _quantise(c: tuple[int, int, int], step: int = 8) -> tuple[int, int, int]:
    return tuple((v // step) * step for v in c)  # type: ignore[return-value]


def _candidate_colours(
    img: Image.Image, search_top: float, min_saturation: int, limit: int
) -> list[tuple[int, int, int]]:
    """Shortlist of flat colours in the lower band, most common first."""
    w, h = img.size
    px = img.load()
    y0 = int(h * search_top)
    buckets: Counter = Counter()
    for y in range(y0, h, 2):
        for x in range(0, w, 2):
            c = px[x, y]
            # Skip near-greys: write-in boxes are tinted, and this cheaply
            # discards most photographic and paper-white regions.
            if max(c) - min(c) < min_saturation:
                continue
            buckets[_quantise(c)] += 1
    if not buckets:
        return []

    # Refine each shortlisted bucket to the exact modal colour inside it, so
    # the mask is centred on the real fill rather than a quantisation edge.
    top = [b for b, _ in buckets.most_common(limit)]
    exact: dict[tuple[int, int, int], Counter] = {b: Counter() for b in top}
    wanted = set(top)
    for y in range(y0, h, 2):
        for x in range(0, w, 2):
            c = px[x, y]
            q = _quantise(c)
            if q in wanted:
                exact[q][c] += 1
    return [counter.most_common(1)[0][0] for counter in exact.values() if counter]


def _mask(img: Image.Image, colour: tuple[int, int, int], tol: int) -> list[list[bool]]:
    w, h = img.size
    px = img.load()
    cr, cg, cb = colour
    return [
        [
            abs(px[x, y][0] - cr) <= tol
            and abs(px[x, y][1] - cg) <= tol
            and abs(px[x, y][2] - cb) <= tol
            for x in range(w)
        ]
        for y in range(h)
    ]


def _components(mask: list[list[bool]], min_w: int, min_h: int) -> list[DetectedBox]:
    """Connected-component labelling, iterative so deep runs cannot recurse."""
    h = len(mask)
    w = len(mask[0]) if h else 0
    seen = [[False] * w for _ in range(h)]
    out: list[DetectedBox] = []

    for sy in range(h):
        row_mask = mask[sy]
        row_seen = seen[sy]
        for sx in range(w):
            if not row_mask[sx] or row_seen[sx]:
                continue
            stack = [(sx, sy)]
            row_seen[sx] = True
            x0 = x1 = sx
            y0 = y1 = sy
            n = 0
            while stack:
                x, y = stack.pop()
                n += 1
                if x < x0:
                    x0 = x
                if x > x1:
                    x1 = x
                if y < y0:
                    y0 = y
                if y > y1:
                    y1 = y
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((nx, ny))

            bw, bh = x1 - x0 + 1, y1 - y0 + 1
            if bw < min_w or bh < min_h:
                continue
            # A write-in box is a filled rectangle: most of its bounding box
            # should actually be the box colour. This rejects text and logos.
            if n < 0.75 * bw * bh:
                continue
            out.append(DetectedBox(x0, y0, bw, bh))
    return out


def _assign_rows(boxes: list[DetectedBox]) -> int:
    """Group boxes into rows by vertical overlap, then order left to right."""
    if not boxes:
        return 0
    boxes.sort(key=lambda b: (b.y, b.x))
    row = 0
    row_top = boxes[0].y
    row_bottom = boxes[0].y + boxes[0].height
    for b in boxes:
        # A new row starts when a box sits clear of the current row's band.
        if b.y > row_bottom - max(4, b.height // 3):
            row += 1
            row_top, row_bottom = b.y, b.y + b.height
        else:
            row_top = min(row_top, b.y)
            row_bottom = max(row_bottom, b.y + b.height)
        b.row = row
    boxes.sort(key=lambda b: (b.row, b.x))
    return row + 1


# Reading order on a QSL card: the order these fields are printed in. Used to
# name detected boxes, since geometry alone cannot say which box is which.
# Width the candidate-colour scoring pass is downscaled to. Only affects
# which colour is chosen, never the reported coordinates.
_SCORE_WIDTH = 400

DEFAULT_ORDER = ["fecha", "qso_con", "nombre", "qrg", "utc", "modo", "rst"]

# What each positional name should print, as a value template.
DEFAULT_VALUES = {
    "fecha": "{date}",
    "qso_con": "{callsign}",
    "nombre": "{name_title}",
    "qrg": "{qrg}",
    "utc": "{utc}",
    "modo": "{mode}",
    "rst": "{rst}",
}


def _boxes_for_colour(
    img: Image.Image,
    colour: tuple[int, int, int],
    tolerance: int,
    min_width: int,
    min_height: int,
    search_top: float,
) -> list[DetectedBox]:
    boxes = _components(_mask(img, colour, tolerance), min_width, min_height)

    # Only accept boxes inside the band we searched. The same colour often
    # appears in header artwork (a sliver of the callsign, a logo), and those
    # are never write-in fields.
    cutoff = int(img.size[1] * search_top)
    boxes = [b for b in boxes if b.y >= cutoff]

    # Drop specks: anything far smaller than the median real box.
    if boxes:
        median = sorted(b.area for b in boxes)[len(boxes) // 2]
        boxes = [b for b in boxes if b.area >= median * 0.15]
    return boxes


def detect_boxes(
    path: str | Path,
    *,
    search_top: float = 0.55,
    tolerance: int = 26,
    min_width: int = 40,
    min_height: int = 18,
    min_saturation: int = 25,
    colour: tuple[int, int, int] | None = None,
    candidates: int = 6,
) -> Detection:
    """Locate the blank field boxes in a QSL template image."""
    img = Image.open(path).convert("RGB")

    if colour is not None:
        shortlist = [colour]
    else:
        shortlist = _candidate_colours(img, search_top, min_saturation, candidates)
    if not shortlist:
        return Detection([], (0, 0, 0), img.size, 0)

    # Pick the colour that yields the most box-like rectangles. Scoring by
    # rectangle count rather than pixel count is what stops a large flat
    # background from outvoting seven small field boxes.
    #
    # Scoring only decides WHICH colour wins, so it runs on a downscaled copy —
    # masking and labelling every candidate at full resolution is the dominant
    # cost. The winner is then re-detected at full size, so the coordinates
    # handed back are pixel-exact.
    if len(shortlist) == 1:
        best_colour = shortlist[0]
    else:
        scale = min(1.0, _SCORE_WIDTH / img.width)
        if scale < 1.0:
            small = img.resize(
                (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                Image.NEAREST,
            )
            # Size thresholds must shrink with the image or nothing qualifies.
            s_min_w = max(4, round(min_width * scale))
            s_min_h = max(3, round(min_height * scale))
        else:
            small, s_min_w, s_min_h = img, min_width, min_height

        best_colour = shortlist[0]
        best_score = -1
        for cand in shortlist:
            score = len(
                _boxes_for_colour(
                    small, cand, tolerance, s_min_w, s_min_h, search_top
                )
            )
            if score > best_score:
                best_score, best_colour = score, cand

    best = _boxes_for_colour(
        img, best_colour, tolerance, min_width, min_height, search_top
    )
    rows = _assign_rows(best)
    return Detection(best, best_colour, img.size, rows)


def name_boxes(
    detection: Detection, order: list[str] | None = None
) -> list[tuple[DetectedBox, str, str]]:
    """Pair each detected box with a field name and value, by reading order.

    Returns (box, name, value). Names beyond the known order fall back to
    field8, field9, ... with an empty value for you to fill in.
    """
    names = order or DEFAULT_ORDER
    out = []
    for i, b in enumerate(detection.boxes):
        if i < len(names):
            name = names[i]
            value = DEFAULT_VALUES.get(name, "")
        else:
            name = f"field{i + 1}"
            value = ""
        out.append((b, name, value))
    return out
