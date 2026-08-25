"""QRZ.com XML callsign-data client.

Uses the XML Logbook Data service (https://xmldata.qrz.com/xml/current/):
one session request for a key, then one request per callsign.  Results are
cached on disk so re-runs over the same log do not re-query QRZ.

Note: QRZ only returns the ``<email>`` element to accounts with an XML
subscription, and only when the operator has not hidden their address.
Missing e-mail is normal and is reported per callsign rather than fatal.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree

import requests

from qsl_send.config import QrzConfig

QRZ_URL = "https://xmldata.qrz.com/xml/current/"


class QrzError(Exception):
    """QRZ rejected the credentials or the service is unavailable."""


@dataclass
class QrzRecord:
    callsign: str = ""
    name: str = ""
    email: str = ""
    qth: str = ""
    country: str = ""
    grid: str = ""
    found: bool = False
    error: str = ""


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _to_dict(element: ElementTree.Element) -> dict[str, str]:
    return {_strip_ns(child.tag): (child.text or "").strip() for child in element}


class QrzClient:
    """Thin QRZ XML client with a JSON file cache."""

    def __init__(self, cfg: QrzConfig, cache_path: Path | None = None):
        self.cfg = cfg
        self.cache_path = cache_path
        self._session_key: str | None = None
        self._http = requests.Session()
        self._http.headers["User-Agent"] = f"{cfg.agent}/0.1"
        self._cache: dict[str, dict] = {}
        self._cache_dirty = False
        self._load_cache()

    # -- cache ---------------------------------------------------------

    def _load_cache(self) -> None:
        if self.cache_path and self.cache_path.is_file():
            try:
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._cache = {}

    def flush(self) -> None:
        if not (self.cache_path and self._cache_dirty):
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(self._cache, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            self._cache_dirty = False
        except OSError:
            pass  # a non-writable cache should never break a run

    # -- session -------------------------------------------------------

    def _request(self, params: dict[str, str]) -> ElementTree.Element:
        try:
            resp = self._http.get(QRZ_URL, params=params, timeout=self.cfg.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise QrzError(f"QRZ request failed: {exc}") from exc
        try:
            return ElementTree.fromstring(resp.content)
        except ElementTree.ParseError as exc:
            raise QrzError(f"QRZ returned malformed XML: {exc}") from exc

    def login(self) -> str:
        if self._session_key:
            return self._session_key
        if not (self.cfg.username and self.cfg.password):
            raise QrzError("qrz.username and qrz.password are required for lookups")
        root = self._request(
            {
                "username": self.cfg.username,
                "password": self.cfg.password,
                "agent": self.cfg.agent,
            }
        )
        session = self._find_session(root)
        key = session.get("key", "")
        if not key:
            reason = session.get("error") or "no session key returned"
            raise QrzError(f"QRZ login failed: {reason}")
        self._session_key = key
        return key

    @staticmethod
    def _find_session(root: ElementTree.Element) -> dict[str, str]:
        for child in root:
            if _strip_ns(child.tag) == "session":
                return _to_dict(child)
        return {}

    @staticmethod
    def _find_callsign(root: ElementTree.Element) -> dict[str, str]:
        for child in root:
            if _strip_ns(child.tag) == "callsign":
                return _to_dict(child)
        return {}

    # -- lookups -------------------------------------------------------

    def lookup(self, callsign: str, *, use_cache: bool = True) -> QrzRecord:
        """Look up one callsign. Never raises for a per-call failure."""
        call = (callsign or "").strip().upper()
        if not call:
            return QrzRecord(error="empty callsign")
        if use_cache and call in self._cache:
            return QrzRecord(**self._cache[call])

        try:
            key = self.login()
            root = self._request({"s": key, "callsign": call})
            session = self._find_session(root)
            err = session.get("error", "")
            if err and "session timeout" in err.lower():
                self._session_key = None
                root = self._request({"s": self.login(), "callsign": call})
                session = self._find_session(root)
                err = session.get("error", "")
            data = self._find_callsign(root)
        except QrzError as exc:
            return QrzRecord(callsign=call, error=str(exc))

        if not data:
            record = QrzRecord(callsign=call, error=err or "not found")
        else:
            name = " ".join(p for p in (data.get("fname", ""), data.get("name", "")) if p)
            record = QrzRecord(
                callsign=data.get("call", call).upper(),
                name=name.strip(),
                email=data.get("email", ""),
                qth=data.get("addr2", ""),
                country=data.get("country", ""),
                grid=data.get("grid", "").upper(),
                found=True,
            )

        self._cache[call] = asdict(record)
        self._cache_dirty = True
        return record

    def lookup_many(
        self, callsigns: list[str], *, use_cache: bool = True, delay: float = 0.0
    ) -> dict[str, QrzRecord]:
        out: dict[str, QrzRecord] = {}
        for i, call in enumerate(callsigns):
            cached = use_cache and call in self._cache
            out[call] = self.lookup(call, use_cache=use_cache)
            if delay and not cached and i + 1 < len(callsigns):
                time.sleep(delay)
        self.flush()
        return out


EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def valid_email(value: str) -> bool:
    return bool(EMAIL_RE.match((value or "").strip()))
