"""Tests for interface translation and OS language detection."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qsl_send import i18n  # noqa: E402
from qsl_send.i18n import (  # noqa: E402
    DEFAULT_LANGUAGE,
    SUPPORTED,
    _normalise,
    detect_language,
    set_language,
    t,
)


@pytest.fixture(autouse=True)
def _restore_language():
    before = i18n.get_language()
    yield
    i18n.set_language(before)


def test_normalise_accepts_the_tag_shapes_each_platform_reports():
    assert _normalise("es") == "es"
    assert _normalise("es-AR") == "es"          # macOS AppleLanguages
    assert _normalise("es_AR.UTF-8") == "es"    # POSIX LANG
    assert _normalise("en-GB") == "en"


def test_normalise_rejects_placeholder_and_unsupported_locales():
    # macOS hands a GUI app "C"/"POSIX" when no LANG is set; that is not a
    # language choice and must not win over real detection.
    assert _normalise("C") is None
    assert _normalise("POSIX") is None
    assert _normalise("") is None
    assert _normalise(None) is None
    assert _normalise("fr-FR") is None  # not translated yet


def test_env_override_wins_over_the_operating_system(monkeypatch):
    monkeypatch.setenv("QSL_SEND_LANG", "es")
    assert detect_language() == "es"
    monkeypatch.setenv("QSL_SEND_LANG", "en")
    assert detect_language() == "en"


def test_an_unsupported_override_is_ignored_rather_than_breaking(monkeypatch):
    monkeypatch.setenv("QSL_SEND_LANG", "klingon")
    assert detect_language() in SUPPORTED


def test_posix_variables_are_read_in_priority_order(monkeypatch):
    monkeypatch.delenv("QSL_SEND_LANG", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    for key in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LANG", "es_AR.UTF-8")
    assert detect_language() == "es"
    # LC_ALL outranks LANG.
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    assert detect_language() == "en"


def test_detection_falls_back_to_english_when_nothing_is_set(monkeypatch):
    monkeypatch.delenv("QSL_SEND_LANG", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    for key in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        monkeypatch.delenv(key, raising=False)
    assert detect_language() == DEFAULT_LANGUAGE


def test_set_language_falls_back_when_given_something_unusable():
    assert set_language("es") == "es"
    assert set_language("zz") in SUPPORTED   # unsupported -> detected/default
    assert set_language(None) in SUPPORTED


def test_spanish_translates_and_english_passes_through():
    set_language("es")
    assert t("Make the cards") == "Crear las tarjetas"
    set_language("en")
    assert t("Make the cards") == "Make the cards"


def test_an_untranslated_string_renders_as_english_not_a_raw_key():
    set_language("es")
    assert t("A string nobody has translated") == "A string nobody has translated"


def test_placeholders_are_filled_in_both_languages():
    set_language("es")
    assert t("Found {count} fields.", count=7) == "Se encontraron 7 campos."
    set_language("en")
    assert t("Found {count} fields.", count=7) == "Found 7 fields."


def test_a_translation_missing_a_placeholder_still_renders(monkeypatch):
    # A bad catalogue entry must not crash the window.
    monkeypatch.setitem(i18n._CATALOGUES["es"], "Broken {count}", "Roto {wrong}")
    set_language("es")
    assert "5" in t("Broken {count}", count=5)


def test_every_spanish_entry_keeps_its_placeholders():
    # A translation that drops or renames a {placeholder} would raise at runtime.
    import re

    ph = re.compile(r"\{(\w+)\}")
    for source, translated in i18n._CATALOGUES["es"].items():
        assert set(ph.findall(source)) == set(ph.findall(translated)), source


def test_every_spanish_entry_actually_differs_from_the_english():
    for source, translated in i18n._CATALOGUES["es"].items():
        assert source != translated, f"untranslated entry: {source!r}"


def test_the_catalogue_covers_the_gui_button_and_status_strings():
    # The strings a colleague sees first; regressions here are very visible.
    must_cover = [
        "Make the cards",
        "Review who gets one…",
        "Send a test to myself",
        "Send the e-mails",
        "Find fields automatically",
        "Choose a card design and a log file.",
        "1. Files",
        "2. Card layout",
        "3. Make and send the cards",
    ]
    for key in must_cover:
        assert key in i18n._CATALOGUES["es"], f"no Spanish for {key!r}"


def test_the_author_credit_is_fixed_not_the_user_callsign():
    """The title credits whoever wrote the app, never whoever is running it.

    These are different things: a colleague using the tool must still see
    "by LU2AOG", not their own callsign.

    Read as source rather than imported: qsl_send.gui exits at import time on a
    Python built without tkinter, which the test environment may well be.
    """
    source = (Path(__file__).resolve().parents[1] / "qsl_send" / "gui.py").read_text(
        encoding="utf-8"
    )
    assert 'AUTHOR_CALLSIGN = "LU2AOG"' in source

    # The credit must not be derived from configuration in any way.
    title_fn = source.split("def _window_title")[1].split("\n    def ")[0]
    assert "AUTHOR_CALLSIGN" in title_fn
    assert "my_callsign" not in title_fn


def test_the_author_credit_translates():
    set_language("en")
    assert t("by {callsign}", callsign="LU2AOG") == "by LU2AOG"
    set_language("es")
    assert t("by {callsign}", callsign="LU2AOG") == "por LU2AOG"
