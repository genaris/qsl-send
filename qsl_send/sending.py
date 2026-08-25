"""Read a generate run's manifest and turn it into a delivery queue."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from qsl_send.config import Config
from qsl_send.mailer import Outgoing, SentLog


class SendError(Exception):
    """The batch cannot be prepared (missing manifest, no cards, etc.)."""


@dataclass
class Queue:
    items: list[Outgoing]
    skipped_already_sent: int = 0
    skipped_no_email: int = 0
    skipped_missing_card: int = 0
    redirected_to: str = ""

    @property
    def is_test(self) -> bool:
        return bool(self.redirected_to)


def load_manifest(output_dir: Path) -> dict:
    path = output_dir / "manifest.json"
    if not path.is_file():
        raise SendError(
            f"No manifest at {path}. Run 'qsl-send generate' first, review the "
            "cards, then send."
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SendError(f"Could not read {path}: {exc}") from exc


def build_queue(
    cfg: Config,
    output_dir: Path,
    *,
    to_override: str = "",
    limit: int | None = None,
    only_calls: set[str] | None = None,
    resend: bool = False,
    sent_log: SentLog | None = None,
) -> Queue:
    """Turn manifest rows into an ordered list of messages to send.

    ``to_override`` redirects every message to one address for testing; those
    deliveries are never written to the sent log, so a redirected test run does
    not mark the real recipients as done.
    """
    manifest = load_manifest(output_dir)
    cards = manifest.get("cards") or []
    if not cards:
        raise SendError("The manifest lists no cards. Run 'qsl-send generate' first.")

    queue = Queue(items=[], redirected_to=to_override)
    wanted = {c.upper() for c in only_calls} if only_calls else None

    for row in cards:
        callsign = str(row.get("callsign", ""))
        if wanted and callsign.upper() not in wanted:
            continue

        email = str(row.get("email", "")).strip()
        card_file = str(row.get("card_file", "")).strip()

        if not email:
            queue.skipped_no_email += 1
            continue
        if not card_file:
            queue.skipped_missing_card += 1
            continue
        card_path = output_dir / card_file
        if not card_path.is_file():
            queue.skipped_missing_card += 1
            continue

        # Identity in the sent log: this card to this real recipient.
        key = f"{callsign}|{card_file}|{email.lower()}"
        if not resend and not to_override and sent_log and sent_log.already_sent(key):
            queue.skipped_already_sent += 1
            continue

        values = dict(row.get("values") or {})
        values.setdefault("callsign", callsign)
        values.setdefault("email", email)
        values.setdefault("my_callsign", cfg.my_callsign)

        queue.items.append(
            Outgoing(
                callsign=callsign,
                to_address=to_override or email,
                card_path=card_path,
                values=values,
                key=key,
            )
        )
        if limit is not None and len(queue.items) >= limit:
            break

    return queue


def format_preview(cfg: Config, queue: Queue, output_dir: Path) -> str:
    """Human-readable plan of what a send would do."""
    s = cfg.smtp
    lines = [
        "Delivery plan",
        "-------------",
        f"  SMTP        : {s.host}:{s.port} ({'STARTTLS' if s.use_tls and s.port != 465 else 'SSL' if s.port == 465 else 'plaintext'})",
        f"  Login as    : {s.username or '(anonymous)'}",
        f"  From        : {s.from_name + ' <' + s.from_address + '>' if s.from_name else s.from_address}",
        f"  Cards from  : {output_dir}",
        f"  Messages    : {len(queue.items)}",
        f"  Pause       : {s.delay:g}s between messages",
    ]
    if queue.is_test:
        lines.append(f"  REDIRECTED  : every message goes to {queue.redirected_to}")
        lines.append("                (real recipients are NOT contacted, nothing is")
        lines.append("                 written to the sent log)")
    skips = []
    if queue.skipped_already_sent:
        skips.append(f"{queue.skipped_already_sent} already sent")
    if queue.skipped_no_email:
        skips.append(f"{queue.skipped_no_email} without an address")
    if queue.skipped_missing_card:
        skips.append(f"{queue.skipped_missing_card} with no card file")
    if skips:
        lines.append(f"  Skipping    : {', '.join(skips)}")

    lines.append("")
    lines.append("Queue")
    lines.append("-----")
    for item in queue.items:
        original = item.values.get("email", "")
        via = f"  (really {original})" if queue.is_test and original else ""
        lines.append(f"  {item.callsign:<10} -> {item.to_address:<30} {item.card_path.name}{via}")
    return "\n".join(lines)


def format_sample(cfg: Config, queue: Queue) -> str:
    """Render the first message's headers and body for eyeballing."""
    from qsl_send.mailer import build_message

    if not queue.items:
        return ""
    msg = build_message(
        cfg.smtp, queue.items[0], attachment_template=cfg.smtp.attachment_name
    )
    attachment = next(
        (p for p in msg.iter_attachments()), None
    )
    lines = [
        "",
        "First message (preview)",
        "-----------------------",
        f"  From    : {msg['From']}",
        f"  To      : {msg['To']}",
        f"  Subject : {msg['Subject']}",
    ]
    if attachment is not None:
        size = len(attachment.get_payload(decode=True) or b"")
        lines.append(
            f"  Attached: {attachment.get_filename()} ({size / 1024:.0f} KB, "
            f"{attachment.get_content_type()})"
        )
    lines.append("")
    body = msg.get_body(preferencelist=("plain",))
    text = body.get_content() if body else ""
    lines.extend("  | " + line for line in text.rstrip().splitlines())
    return "\n".join(lines)
