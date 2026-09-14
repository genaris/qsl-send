"""Inspect an output folder before writing a new batch into it.

One folder per activation keeps each batch's manifest and delivery log
separate. Reusing a folder does not cause duplicate e-mails — the sent-log key
includes the card file name, which carries the QSO date — but it does overwrite
the previous manifest, mixing two activations' records together.

Rather than warn whenever a folder exists (which is the normal case when
regenerating the same batch, and would quickly become noise people click
through), this reports *what* is already there so the caller can warn only when
it matters: a different activation, or a batch already e-mailed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Workspace:
    """What an output folder already contains."""

    path: Path
    exists: bool = False
    cards: int = 0
    qso_dates: list[str] = field(default_factory=list)
    generated_at: str = ""
    sent: int = 0
    sent_first: str = ""
    sent_last: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.exists or (self.cards == 0 and self.sent == 0)

    def holds_other_activation(self, new_dates: list[str]) -> bool:
        """True when the folder holds QSOs from dates the new batch lacks."""
        if not self.qso_dates or not new_dates:
            return False
        return not set(self.qso_dates) & set(new_dates)

    def describe_dates(self) -> str:
        """The stored QSO dates as DD/MM/YYYY, for showing to a person."""
        out = []
        for raw in self.qso_dates[:3]:
            if len(raw) == 8 and raw.isdigit():
                out.append(f"{raw[6:8]}/{raw[4:6]}/{raw[:4]}")
            else:
                out.append(raw)
        if len(self.qso_dates) > 3:
            out.append("…")
        return ", ".join(out)


def inspect(output_dir: str | Path) -> Workspace:
    """Read whatever a previous run left in `output_dir`. Never raises."""
    path = Path(output_dir)
    ws = Workspace(path=path, exists=path.is_dir())
    if not ws.exists:
        return ws

    cards_dir = path / "cards"
    if cards_dir.is_dir():
        ws.cards = sum(
            1 for p in cards_dir.iterdir()
            if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png")
        )

    manifest = path / "manifest.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            ws.generated_at = str(data.get("generated_at", ""))
            ws.qso_dates = sorted(
                {c["qso_date"] for c in data.get("cards", []) if c.get("qso_date")}
            )
        except (OSError, ValueError, TypeError):
            pass

    sent = path / "sent.json"
    if sent.is_file():
        try:
            entries = json.loads(sent.read_text(encoding="utf-8"))
            ws.sent = len(entries)
            stamps = sorted(
                str(v.get("sent_at", "")) for v in entries.values() if isinstance(v, dict)
            )
            stamps = [s for s in stamps if s]
            if stamps:
                ws.sent_first, ws.sent_last = stamps[0], stamps[-1]
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    return ws


def adif_dates(adif_path: str | Path) -> list[str]:
    """The distinct QSO dates in a log, so a folder can be matched to it."""
    from qsl_send.adif import read_adif

    try:
        return sorted({q.get("qso_date") for q in read_adif(adif_path) if q.get("qso_date")})
    except (OSError, ValueError):
        return []


def warning_for(ws: Workspace, new_dates: list[str]) -> str | None:
    """A reason to stop and confirm, or None when writing here is unremarkable.

    Regenerating the same activation is routine and gets no warning.
    """
    if ws.is_empty:
        return None

    if ws.holds_other_activation(new_dates):
        parts = [
            f"'{ws.path.name}' already holds a different activation "
            f"({ws.cards} card(s) from {ws.describe_dates()})."
        ]
        if ws.sent:
            parts.append(f"{ws.sent} of them were already e-mailed.")
        parts.append(
            "Generating here overwrites that record. Use a separate folder "
            "per activation to keep each one's history."
        )
        return " ".join(parts)

    if ws.sent:
        return (
            f"'{ws.path.name}' already has {ws.sent} e-mail(s) sent "
            f"({ws.sent_first[:16].replace('T', ' ')}). Regenerating is safe — "
            "those recipients stay marked as done and will not be mailed twice."
        )
    return None
