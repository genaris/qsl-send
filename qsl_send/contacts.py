"""Local address book for operators the log and QRZ don't cover.

A small YAML file mapping callsign -> address (optionally a name), for
addresses you tracked down yourself. Entries take precedence over the ADIF and
QRZ, and are reported in the manifest as ``email_source: override`` so it is
always visible where an address came from.

Callsigns are matched on the base call, so an entry for ``N0CALL`` also covers
``N0CALL/A`` and ``N0CALL/P`` in the log.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from qsl_send.adif import base_callsign
from qsl_send.qrz import valid_email


class ContactsError(Exception):
    """The contacts file is missing or malformed."""


@dataclass
class Contact:
    callsign: str
    email: str = ""
    name: str = ""


def load_contacts(path: str | Path | None) -> tuple[dict[str, Contact], list[str]]:
    """Load the override file. Returns (contacts by base callsign, warnings)."""
    if path is None:
        return {}, []
    p = Path(path).expanduser()
    if not p.is_file():
        raise ContactsError(f"Contacts file not found: {p}")

    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ContactsError(f"{p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ContactsError(f"{p}: expected a mapping of callsign -> address")

    contacts: dict[str, Contact] = {}
    warnings: list[str] = []
    for call, value in raw.items():
        key = base_callsign(str(call))
        if not key:
            continue
        if isinstance(value, str):
            contact = Contact(callsign=key, email=value.strip())
        elif isinstance(value, dict):
            contact = Contact(
                callsign=key,
                email=str(value.get("email", "")).strip(),
                name=str(value.get("name", "")).strip(),
            )
        else:
            warnings.append(f"contacts: ignoring {call!r} (expected an address or a mapping)")
            continue

        if contact.email and not valid_email(contact.email):
            warnings.append(
                f"contacts: {key} has an address that does not look valid "
                f"({contact.email!r}) — ignoring it"
            )
            contact.email = ""
        if not contact.email and not contact.name:
            continue
        contacts[key] = contact

    return contacts, warnings
