"""Where a *user's* settings live, as opposed to the application's own files.

Running from a checkout, the configuration sits next to the code and the
current directory is the project. An installed application has neither: it is
launched from the Start menu, so the working directory is somewhere arbitrary
like C:\\Windows\\System32, and its own folder under Program Files is read-only
for a normal user.

So the settings belong in a per-user directory:

    Windows   %APPDATA%\\qsl-send\\
    macOS     ~/Library/Application Support/qsl-send/
    Linux     ~/.config/qsl-send/   (or $XDG_CONFIG_HOME)

The first time the application runs there is nothing to edit, which is a dead
end for someone who has no idea what a YAML file is. So the example shipped
inside the application is copied there, giving a real file with sensible
placeholder values that the settings window can open immediately.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_DIR_NAME = "qsl-send"
CONFIG_NAME = "qsl-send.yaml"
EXAMPLE_NAME = "qsl-send.example.yaml"

# Written when no example can be found — the application must still start.
_FALLBACK_CONFIG = """\
# qsl-send settings. Edit here, or use Settings… in the window.

# Your callsign, as printed on the card.
my_callsign: MY1CLL

# The card design and the log to read. Choose these in the window.
template: ""
adif: ""
output_dir: output

# Addresses you looked up yourself, for operators the log does not cover.
contacts_file: contacts.yaml

# Window language: "en", "es", or leave empty to follow the computer.
language: ""

date_format: "%d/%m/%Y"
time_format: "%H:%M"
qrg_decimals: 3
group_by: qso
skip_without_email: true

smtp:
  host: smtp.gmail.com
  port: 587
  username: ""
  password: ""
  use_tls: true
  from_address: ""
  from_name: ""
  delay: 2.0
  timeout: 30
  attachment_name: "QSL_{my_callsign}_{callsign}"
  subject: "QSL {my_callsign} <-> {callsign}"
  body: |
    Hello {name_first}!

    Thank you for the contact on {date} at {utc} UTC
    on {qrg} MHz ({mode}), RST {rst}.

    Your QSL card is attached.

    73!
    {my_callsign}
"""


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle rather than a checkout."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def bundled_dir() -> Path:
    """Where the application's own read-only files live.

    Reads _MEIPASS defensively rather than assuming it exists whenever the
    application looks frozen: some bundlers set sys.frozen without it, and
    an AttributeError here would kill the application at startup.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def user_config_dir() -> Path:
    """The per-user directory for settings. Not created here."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME")
        root = Path(base) if base else Path.home() / ".config"
    return root / APP_DIR_NAME


def find_example() -> Path | None:
    """The example config shipped with the application, wherever it ended up."""
    for candidate in (
        bundled_dir() / EXAMPLE_NAME,
        bundled_dir() / "_internal" / EXAMPLE_NAME,
        Path(sys.executable).resolve().parent / EXAMPLE_NAME,
        Path(__file__).resolve().parent.parent / EXAMPLE_NAME,
    ):
        if candidate.is_file():
            return candidate
    return None


def default_output_dir() -> Path:
    """Somewhere a normal user can actually write cards to."""
    documents = Path.home() / "Documents"
    base = documents if documents.is_dir() else Path.home()
    return base / "QSL Cards"


def ensure_user_config(create: bool = True) -> Path:
    """Return the user's config path, creating it from the example if needed.

    Never raises: if the directory cannot be written, the path is still
    returned so the caller can report something sensible.
    """
    target = user_config_dir() / CONFIG_NAME
    if target.is_file() or not create:
        return target

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        example = find_example()
        if example is not None:
            shutil.copyfile(example, target)
        else:
            target.write_text(_FALLBACK_CONFIG, encoding="utf-8")
    except OSError:
        pass
    return target


def resolve_config(argv_path: str | Path | None = None) -> Path | None:
    """Pick the settings file to use.

    Order: an explicit path, then one beside the current directory (how a
    checkout works), and finally the per-user file — created on first run when
    the application is installed, so the settings window always has something
    to open.
    """
    if argv_path:
        p = Path(argv_path).expanduser()
        if p.is_file():
            return p

    for name in (CONFIG_NAME, "qsl-send.yml"):
        candidate = Path.cwd() / name
        if candidate.is_file():
            return candidate

    existing = user_config_dir() / CONFIG_NAME
    if existing.is_file():
        return existing

    # Installed application, first run: make a real file rather than starting
    # with nothing and refusing to open Settings.
    if is_frozen():
        return ensure_user_config()
    return None
