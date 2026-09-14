"""Tests for automatic field-box detection.

Every fixture is a synthetic card drawn here. The real QSL templates are
git-ignored (they carry photographs of identifiable people), so the suite must
not depend on them.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qsl_send.detect import (  # noqa: E402
    DEFAULT_ORDER,
    detect_boxes,
    name_boxes,
)

FILL = (0, 175, 240)  # saturated cyan, as real cards use
SIZE = (1600, 1060)

# A single row of seven boxes near the bottom, in the proportions a QSL card
# uses: two medium, one wide (the name), two medium, two narrow.
ONE_ROW = [
    (100, 950, 174, 41),
    (290, 950, 174, 41),
    (480, 950, 293, 41),
    (790, 950, 152, 41),
    (960, 950, 152, 41),
    (1130, 950, 71, 41),
    (1220, 950, 71, 41),
]

# The same seven fields split across two rows, as the DPS-02 card does.
TWO_ROWS = [
    (100, 860, 174, 41),
    (290, 860, 174, 41),
    (100, 930, 293, 41),
    (410, 930, 152, 41),
    (580, 930, 152, 41),
    (750, 930, 71, 41),
    (840, 930, 71, 41),
]


def _card(
    path: Path,
    boxes,
    *,
    background=(120, 130, 140),
    fill=FILL,
    size=SIZE,
    extra=None,
) -> Path:
    """Draw a synthetic QSL card with `boxes` as flat filled rectangles."""
    img = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(img)
    for x, y, w, h in boxes:
        draw.rectangle([x, y, x + w, y + h], fill=fill)
    if extra:
        for rect, colour in extra:
            x, y, w, h = rect
            draw.rectangle([x, y, x + w, y + h], fill=colour)
    img.save(path, "JPEG", quality=95, subsampling=0)
    return path


def test_finds_every_box_in_a_single_row(tmp_path):
    d = detect_boxes(_card(tmp_path / "c.jpg", ONE_ROW))
    assert len(d.boxes) == 7
    assert d.rows == 1
    assert d.size == SIZE


def test_reports_the_fill_colour_it_locked_onto(tmp_path):
    d = detect_boxes(_card(tmp_path / "c.jpg", ONE_ROW))
    # JPEG is lossy, so allow a small drift from the exact drawn colour.
    assert all(abs(a - b) <= 6 for a, b in zip(d.colour, FILL))


def test_box_coordinates_match_what_was_drawn(tmp_path):
    d = detect_boxes(_card(tmp_path / "c.jpg", ONE_ROW))
    for found, drawn in zip(d.boxes, ONE_ROW):
        fx, fy, fw, fh = found.box
        dx, dy, dw, dh = drawn
        # Within a couple of pixels: JPEG softens the rectangle edges.
        assert abs(fx - dx) <= 3 and abs(fy - dy) <= 3
        assert abs(fw - dw) <= 4 and abs(fh - dh) <= 4


def test_boxes_come_back_in_left_to_right_reading_order(tmp_path):
    d = detect_boxes(_card(tmp_path / "c.jpg", ONE_ROW))
    xs = [b.x for b in d.boxes]
    assert xs == sorted(xs)


def test_two_row_layout_is_split_into_rows(tmp_path):
    d = detect_boxes(_card(tmp_path / "c.jpg", TWO_ROWS))
    assert len(d.boxes) == 7
    assert d.rows == 2
    assert [b.row for b in d.boxes] == [0, 0, 1, 1, 1, 1, 1]


def test_two_row_layout_reads_row_by_row_not_by_column(tmp_path):
    # Reading order must be row 1 left-to-right, then row 2 left-to-right —
    # not a single x-sort, which would interleave the two rows.
    d = detect_boxes(_card(tmp_path / "c.jpg", TWO_ROWS))
    assert [b.box[:2] for b in d.boxes][:3] == [
        list(TWO_ROWS[0][:2]),
        list(TWO_ROWS[1][:2]),
        list(TWO_ROWS[2][:2]),
    ]


def test_a_large_flat_background_does_not_outvote_the_boxes(tmp_path):
    # The regression this guards: scoring candidate colours by pixel count
    # picks the background, because one big region beats seven small ones.
    # Scoring by how many box-shaped rectangles a colour yields fixes it.
    path = _card(
        tmp_path / "c.jpg",
        ONE_ROW,
        background=(20, 90, 150),  # saturated, and far larger than the boxes
    )
    d = detect_boxes(path)
    assert len(d.boxes) == 7
    assert all(abs(a - b) <= 6 for a, b in zip(d.colour, FILL))


def test_header_artwork_in_the_box_colour_is_ignored(tmp_path):
    # Real cards often use the box colour in the callsign artwork up top.
    # Only shapes below search_top may count as fields.
    path = _card(
        tmp_path / "c.jpg",
        ONE_ROW,
        extra=[((53, 54, 45, 120), FILL)],  # a sliver high on the card
    )
    d = detect_boxes(path)
    assert len(d.boxes) == 7
    assert all(b.y > SIZE[1] * 0.55 for b in d.boxes)


def test_search_top_can_be_lowered_to_reach_higher_boxes(tmp_path):
    # A card whose fields sit above the default 55% cutoff.
    high = [(100, 300, 174, 41), (290, 300, 174, 41), (480, 300, 293, 41)]
    path = _card(tmp_path / "c.jpg", high)
    assert detect_boxes(path).boxes == []
    assert len(detect_boxes(path, search_top=0.2).boxes) == 3


def test_forcing_a_colour_skips_detection(tmp_path):
    path = _card(tmp_path / "c.jpg", ONE_ROW)
    d = detect_boxes(path, colour=FILL)
    assert len(d.boxes) == 7
    assert d.colour == FILL


def test_a_card_with_no_flat_boxes_detects_nothing(tmp_path):
    path = tmp_path / "plain.jpg"
    Image.new("RGB", SIZE, (128, 128, 128)).save(path, "JPEG")
    d = detect_boxes(path)
    assert d.boxes == []
    assert d.rows == 0


def test_names_follow_reading_order(tmp_path):
    d = detect_boxes(_card(tmp_path / "c.jpg", ONE_ROW))
    assert [n for _b, n, _v in name_boxes(d)] == DEFAULT_ORDER


def test_names_carry_the_matching_value_template(tmp_path):
    d = detect_boxes(_card(tmp_path / "c.jpg", ONE_ROW))
    values = {n: v for _b, n, v in name_boxes(d)}
    assert values["fecha"] == "{date}"
    assert values["qso_con"] == "{callsign}"
    assert values["nombre"] == "{name_title}"
    assert values["rst"] == "{rst}"


def test_a_custom_order_overrides_the_default_names(tmp_path):
    d = detect_boxes(_card(tmp_path / "c.jpg", ONE_ROW))
    order = ["a", "b", "c", "d", "e", "f", "g"]
    assert [n for _b, n, _v in name_boxes(d, order)] == order


def test_extra_boxes_get_placeholder_names_rather_than_being_dropped(tmp_path):
    eight = ONE_ROW + [(1310, 950, 71, 41)]
    d = detect_boxes(_card(tmp_path / "c.jpg", eight))
    assert len(d.boxes) == 8
    named = name_boxes(d)
    # The eighth has no known name, so it is flagged for the user to fill in.
    assert named[7][1] == "field8"
    assert named[7][2] == ""


def test_detected_boxes_are_usable_as_config_field_boxes(tmp_path):
    # The whole point: what detection emits must render correctly.
    from qsl_send.config import load_config
    from qsl_send.render import CardRenderer

    template = _card(tmp_path / "c.jpg", ONE_ROW)
    d = detect_boxes(template)

    cfg = load_config(None)
    cfg.render.template_size = d.size
    # Point the real field specs at the detected geometry.
    for spec, (box, name, value) in zip(cfg.render.fields, name_boxes(d)):
        spec.box = tuple(box.box)
        spec.value = value

    renderer = CardRenderer(template, cfg.render)
    assert not renderer.scaled  # template_size matches, so no rescaling
    card = renderer.render_card(
        {"date": "13/09/2026", "callsign": "AA1AA", "name_title": "Ana Ejemplo",
         "qrg": "7.115", "utc": "17:36", "mode": "SSB", "rst": "599"}
    )
    out = tmp_path / "card.jpg"
    renderer.save(card, out)
    assert out.is_file() and out.stat().st_size > 0
