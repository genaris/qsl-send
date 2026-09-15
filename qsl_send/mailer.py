"""SMTP delivery of generated QSL cards.

Nothing here runs unless ``qsl-send send`` is invoked without ``--dry-run``.
Deliveries are recorded in ``sent.json`` next to the manifest so a repeated
run does not mail the same operator twice.
"""

from __future__ import annotations

import json
import mimetypes
import smtplib
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path
from typing import Callable

from qsl_send.config import SmtpConfig
from qsl_send.fields import format_template


class MailError(Exception):
    """SMTP connection, authentication or delivery failure."""


@dataclass
class Outgoing:
    """One e-mail queued for delivery."""

    callsign: str
    to_address: str
    card_path: Path
    values: dict[str, str] = field(default_factory=dict)
    key: str = ""  # identity in the sent-log


@dataclass
class SendOutcome:
    callsign: str
    to_address: str
    card_file: str
    status: str  # sent | failed | skipped
    detail: str = ""


def _safe_attachment_name(name: str, fallback: str) -> str:
    # Keep portable callsigns readable: LU2AOG/A -> LU2AOG-A.
    name = name.replace("/", "-")
    cleaned = "".join(c for c in name if c.isalnum() or c in "._- ").strip()
    return cleaned or fallback


def build_message(cfg: SmtpConfig, item: Outgoing, *, attachment_template: str) -> EmailMessage:
    """Compose one QSL e-mail with the card attached."""
    msg = EmailMessage()
    subject = format_template(cfg.subject, item.values).strip()
    body = format_template(cfg.body, item.values)

    msg["Subject"] = subject or f"QSL {item.callsign}"
    msg["From"] = (
        formataddr((cfg.from_name, cfg.from_address))
        if cfg.from_name
        else cfg.from_address
    )
    msg["To"] = item.to_address
    msg["Date"] = formatdate(localtime=True)
    # Key the Message-ID off the sending domain. The default derives it from the
    # local hostname, which on a laptop yields something like
    # <...@1.0.0.…ip6.arpa> and reads as suspicious to spam filters.
    domain = cfg.from_address.rpartition("@")[2] or None
    msg["Message-ID"] = make_msgid(domain=domain)
    if cfg.reply_to:
        msg["Reply-To"] = cfg.reply_to
    msg.set_content(body)

    data = item.card_path.read_bytes()
    ctype, _ = mimetypes.guess_type(item.card_path.name)
    maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
    filename = _safe_attachment_name(
        format_template(attachment_template, item.values) + item.card_path.suffix,
        item.card_path.name,
    )
    msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg


class SentLog:
    """Record of what has already been delivered, keyed per card+recipient."""

    def __init__(self, path: Path):
        self.path = path
        self.entries: dict[str, dict] = {}
        if path.is_file():
            try:
                self.entries = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.entries = {}

    def already_sent(self, key: str) -> bool:
        return key in self.entries

    def record(self, key: str, callsign: str, to_address: str, card_file: str) -> None:
        self.entries[key] = {
            "callsign": callsign,
            "email": to_address,
            "card_file": card_file,
            "sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.entries, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:  # pragma: no cover - disk failure
            raise MailError(f"Could not write the sent log {self.path}: {exc}") from exc


class Mailer:
    """A single authenticated SMTP session used for the whole batch."""

    def __init__(self, cfg: SmtpConfig):
        self.cfg = cfg
        self._smtp: smtplib.SMTP | smtplib.SMTP_SSL | None = None

    def __enter__(self) -> Mailer:
        self.connect()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def connect(self) -> None:
        cfg = self.cfg
        if not cfg.host:
            raise MailError("smtp.host is not set in the config")
        if not cfg.from_address:
            raise MailError("smtp.from_address is not set in the config")
        context = ssl.create_default_context()
        try:
            if cfg.port == 465:
                smtp: smtplib.SMTP = smtplib.SMTP_SSL(
                    cfg.host, cfg.port, timeout=cfg.timeout, context=context
                )
            else:
                smtp = smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout)
                smtp.ehlo()
                if cfg.use_tls:
                    smtp.starttls(context=context)
                    smtp.ehlo()
            if cfg.username:
                if not cfg.password:
                    # Caught here rather than letting the server answer
                    # "530 Authentication Required", which tells the user
                    # nothing about what to fix.
                    raise MailError(
                        "No password is set for "
                        f"{cfg.username}, so the mail server rejected the "
                        "sign-in.\n\n"
                        "For Gmail this must be a 16-character App Password "
                        "from https://myaccount.google.com/apppasswords — not "
                        "your normal Google password, and 2-Step Verification "
                        "must be on.\n\n"
                        "Enter it in Settings under Password."
                    )
                if cfg.username.startswith(("myemail@", "your", "user@")):
                    raise MailError(
                        f"The sign-in address is still the example value "
                        f"'{cfg.username}'. Put your own address in Settings "
                        "under 'Sign in as'."
                    )
                password = cfg.password
                if "gmail.com" in cfg.host.lower():
                    # Google shows App Passwords as four groups of four; those
                    # spaces are presentational and must not be sent.
                    password = "".join(password.split())
                smtp.login(cfg.username, password)
        except smtplib.SMTPAuthenticationError as exc:
            raise MailError(
                f"SMTP authentication rejected by {cfg.host}: {exc.smtp_code} "
                f"{exc.smtp_error!r}. For Gmail, check that 2-Step Verification is on "
                "and SMTP_PASSWORD holds an App Password."
            ) from exc
        except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
            raise MailError(f"Could not connect to {cfg.host}:{cfg.port}: {exc}") from exc
        self._smtp = smtp

    def send(self, msg: EmailMessage) -> None:
        if self._smtp is None:
            raise MailError("send() called before connect()")
        try:
            self._smtp.send_message(msg)
        except smtplib.SMTPException as exc:
            raise MailError(str(exc)) from exc

    def close(self) -> None:
        if self._smtp is not None:
            try:
                self._smtp.quit()
            except smtplib.SMTPException:
                pass
            self._smtp = None


def deliver(
    cfg: SmtpConfig,
    items: list[Outgoing],
    *,
    attachment_template: str,
    sent_log: SentLog | None,
    delay: float = 0.0,
    progress: Callable[[str], None] | None = None,
) -> list[SendOutcome]:
    """Send every queued message, continuing past individual failures."""
    say = progress or (lambda _m: None)
    outcomes: list[SendOutcome] = []
    if not items:
        return outcomes

    with Mailer(cfg) as mailer:
        for i, item in enumerate(items):
            try:
                msg = build_message(cfg, item, attachment_template=attachment_template)
                mailer.send(msg)
            except (MailError, OSError) as exc:
                outcomes.append(
                    SendOutcome(
                        item.callsign, item.to_address, item.card_path.name, "failed", str(exc)
                    )
                )
                say(f"! {item.callsign:<10} {item.to_address:<32} FAILED: {exc}")
            else:
                outcomes.append(
                    SendOutcome(item.callsign, item.to_address, item.card_path.name, "sent")
                )
                say(f"> {item.callsign:<10} {item.to_address:<32} sent")
                if sent_log is not None:
                    sent_log.record(
                        item.key, item.callsign, item.to_address, item.card_path.name
                    )
                    sent_log.save()
            if delay and i + 1 < len(items):
                time.sleep(delay)
    return outcomes
