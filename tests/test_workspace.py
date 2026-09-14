"""Tests for inspecting an output folder before writing a batch into it.

The point is to warn about a *different* activation, not about the folder
merely existing — regenerating the same batch is routine, and a warning that
fires every time is one people learn to click through.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qsl_send.workspace import adif_dates, inspect, warning_for  # noqa: E402


def _batch(path: Path, dates: list[str], *, cards: int = 2, sent: int = 0) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "cards").mkdir(exist_ok=True)
    for i in range(cards):
        (path / "cards" / f"AA{i}AA_{dates[0]}_1200.jpg").write_bytes(b"x")
    (path / "manifest.json").write_text(json.dumps({
        "generated_at": "2026-09-14T10:00:00+00:00",
        "cards": [{"callsign": f"AA{i}AA", "qso_date": dates[i % len(dates)]}
                  for i in range(cards)],
    }), encoding="utf-8")
    if sent:
        (path / "sent.json").write_text(json.dumps({
            f"AA{i}AA|cards/x.jpg|a@example.com": {
                "callsign": f"AA{i}AA", "email": "a@example.com",
                "card_file": "x.jpg", "sent_at": "2026-09-14T11:0%d:00+00:00" % i,
            } for i in range(sent)
        }), encoding="utf-8")
    return path


def test_a_folder_that_does_not_exist_is_empty(tmp_path):
    ws = inspect(tmp_path / "nope")
    assert not ws.exists and ws.is_empty
    assert warning_for(ws, ["20260913"]) is None


def test_an_existing_but_unused_folder_does_not_warn(tmp_path):
    (tmp_path / "out").mkdir()
    assert warning_for(inspect(tmp_path / "out"), ["20260913"]) is None


def test_regenerating_the_same_activation_does_not_warn(tmp_path):
    ws = inspect(_batch(tmp_path / "out", ["20260913"]))
    assert warning_for(ws, ["20260913"]) is None


def test_a_different_activation_warns(tmp_path):
    ws = inspect(_batch(tmp_path / "out", ["20260830"]))
    warning = warning_for(ws, ["20260913"])
    assert warning and "different activation" in warning


def test_the_warning_names_what_is_already_there(tmp_path):
    ws = inspect(_batch(tmp_path / "out-dps-02", ["20260830"], cards=3))
    warning = warning_for(ws, ["20260913"])
    assert "out-dps-02" in warning
    assert "3 card(s)" in warning
    assert "30/08/2026" in warning  # shown the way a person writes a date


def test_a_different_activation_that_was_sent_says_so(tmp_path):
    ws = inspect(_batch(tmp_path / "out", ["20260830"], cards=2, sent=2))
    warning = warning_for(ws, ["20260913"])
    assert "already e-mailed" in warning


def test_regenerating_an_already_sent_batch_is_reassuring_not_alarming(tmp_path):
    """Sending then regenerating the same batch is safe; say so plainly."""
    ws = inspect(_batch(tmp_path / "out", ["20260913"], sent=2))
    warning = warning_for(ws, ["20260913"])
    assert warning and "not be mailed twice" in warning
    assert "different activation" not in warning


def test_overlapping_dates_count_as_the_same_activation(tmp_path):
    # A log spanning midnight, regenerated against a folder holding one day.
    ws = inspect(_batch(tmp_path / "out", ["20260913"]))
    assert warning_for(ws, ["20260913", "20260914"]) is None


def test_inspect_reports_cards_dates_and_sends(tmp_path):
    ws = inspect(_batch(tmp_path / "out", ["20260913"], cards=4, sent=3))
    assert ws.cards == 4
    assert ws.qso_dates == ["20260913"]
    assert ws.sent == 3
    assert ws.sent_first and ws.sent_last


def test_a_corrupt_manifest_does_not_raise(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "manifest.json").write_text("{not json", encoding="utf-8")
    ws = inspect(out)
    assert ws.qso_dates == []


def test_a_corrupt_sent_log_does_not_raise(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "sent.json").write_text("[]", encoding="utf-8")
    assert inspect(out).sent == 0


def test_adif_dates_reads_the_distinct_days(tmp_path):
    log = tmp_path / "log.adi"
    log.write_text(
        "<eoh>\n<call:5>AA1AA<qso_date:8>20260913<eor>\n"
        "<call:5>BB2BB<qso_date:8>20260913<eor>\n"
        "<call:5>CC3CC<qso_date:8>20260914<eor>\n", encoding="utf-8")
    assert adif_dates(log) == ["20260913", "20260914"]


def test_adif_dates_on_a_missing_file_returns_nothing(tmp_path):
    assert adif_dates(tmp_path / "nope.adi") == []


def test_unknown_dates_never_produce_a_false_warning(tmp_path):
    # A log with no dates at all must not be reported as "a different activation".
    ws = inspect(_batch(tmp_path / "out", ["20260830"]))
    assert warning_for(ws, []) is None
