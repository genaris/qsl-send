"""Wire the pieces together: ADIF -> recipient resolution -> card images."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from qsl_send.adif import Qso, base_callsign, read_adif
from qsl_send.config import Config
from qsl_send.contacts import Contact
from qsl_send.fields import format_template, placeholders
from qsl_send.i18n import t
from qsl_send.qrz import QrzClient, QrzError, QrzRecord, valid_email
from qsl_send.render import CardRenderer

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class CardResult:
    """One row of the run report: what was generated and for whom."""

    callsign: str
    name: str = ""
    email: str = ""
    email_source: str = "none"  # adif | qrz | none
    name_source: str = "adif"  # adif | qrz | none
    qso_date: str = ""
    time_on: str = ""
    mode: str = ""
    band: str = ""
    freq: str = ""
    rst_sent: str = ""
    card_file: str = ""
    status: str = "ok"  # ok | no_email | no_name | error
    notes: str = ""
    qso_count: int = 1
    # Placeholder values for this QSO. Carried in manifest.json (not the CSV) so
    # `send` can render the subject/body without re-reading the ADIF.
    values: dict[str, str] = field(default_factory=dict)

    @property
    def sendable(self) -> bool:
        """Whether this card would actually be e-mailed.

        Must match what build_queue() does: it needs an address and a rendered
        card, and nothing else. In particular a missing *name* does not block
        delivery — the greeting just falls back to the callsign — so `no_name`
        is still sendable. Only a missing address or a render error is not.
        """
        return bool(self.email) and self.status != "error"


@dataclass
class RunSummary:
    results: list[CardResult] = field(default_factory=list)
    qsos_read: int = 0
    cards_written: int = 0
    qrz_queried: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def with_email(self) -> int:
        return sum(1 for r in self.results if r.email)

    @property
    def without_email(self) -> int:
        return sum(1 for r in self.results if not r.email)

    @property
    def errors(self) -> int:
        return sum(1 for r in self.results if r.status == "error")

    @property
    def without_name(self) -> int:
        return sum(1 for r in self.results if r.status == "no_name")

    @property
    def needing_contacts(self) -> list[str]:
        """Callsigns whose name or address could be filled in by hand."""
        return [r.callsign for r in self.results
                if r.status in ("no_email", "no_name")]


def safe_filename(stem: str, fallback: str = "card") -> str:
    cleaned = _UNSAFE.sub("_", stem).strip("._-")
    return cleaned or fallback


def select_qsos(qsos: Iterable[Qso], group_by: str) -> list[Qso]:
    """One card per QSO, or the first QSO per callsign."""
    qsos = list(qsos)
    if group_by != "callsign":
        return qsos
    seen: dict[str, Qso] = {}
    for q in qsos:
        key = base_callsign(q.call)
        if key and key not in seen:
            seen[key] = q
    return list(seen.values())


def _resolve_contact(
    qso: Qso, qrz_record: QrzRecord | None, prefer: str, override: Contact | None = None
) -> tuple[str, str, str, str, str]:
    """-> (name, name_source, email, email_source, note)

    A contacts-file entry wins over both the ADIF and QRZ: it was curated by
    hand, so it is the most trustworthy source available.
    """
    adif_name = qso.get("name").strip()
    adif_email = qso.get("email").strip()
    if not valid_email(adif_email):
        # Some logs put the address in <qsl_via>; accept it if it looks like one.
        via = qso.get("qsl_via").strip()
        adif_email = via if valid_email(via) else ""

    qrz_name = qrz_record.name.strip() if qrz_record else ""
    qrz_email = qrz_record.email.strip() if qrz_record else ""
    if not valid_email(qrz_email):
        qrz_email = ""

    order = [("qrz", qrz_email), ("adif", adif_email)]
    if prefer == "adif":
        order.reverse()
    if override and override.email:
        order.insert(0, ("override", override.email))
    email, email_source = "", "none"
    for source, value in order:
        if value:
            email, email_source = value, source
            break

    name_order = [("qrz", qrz_name), ("adif", adif_name)]
    if prefer == "adif":
        name_order.reverse()
    if override and override.name:
        name_order.insert(0, ("override", override.name))
    name, name_source = "", "none"
    for source, value in name_order:
        if value:
            name, name_source = value, source
            break

    note = ""
    if qrz_record and qrz_record.error:
        note = f"qrz: {qrz_record.error}"
    return name, name_source, email, email_source, note


def _fit_fields_to_template(
    cfg: Config,
    template_path: Path,
    summary: "RunSummary",
    say: Callable[[str], None],
) -> None:
    """Locate the field boxes on the card actually being used.

    Box coordinates are pixels of one particular image, so reusing them for a
    different card only scales them and the text lands off the boxes. Choosing
    a template is a request to find *its* boxes, so they are located here
    rather than trusted from the configuration.

    Detection is a heuristic — it looks for flat rectangles of a single colour
    — so when it cannot find them the configured boxes are kept as a fallback
    and the run says so, rather than producing obviously broken cards.
    """
    from qsl_send.detect import DEFAULT_ORDER, detect_boxes

    try:
        from PIL import Image

        with Image.open(template_path) as img:
            actual_size = img.size
    except Exception:
        return

    if tuple(actual_size) == tuple(cfg.render.template_size):
        return  # the configured boxes already belong to this card

    expected = len(cfg.render.fields) or len(DEFAULT_ORDER)
    try:
        detection = detect_boxes(template_path)
    except Exception as exc:
        detection = None
        say(t("! Could not inspect {name}: {error}",
                name=template_path.name, error=exc))

    if detection is None or len(detection.boxes) != expected:
        found = 0 if detection is None else len(detection.boxes)
        summary.warnings.append(t(
            "{name} is {actual}, but the saved field boxes were measured on "
            "{saved}. Automatic detection found {found} box(es) instead of "
            "{expected}, so the saved boxes were scaled to fit — check one "
            "card before sending.",
            name=template_path.name,
            actual=f"{actual_size[0]}x{actual_size[1]}",
            saved=f"{cfg.render.template_size[0]}x{cfg.render.template_size[1]}",
            found=found, expected=expected,
        ))
        return

    # Keep each field's configured name and value; take only the geometry.
    for spec, box in zip(cfg.render.fields, detection.boxes):
        spec.box = tuple(box.box)  # type: ignore[assignment]
    cfg.render.template_size = detection.size
    say(t("Located {count} field box(es) on {name} ({size})",
          count=len(detection.boxes), name=template_path.name,
          size=f"{actual_size[0]}x{actual_size[1]}"))


def generate_cards(
    cfg: Config,
    *,
    adif_path: Path,
    template_path: Path,
    output_dir: Path,
    limit: int | None = None,
    only_calls: set[str] | None = None,
    use_qrz: bool | None = None,
    refresh_qrz: bool = False,
    render_images: bool = True,
    contacts: dict[str, Contact] | None = None,
    progress: Callable[[str], None] | None = None,
) -> RunSummary:
    """Read the log, resolve recipients and write one card image per QSO."""
    say = progress or (lambda _msg: None)
    summary = RunSummary()

    qsos = read_adif(adif_path)
    summary.qsos_read = len(qsos)
    say(t("Read {count} QSO(s) from {name}",
            count=len(qsos), name=adif_path.name))

    selected = select_qsos(qsos, cfg.group_by)
    if only_calls:
        wanted = {c.upper() for c in only_calls}
        selected = [
            q for q in selected if q.call in wanted or base_callsign(q.call) in wanted
        ]
    if limit is not None:
        selected = selected[:limit]

    counts: dict[str, int] = {}
    for q in qsos:
        key = base_callsign(q.call)
        counts[key] = counts.get(key, 0) + 1

    # QRZ lookups, batched up front so the cache is written once.
    qrz_enabled = cfg.qrz.enabled if use_qrz is None else use_qrz
    records: dict[str, QrzRecord] = {}
    if qrz_enabled and selected:
        calls = sorted({base_callsign(q.call) for q in selected if q.call})
        say(t("Looking up {count} callsign(s) on QRZ.com…", count=len(calls)))
        cache_path = cfg.resolve(cfg.qrz.cache_file) or Path(cfg.qrz.cache_file)
        client = QrzClient(cfg.qrz, cache_path=cache_path)
        try:
            client.login()
        except QrzError as exc:
            summary.warnings.append(
                t("QRZ disabled for this run: {error}", error=exc))
            say(f"! {exc}")
            qrz_enabled = False
        if qrz_enabled:
            before = len(client._cache)  # noqa: SLF001 - internal, for reporting only
            records = client.lookup_many(calls, use_cache=not refresh_qrz)
            summary.qrz_queried = max(0, len(client._cache) - before)  # noqa: SLF001
            failed = [c for c, r in records.items() if r.error]
            if failed:
                summary.warnings.append(t(
                    "{count} QRZ lookup(s) returned no data: {calls}",
                    count=len(failed),
                    calls=", ".join(failed[:10]) + ("…" if len(failed) > 10 else ""),
                ))

    if render_images:
        _fit_fields_to_template(cfg, template_path, summary, say)
    renderer = CardRenderer(template_path, cfg.render) if render_images else None

    used_names: set[str] = set()
    for qso in selected:
        call = qso.call or "UNKNOWN"
        record = records.get(base_callsign(call))
        override = (contacts or {}).get(base_callsign(call))
        name, name_source, email, email_source, note = _resolve_contact(
            qso, record, cfg.qrz.prefer, override
        )

        result = CardResult(
            callsign=call,
            name=name,
            email=email,
            email_source=email_source,
            name_source=name_source if name else "none",
            qso_date=qso.get("qso_date"),
            time_on=qso.get("time_on"),
            mode=qso.get("mode").upper(),
            band=qso.get("band").lower(),
            freq=qso.get("freq"),
            rst_sent=qso.get("rst_sent"),
            notes=note,
            qso_count=counts.get(base_callsign(call), 1),
        )
        if not email:
            result.status = "no_email"
        elif not name:
            # Se puede enviar, pero el saludo caería en el indicativo. Vale la
            # pena avisar para que se pueda completar en la libreta.
            result.status = "no_name"

        if cfg.skip_without_email and not email:
            result.notes = "; ".join(filter(None, [result.notes, "skipped: no e-mail"]))
            summary.results.append(result)
            say(t("- {callsign}: no e-mail, card skipped", callsign=call))
            continue

        values = placeholders(
            qso,
            date_format=cfg.date_format,
            time_format=cfg.time_format,
            qrg_decimals=cfg.qrg_decimals,
            name=name or None,
            email=email,
            my_callsign=cfg.my_callsign,
        )
        result.values = values

        if renderer is not None:
            stem = safe_filename(format_template(cfg.render.filename, values), call)
            candidate = stem
            n = 2
            while candidate.lower() in used_names:
                candidate = f"{stem}_{n}"
                n += 1
            used_names.add(candidate.lower())
            out_path = output_dir / "cards" / f"{candidate}{renderer.extension}"
            try:
                renderer.save(renderer.render_card(values), out_path)
            except (OSError, ValueError) as exc:
                result.status = "error"
                result.notes = "; ".join(filter(None, [result.notes, f"render: {exc}"]))
                summary.results.append(result)
                say(f"! {call}: {exc}")
                continue
            result.card_file = str(out_path.relative_to(output_dir))
            summary.cards_written += 1

        summary.results.append(result)
        say(f"+ {call:<10} {email or '(no e-mail)':<32} {result.card_file}")

    return summary
