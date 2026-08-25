"""Turn a raw ADIF record into the placeholder values used by templates.

Both the card text boxes and the output filename / e-mail templates are
``str.format`` strings over the dict produced by :func:`placeholders`.
"""

from __future__ import annotations

from datetime import datetime

from qsl_send.adif import Qso, base_callsign


class _Blank(dict):
    """format_map() helper: unknown placeholders render as an empty string."""

    def __missing__(self, key: str) -> str:  # pragma: no cover - trivial
        return ""


def format_template(template: str, values: dict[str, str]) -> str:
    try:
        return template.format_map(_Blank(values))
    except (IndexError, ValueError):
        # A stray brace in the template: return it as typed rather than crash.
        return template


def _fmt_date(raw: str, fmt: str) -> str:
    raw = (raw or "").strip()
    if len(raw) != 8 or not raw.isdigit():
        return raw
    try:
        return datetime.strptime(raw, "%Y%m%d").strftime(fmt)
    except ValueError:
        return raw


def _fmt_time(raw: str, fmt: str) -> str:
    raw = (raw or "").strip()
    if len(raw) not in (4, 6) or not raw.isdigit():
        return raw
    try:
        return datetime.strptime(raw[:4], "%H%M").strftime(fmt)
    except ValueError:
        return raw


def _fmt_freq(raw: str, decimals: int) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        return f"{float(raw):.{decimals}f}"
    except ValueError:
        return raw


def _titlecase(name: str) -> str:
    """`MARIA DE LOS ANGELES` -> `Maria de los Angeles` (leaves mixed case)."""
    name = (name or "").strip()
    if not name or not name.isupper():
        return name
    small = {"de", "del", "la", "las", "los", "y", "da", "do", "van", "von"}
    out = []
    for i, word in enumerate(name.split()):
        lowered = word.lower()
        out.append(lowered if i and lowered in small else lowered.capitalize())
    return " ".join(out)


def placeholders(
    qso: Qso,
    *,
    date_format: str = "%d/%m/%Y",
    time_format: str = "%H:%M",
    qrg_decimals: int = 3,
    name: str | None = None,
    email: str = "",
    my_callsign: str = "",
) -> dict[str, str]:
    """Build the placeholder dict for one QSO.

    ``name`` overrides the ADIF ``<name>`` (e.g. with a value from QRZ).
    """
    g = qso.get
    raw_name = (name if name is not None else g("name")).strip()
    call = qso.call
    values: dict[str, str] = {
        # The seven template boxes.
        "date": _fmt_date(g("qso_date"), date_format),
        "callsign": call,
        "name": raw_name,
        "qrg": _fmt_freq(g("freq"), qrg_decimals),
        "utc": _fmt_time(g("time_on"), time_format),
        "mode": g("mode").upper(),
        "rst": g("rst_sent"),
        # Handy variants.
        "call": call,
        "base_callsign": base_callsign(call),
        "name_title": _titlecase(raw_name),
        # Falls back to the callsign so a greeting never renders as "Hola !".
        # Hams address each other by callsign anyway when no name is logged.
        "name_first": (_titlecase(raw_name).split(" ")[0] if raw_name else "") or call,
        "date_iso": g("qso_date"),
        "date_adif": g("qso_date"),
        "utc_raw": g("time_on"),
        "time_off": _fmt_time(g("time_off"), time_format),
        "rst_rcvd": g("rst_rcvd"),
        "band": g("band").lower(),
        "freq": g("freq"),
        "qth": g("qth"),
        "gridsquare": g("gridsquare").upper(),
        "country": g("country"),
        "email": email,
        "my_callsign": (my_callsign or g("station_callsign")).upper(),
        "my_name": g("my_name"),
        "my_gridsquare": g("my_gridsquare").upper(),
        "my_qth": g("my_city"),
        "tx_pwr": g("tx_pwr"),
        "index": str(qso.index),
    }
    return values
