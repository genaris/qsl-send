"""Tests for locating a user's settings in an installed application.

The failure these guard against: launched from the Start menu, the working
directory is not where the application lives, so nothing was found and the
settings window refused to open — a dead end for someone who does not know
what a YAML file is.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qsl_send import userdata  # noqa: E402
from qsl_send.userdata import (  # noqa: E402
    CONFIG_NAME,
    ensure_user_config,
    is_frozen,
    resolve_config,
    user_config_dir,
)


def test_windows_settings_go_under_appdata(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert user_config_dir() == tmp_path / "Roaming" / "qsl-send"


def test_macos_settings_go_under_application_support(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert user_config_dir() == tmp_path / "Library" / "Application Support" / "qsl-send"


def test_linux_honours_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert user_config_dir() == tmp_path / "cfg" / "qsl-send"


def test_a_missing_appdata_still_yields_a_path(monkeypatch, tmp_path):
    # A stripped-down Windows environment must not crash the application.
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert user_config_dir().name == "qsl-send"


def test_first_run_creates_a_real_settings_file(monkeypatch, tmp_path):
    monkeypatch.setattr(userdata, "user_config_dir", lambda: tmp_path / "cfg")
    monkeypatch.setattr(userdata, "find_example", lambda: None)
    created = ensure_user_config()
    assert created.is_file()
    assert created.name == CONFIG_NAME


def test_the_created_file_is_valid_yaml_the_app_can_load(monkeypatch, tmp_path):
    import yaml

    from qsl_send.config import load_config

    monkeypatch.setattr(userdata, "user_config_dir", lambda: tmp_path / "cfg")
    monkeypatch.setattr(userdata, "find_example", lambda: None)
    created = ensure_user_config()

    data = yaml.safe_load(created.read_text(encoding="utf-8"))
    assert data["my_callsign"]          # a placeholder, not empty
    cfg = load_config(created)          # and the real loader accepts it
    assert cfg.smtp.host


def test_the_example_is_preferred_over_the_fallback(monkeypatch, tmp_path):
    example = tmp_path / "example.yaml"
    example.write_text("my_callsign: FROMEXAMPLE\n", encoding="utf-8")
    monkeypatch.setattr(userdata, "user_config_dir", lambda: tmp_path / "cfg")
    monkeypatch.setattr(userdata, "find_example", lambda: example)
    created = ensure_user_config()
    assert "FROMEXAMPLE" in created.read_text(encoding="utf-8")


def test_an_existing_file_is_never_overwritten(monkeypatch, tmp_path):
    monkeypatch.setattr(userdata, "user_config_dir", lambda: tmp_path / "cfg")
    monkeypatch.setattr(userdata, "find_example", lambda: None)
    first = ensure_user_config()
    first.write_text("my_callsign: MINE\n", encoding="utf-8")
    again = ensure_user_config()
    assert again == first
    assert "MINE" in again.read_text(encoding="utf-8")


def test_an_unwritable_directory_does_not_raise(monkeypatch, tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(userdata, "user_config_dir", lambda: blocked / "cfg")
    monkeypatch.setattr(userdata, "find_example", lambda: None)
    # Returns a path rather than exploding; the caller reports the problem.
    assert ensure_user_config().name == CONFIG_NAME


def test_an_explicit_path_wins(tmp_path):
    explicit = tmp_path / "custom.yaml"
    explicit.write_text("my_callsign: AA1AA\n", encoding="utf-8")
    assert resolve_config(explicit) == explicit


def test_a_config_in_the_working_directory_is_used(monkeypatch, tmp_path):
    (tmp_path / CONFIG_NAME).write_text("my_callsign: AA1AA\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert resolve_config() == tmp_path / CONFIG_NAME


def test_from_a_checkout_with_no_config_nothing_is_invented(monkeypatch, tmp_path):
    # Running from source keeps the old behaviour: no config, no file created.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(userdata, "is_frozen", lambda: False)
    monkeypatch.setattr(userdata, "user_config_dir", lambda: tmp_path / "cfg")
    assert resolve_config() is None


def test_an_installed_application_always_gets_a_config(monkeypatch, tmp_path):
    """The bug this fixes: installed, launched from the Start menu, nothing found."""
    work = tmp_path / "System32"
    work.mkdir()
    monkeypatch.chdir(work)                      # not where the app lives
    monkeypatch.setattr(userdata, "is_frozen", lambda: True)
    monkeypatch.setattr(userdata, "user_config_dir", lambda: tmp_path / "cfg")
    monkeypatch.setattr(userdata, "find_example", lambda: None)

    found = resolve_config()
    assert found is not None and found.is_file()


def test_is_frozen_is_false_when_running_from_source():
    assert is_frozen() is False


def test_bundled_dir_survives_frozen_without_meipass(monkeypatch, tmp_path):
    """sys.frozen without _MEIPASS must not kill the application at startup.

    Some bundlers set one and not the other, and an AttributeError here would
    crash before the window ever opens.
    """
    from qsl_send.userdata import bundled_dir

    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app" / "QSL Sender"))
    assert bundled_dir() == (tmp_path / "app")


def test_bundled_dir_prefers_meipass_when_present(monkeypatch, tmp_path):
    from qsl_send.userdata import bundled_dir

    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    assert bundled_dir() == (tmp_path / "bundle")


def test_documents_is_offered_when_output_would_land_in_appdata(monkeypatch, tmp_path):
    """A relative output_dir resolves against the settings file.

    Installed, that file is in AppData, so "output" would put the cards
    somewhere nobody would look. The window offers Documents instead — but
    only when the folder does not already exist.
    """
    from qsl_send.config import load_config

    settings_dir = tmp_path / "appdata" / "qsl-send"
    settings_dir.mkdir(parents=True)
    cfg_file = settings_dir / CONFIG_NAME
    cfg_file.write_text("my_callsign: AA1AA\noutput_dir: output\n", encoding="utf-8")
    monkeypatch.setattr(userdata, "user_config_dir", lambda: settings_dir)

    cfg = load_config(cfg_file)
    resolved = Path(cfg.resolve(cfg.output_dir))

    # This is the condition the window applies.
    inside_settings_dir = (
        cfg.path is not None
        and not Path(cfg.output_dir).is_absolute()
        and cfg.path.parent == userdata.user_config_dir()
    )
    assert inside_settings_dir
    assert not resolved.exists()          # so Documents wins


def test_an_existing_output_folder_is_left_alone(monkeypatch, tmp_path):
    """If the folder is genuinely in use, do not second-guess it."""
    from qsl_send.config import load_config

    settings_dir = tmp_path / "appdata" / "qsl-send"
    settings_dir.mkdir(parents=True)
    (settings_dir / "output").mkdir()
    cfg_file = settings_dir / CONFIG_NAME
    cfg_file.write_text("my_callsign: AA1AA\noutput_dir: output\n", encoding="utf-8")
    monkeypatch.setattr(userdata, "user_config_dir", lambda: settings_dir)

    cfg = load_config(cfg_file)
    assert Path(cfg.resolve(cfg.output_dir)).exists()   # kept


def test_an_absolute_output_dir_is_never_second_guessed(tmp_path):
    from qsl_send.config import load_config

    cfg_file = tmp_path / CONFIG_NAME
    target = tmp_path / "somewhere"
    cfg_file.write_text(
        f"my_callsign: AA1AA\noutput_dir: {target}\n", encoding="utf-8")
    cfg = load_config(cfg_file)
    assert Path(cfg.output_dir).is_absolute()
