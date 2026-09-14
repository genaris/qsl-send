"""Entry point for the packaged application.

Double-clicking opens the window. Passing arguments runs the original
command-line interface, so power users keep everything they had.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
        from qsl_send.cli import main
        raise SystemExit(main())
    from qsl_send.gui import main
    raise SystemExit(main())
