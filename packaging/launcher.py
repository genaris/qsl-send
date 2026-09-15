"""Entry point for the packaged application.

Double-clicking opens the window. Passing arguments runs the original
command-line interface, so power users keep everything they had.

The imports below are deliberately at module level, not inside ``__main__``:
PyInstaller analyses this file statically, and an import hidden behind a
runtime ``sys.path`` tweak is invisible to it. That is what produced
"No module named qsl_send" in the packaged application.
"""

import sys

# The CLI is imported eagerly: it is safe everywhere and gives PyInstaller's
# static analysis a path into the package.
from qsl_send.cli import main as cli_main

# The GUI is NOT imported here. qsl_send.gui raises SystemExit at import time
# on a Python without tkinter, which would take the command line down with it —
# `--version` would print a tkinter error instead of the version. It is
# imported only when a window is actually wanted; the spec lists it under
# hiddenimports so it still ends up in the bundle.


def _wants_cli(argv: list[str]) -> bool:
    """True when the app was started with command-line arguments.

    Double-clicking passes none, so that opens the window. A single .yaml
    argument means a config file was dropped onto the icon, which is still a
    GUI launch. Anything else is a CLI invocation.
    """
    if not argv:
        return False
    if len(argv) == 1 and argv[0].lower().endswith((".yaml", ".yml")):
        return False
    return True


if __name__ == "__main__":
    if _wants_cli(sys.argv[1:]):
        raise SystemExit(cli_main())
    from qsl_send.gui import main as gui_main

    raise SystemExit(gui_main())
