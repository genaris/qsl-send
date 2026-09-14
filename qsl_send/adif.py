"""Minimal ADIF (Amateur Data Interchange Format) reader.

Only what a QSL generator needs: skip the header, then read
``<field:len[:type]>value`` pairs until each ``<eor>``.  Field names are
lower-cased; values are kept verbatim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

# Matched against bytes: ADI field lengths count BYTES, not characters, so an
# accented value like <name:30>Cristóbal Mariano Di Bártolo (28 chars, 30 bytes
# in UTF-8) is only sliced correctly before decoding.
_TAG = re.compile(rb"<([^:<>]+)(?::(\d+))?(?::([^:<>]+))?>", re.IGNORECASE)


@dataclass
class Qso:
    """One logged contact. ``fields`` holds the raw ADIF record."""

    fields: dict[str, str] = field(default_factory=dict)
    index: int = 0

    def get(self, name: str, default: str = "") -> str:
        return self.fields.get(name.lower(), default)

    @property
    def call(self) -> str:
        return self.get("call").upper()


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _iter_tags(data: bytes) -> Iterator[tuple[str, str]]:
    pos = 0
    while True:
        m = _TAG.search(data, pos)
        if not m:
            return
        name = _decode(m.group(1)).strip().lower()
        length = m.group(2)
        if length is None:
            # Control tag such as <eoh> / <eor>: no payload.
            yield name, ""
            pos = m.end()
            continue
        n = int(length)
        yield name, _decode(data[m.end() : m.end() + n])
        pos = m.end() + n


def parse_adif(source: str | bytes) -> list[Qso]:
    """Parse ADIF content into a list of QSOs, in file order.

    Accepts bytes (preferred — field lengths are byte counts) or str.
    """
    data = source.encode("utf-8") if isinstance(source, str) else source
    head_end = data.lower().find(b"<eoh>")
    body = data[head_end + len(b"<eoh>") :] if head_end != -1 else data

    qsos: list[Qso] = []
    current: dict[str, str] = {}
    for name, value in _iter_tags(body):
        if name == "eor":
            if current:
                qsos.append(Qso(fields=current, index=len(qsos) + 1))
            current = {}
        elif name != "eoh":
            current[name] = value
    if current:
        qsos.append(Qso(fields=current, index=len(qsos) + 1))
    return qsos


def read_adif(path: str | Path) -> list[Qso]:
    """Read an ADIF file from disk. Values decode as UTF-8, else latin-1."""
    return parse_adif(Path(path).read_bytes())


def base_callsign(call: str) -> str:
    """Strip portable prefixes/suffixes: ``LU2GPC/A`` -> ``LU2GPC``.

    Used for QRZ lookups, which key on the base callsign.
    """
    call = (call or "").strip().upper()
    if "/" not in call:
        return call
    parts = [p for p in call.split("/") if p]
    if not parts:
        return call
    # The base call is the longest part containing a digit
    # (DL/LU2AOG -> LU2AOG, LU2AOG/A -> LU2AOG).
    candidates = [p for p in parts if any(c.isdigit() for c in p)]
    if not candidates:
        return parts[0]
    return max(candidates, key=len)
