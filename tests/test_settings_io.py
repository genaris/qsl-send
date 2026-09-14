"""Tests for writing individual settings back to the YAML config.

The defining property: only the lines whose values changed may be rewritten.
The config is heavily commented, and those comments are the documentation a
colleague reads when something breaks.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qsl_send.settings_io import (  # noqa: E402
    SettingsWriteError,
    is_block_scalar,
    is_env_placeholder,
    read_block_scalar,
    read_raw_value,
    update_block_scalar,
    update_env_file,
    update_settings,
)

SAMPLE = """\
# A commented configuration.
# Second comment line.

my_callsign: AA1AA      # trailing comment
output_dir: output
skip_without_email: false

# A comment introducing the render block.
render:
  quality: 92
  # a nested comment
  color: "#0b2d5c"

smtp:
  host: smtp.example.com
  port: 587               # 587 = STARTTLS
  username: ${SMTP_USERNAME}
  password: ${SMTP_PASSWORD}
  from_name: "Some Operator"
  delay: 2.0
  subject: "QSL {my_callsign}"
  body: |
    Hola {name_first}!

    Gracias por el contacto.

    73!
"""


@pytest.fixture
def cfg(tmp_path) -> Path:
    p = tmp_path / "qsl-send.yaml"
    p.write_text(SAMPLE, encoding="utf-8")
    return p


def _comments(path: Path) -> int:
    return len([l for l in path.read_text(encoding="utf-8").splitlines()
                if l.strip().startswith("#")])


def test_a_top_level_value_is_changed(cfg):
    assert update_settings(cfg, {"my_callsign": "BB2BB"}) == ["my_callsign"]
    assert "my_callsign: BB2BB" in cfg.read_text(encoding="utf-8")


def test_a_nested_value_is_changed(cfg):
    update_settings(cfg, {"smtp.host": "smtp.gmail.com"})
    assert "host: smtp.gmail.com" in cfg.read_text(encoding="utf-8")


def test_every_comment_survives_a_save(cfg):
    before = _comments(cfg)
    update_settings(cfg, {"my_callsign": "BB2BB", "smtp.port": 465})
    assert _comments(cfg) == before


def test_a_trailing_comment_on_the_edited_line_survives(cfg):
    update_settings(cfg, {"smtp.port": 465})
    text = cfg.read_text(encoding="utf-8")
    assert "port: 465" in text
    assert "# 587 = STARTTLS" in text


def test_the_line_count_does_not_change(cfg):
    before = len(cfg.read_text(encoding="utf-8").splitlines())
    update_settings(cfg, {"my_callsign": "BB2BB", "output_dir": "cards"})
    assert len(cfg.read_text(encoding="utf-8").splitlines()) == before


def test_untouched_lines_are_byte_identical(cfg):
    before = cfg.read_text(encoding="utf-8").splitlines()
    update_settings(cfg, {"my_callsign": "BB2BB"})
    after = cfg.read_text(encoding="utf-8").splitlines()
    changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(changed) == 1  # exactly the one line we asked to change


def test_an_env_placeholder_is_not_silently_overwritten(cfg):
    assert update_settings(cfg, {"smtp.password": "hunter2"}) == []
    assert "${SMTP_PASSWORD}" in cfg.read_text(encoding="utf-8")


def test_a_placeholder_can_be_replaced_when_explicitly_allowed(cfg):
    written = update_settings(
        cfg, {"smtp.password": "hunter2"},
        allow_replacing_placeholders={"smtp.password"})
    assert written == ["smtp.password"]
    text = cfg.read_text(encoding="utf-8")
    assert "password: hunter2" in text
    # The opt-in is per key: username keeps its placeholder.
    assert "${SMTP_USERNAME}" in text


def test_an_unchanged_value_is_not_rewritten(cfg):
    assert update_settings(cfg, {"my_callsign": "AA1AA"}) == []


def test_an_unknown_key_is_ignored_rather_than_invented(cfg):
    assert update_settings(cfg, {"nonexistent.key": "x"}) == []
    assert "nonexistent" not in cfg.read_text(encoding="utf-8")


def test_booleans_are_written_as_yaml_not_python(cfg):
    update_settings(cfg, {"skip_without_email": True})
    text = cfg.read_text(encoding="utf-8")
    assert "skip_without_email: true" in text
    assert "True" not in text


def test_values_that_could_be_misread_are_quoted(cfg):
    update_settings(cfg, {"my_callsign": "yes"})
    assert 'my_callsign: "yes"' in cfg.read_text(encoding="utf-8")


def test_a_value_containing_a_colon_is_quoted(cfg):
    update_settings(cfg, {"output_dir": "C:/cards"})
    text = cfg.read_text(encoding="utf-8")
    assert 'output_dir: "C:/cards"' in text
    import yaml
    assert yaml.safe_load(text)["output_dir"] == "C:/cards"


def test_the_file_still_parses_as_yaml_after_editing(cfg):
    update_settings(cfg, {
        "my_callsign": "CC3CC", "smtp.port": 465,
        "smtp.from_name": "Name With Spaces", "skip_without_email": True,
    })
    import yaml
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert data["my_callsign"] == "CC3CC"
    assert data["smtp"]["port"] == 465
    assert data["skip_without_email"] is True


def test_nested_keys_do_not_collide_across_blocks(cfg):
    # Both render and smtp could plausibly own a bare `quality`/`host`; the
    # dotted path must pick the right block.
    update_settings(cfg, {"render.quality": 80})
    import yaml
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert data["render"]["quality"] == 80
    assert data["smtp"]["port"] == 587


def test_read_raw_value_sees_the_placeholder_not_the_expansion(cfg):
    assert read_raw_value(cfg, "smtp.password") == "${SMTP_PASSWORD}"
    assert is_env_placeholder(read_raw_value(cfg, "smtp.password"))
    assert not is_env_placeholder(read_raw_value(cfg, "smtp.host"))


def test_missing_file_raises_a_clear_error(tmp_path):
    with pytest.raises(SettingsWriteError):
        update_settings(tmp_path / "nope.yaml", {"my_callsign": "AA1AA"})


def test_a_blank_password_must_not_wipe_a_stored_one(tmp_path):
    """The settings window drops an empty password box before saving.

    The box can legitimately come up empty — a config pointing at
    ${SMTP_PASSWORD} with no .env present — and saving then would silently
    destroy a working setup.
    """
    p = tmp_path / "qsl-send.yaml"
    p.write_text(
        "my_callsign: AA1AA\nsmtp:\n  host: smtp.example.com\n"
        "  password: keepme123\n",
        encoding="utf-8",
    )
    # Exactly what gui.SettingsDialog.on_save does with a blank box.
    changes = {"my_callsign": "BB2BB", "smtp.password": "   "}
    if not str(changes.get("smtp.password", "")).strip():
        changes.pop("smtp.password")
    update_settings(p, changes, allow_replacing_placeholders=frozenset())

    text = p.read_text(encoding="utf-8")
    assert "my_callsign: BB2BB" in text
    assert "password: keepme123" in text


def test_a_typed_password_does_replace_a_literal_one(tmp_path):
    p = tmp_path / "qsl-send.yaml"
    p.write_text("smtp:\n  password: old-secret\n", encoding="utf-8")
    assert update_settings(p, {"smtp.password": "new-secret"}) == ["smtp.password"]
    assert "password: new-secret" in p.read_text(encoding="utf-8")


def test_a_block_scalar_is_recognised_as_such(cfg):
    assert is_block_scalar(read_raw_value(cfg, "smtp.body"))
    assert not is_block_scalar(read_raw_value(cfg, "smtp.subject"))


def test_reading_a_block_returns_its_text_not_the_marker(cfg):
    body = read_block_scalar(cfg, "smtp.body")
    assert body.startswith("Hola {name_first}!")
    assert "73!" in body
    assert "|" not in body.splitlines()[0]


def test_reading_a_block_preserves_internal_blank_lines(cfg):
    assert "\n\n" in read_block_scalar(cfg, "smtp.body")


def test_update_settings_refuses_to_rewrite_a_block_line(cfg):
    """Replacing the `body: |` line would orphan its text and corrupt the file."""
    import yaml

    assert update_settings(cfg, {"smtp.body": "roto"}) == []
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert data["smtp"]["body"].startswith("Hola")


def test_a_block_can_be_rewritten_and_the_file_stays_valid(cfg):
    import yaml

    assert update_block_scalar(cfg, "smtp.body", "Linea uno\n\nLinea dos\n")
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert data["smtp"]["body"].splitlines()[0] == "Linea uno"
    assert data["smtp"]["subject"] == "QSL {my_callsign}"
    assert data["my_callsign"] == "AA1AA"


def test_rewriting_a_block_keeps_every_comment(cfg):
    before = _comments(cfg)
    update_block_scalar(cfg, "smtp.body", "Nuevo texto\n")
    assert _comments(cfg) == before


def test_rewriting_a_block_survives_a_read_back(cfg):
    text = "Hola {name_first}!\n\nSegunda linea.\n\n73!\n{my_callsign}"
    update_block_scalar(cfg, "smtp.body", text)
    assert read_block_scalar(cfg, "smtp.body") == text


def test_a_shorter_block_does_not_leave_old_lines_behind(cfg):
    import yaml

    update_block_scalar(cfg, "smtp.body", "Corto.\n")
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert data["smtp"]["body"].strip() == "Corto."
    assert "Gracias por el contacto" not in cfg.read_text(encoding="utf-8")


def test_rewriting_a_block_leaves_following_keys_intact(cfg):
    import yaml

    update_block_scalar(cfg, "smtp.body", "x\n")
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert data["render"]["quality"] == 92
    assert data["smtp"]["delay"] == 2.0


def test_placeholders_in_the_body_are_not_mangled(cfg):
    update_block_scalar(cfg, "smtp.body", "Hola {name_first}, {callsign}!\n")
    assert "{name_first}" in read_block_scalar(cfg, "smtp.body")


def test_updating_a_missing_block_raises_rather_than_inventing_one(cfg):
    with pytest.raises(SettingsWriteError):
        update_block_scalar(cfg, "smtp.nonexistent", "x")


def test_updating_a_non_block_key_as_a_block_raises(cfg):
    with pytest.raises(SettingsWriteError):
        update_block_scalar(cfg, "smtp.subject", "x")


def test_env_writer_updates_an_existing_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\nSMTP_USERNAME=old@example.com\n", encoding="utf-8")
    assert update_env_file(env, {"SMTP_USERNAME": "new@example.com"}) == ["SMTP_USERNAME"]
    text = env.read_text(encoding="utf-8")
    assert "SMTP_USERNAME=new@example.com" in text
    assert "# comment" in text


def test_env_writer_appends_a_missing_key_and_creates_the_file(tmp_path):
    env = tmp_path / ".env"
    assert update_env_file(env, {"SMTP_PASSWORD": "abcd"}) == ["SMTP_PASSWORD"]
    assert "SMTP_PASSWORD=abcd" in env.read_text(encoding="utf-8")
