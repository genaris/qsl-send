"""Command line interface for qsl-send."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from qsl_send import __version__
from qsl_send.config import Config, ConfigError, load_config
from qsl_send.pipeline import generate_cards
from qsl_send.report import format_summary, write_manifest

DEFAULT_CONFIG_NAMES = ("qsl-send.yaml", "qsl-send.yml", "config.yaml", "config.yml")


def _find_default_config() -> Path | None:
    for name in DEFAULT_CONFIG_NAMES:
        p = Path.cwd() / name
        if p.is_file():
            return p
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qsl-send",
        description="Generate QSL cards from an ADIF log and a card template.",
    )
    parser.add_argument("--version", action="version", version=f"qsl-send {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser(
        "generate",
        help="render one card image per QSO and write the recipient manifest",
        description=(
            "Render one card image per QSO and write a manifest listing the "
            "e-mail address and file name for each recipient. No mail is sent."
        ),
    )
    gen.add_argument("-c", "--config", help="YAML config file (default: ./qsl-send.yaml)")
    gen.add_argument("-a", "--adif", help="ADIF log file")
    gen.add_argument("-t", "--template", help="QSL template image (JPEG/PNG)")
    gen.add_argument("-o", "--output-dir", help="output directory (default: ./output)")
    gen.add_argument(
        "--contacts",
        metavar="FILE",
        help="YAML address book of callsign -> e-mail, for operators the log and "
        "QRZ don't cover (overrides both)",
    )
    gen.add_argument("--limit", type=int, help="only process the first N QSOs")
    gen.add_argument(
        "--call",
        action="append",
        metavar="CALLSIGN",
        help="only this callsign (repeatable)",
    )
    gen.add_argument(
        "--qrz",
        dest="qrz",
        action="store_true",
        default=None,
        help="force QRZ.com lookups on",
    )
    gen.add_argument(
        "--no-qrz", dest="qrz", action="store_false", help="skip QRZ.com lookups"
    )
    gen.add_argument(
        "--refresh-qrz", action="store_true", help="ignore the QRZ cache and re-query"
    )
    gen.add_argument(
        "--manifest-only",
        action="store_true",
        help="resolve recipients and write the manifest without rendering images",
    )
    gen.add_argument("-q", "--quiet", action="store_true", help="only print the summary")

    check = sub.add_parser(
        "check", help="validate the config and inputs without writing anything"
    )
    check.add_argument("-c", "--config", help="YAML config file")
    check.add_argument("-a", "--adif", help="ADIF log file")
    check.add_argument("-t", "--template", help="QSL template image")

    det = sub.add_parser(
        "detect-fields",
        help="find the field boxes in a template image automatically",
        description=(
            "Locate the blank write-in boxes in a QSL template by scanning for "
            "flat rectangles of a single colour, and print them as a ready-to-"
            "paste YAML fields block. Entirely local: no network, no OCR."
        ),
    )
    det.add_argument("template", nargs="?", help="template image (default: from config)")
    det.add_argument("-c", "--config", help="YAML config file (default: ./qsl-send.yaml)")
    det.add_argument(
        "--write",
        action="store_true",
        help="write render.fields and render.template_size into the config",
    )
    det.add_argument(
        "--preview",
        metavar="FILE",
        help="save a copy of the template with detected boxes outlined and numbered",
    )
    det.add_argument(
        "--order",
        help="comma-separated field names in reading order "
        "(default: fecha,qso_con,nombre,qrg,utc,modo,rst)",
    )
    det.add_argument(
        "--search-top",
        type=float,
        default=0.55,
        help="only look below this fraction of the card height (default: 0.55)",
    )
    det.add_argument(
        "--tolerance", type=int, default=26, help="colour match tolerance (default: 26)"
    )
    det.add_argument(
        "--colour",
        metavar="RRGGBB",
        help="force the box fill colour instead of detecting it",
    )

    snd = sub.add_parser(
        "send",
        help="e-mail the cards from a previous 'generate' run",
        description=(
            "Send the cards listed in output/manifest.json. Defaults to a dry "
            "run preview; pass --confirm to actually deliver."
        ),
    )
    snd.add_argument("-c", "--config", help="YAML config file (default: ./qsl-send.yaml)")
    snd.add_argument("-o", "--output-dir", help="directory holding manifest.json + cards")
    snd.add_argument(
        "--to",
        metavar="ADDRESS",
        help="TEST MODE: send every message to this address instead of the real "
        "recipients (nothing is written to the sent log)",
    )
    snd.add_argument("--limit", type=int, help="send at most N messages")
    snd.add_argument(
        "--call", action="append", metavar="CALLSIGN", help="only this callsign (repeatable)"
    )
    snd.add_argument(
        "--confirm",
        action="store_true",
        help="actually send. Without it, send only previews the batch.",
    )
    snd.add_argument(
        "--resend",
        action="store_true",
        help="ignore the sent log and send again to recipients already mailed",
    )
    snd.add_argument(
        "--delay",
        type=float,
        help="seconds to pause between messages (default: smtp.delay in the config)",
    )
    return parser


def _resolve_inputs(args: argparse.Namespace) -> tuple[Config, Path, Path, Path]:
    config_path = Path(args.config) if args.config else _find_default_config()
    cfg = load_config(config_path)

    adif = Path(args.adif).expanduser() if args.adif else cfg.resolve(cfg.adif)
    if not adif:
        raise ConfigError("No ADIF file given. Use --adif or set 'adif' in the config.")
    if not adif.is_file():
        raise ConfigError(f"ADIF file not found: {adif}")

    template = (
        Path(args.template).expanduser() if args.template else cfg.resolve(cfg.template)
    )
    if not template:
        raise ConfigError(
            "No template image given. Use --template or set 'template' in the config."
        )
    if not template.is_file():
        raise ConfigError(f"Template image not found: {template}")

    out_raw = getattr(args, "output_dir", None) or cfg.output_dir
    output = Path(out_raw).expanduser()
    if not output.is_absolute() and not getattr(args, "output_dir", None):
        output = cfg.resolve(str(output)) or output
    return cfg, adif, template, output


def _load_contacts_for(cfg: Config, args: argparse.Namespace):
    """-> (contacts by base callsign, source path or None, warnings)"""
    from qsl_send.contacts import load_contacts

    raw = getattr(args, "contacts", None)
    path = Path(raw).expanduser() if raw else cfg.resolve(cfg.contacts_file)
    if path is None:
        return {}, None, []
    contacts, warnings = load_contacts(path)
    return contacts, path, warnings


def cmd_generate(args: argparse.Namespace) -> int:
    from qsl_send.contacts import ContactsError

    cfg, adif, template, output = _resolve_inputs(args)
    say = (lambda _m: None) if args.quiet else (lambda m: print(m))

    try:
        contacts, contacts_path, contact_warnings = _load_contacts_for(cfg, args)
    except ContactsError as exc:
        raise ConfigError(str(exc)) from exc

    if not args.quiet:
        print(f"Template : {template}")
        print(f"ADIF     : {adif}")
        if contacts_path:
            print(f"Contacts : {contacts_path} — {len(contacts)} override(s)")
        print(f"Output   : {output}")
        print()

    summary = generate_cards(
        cfg,
        adif_path=adif,
        template_path=template,
        output_dir=output,
        limit=args.limit,
        only_calls=set(args.call) if args.call else None,
        use_qrz=args.qrz,
        refresh_qrz=args.refresh_qrz,
        render_images=not args.manifest_only,
        contacts=contacts,
        progress=say,
    )
    summary.warnings.extend(contact_warnings)

    paths = write_manifest(summary, output)
    print(format_summary(summary, output))
    print(f"  Manifest             : {paths['csv']}")
    print(f"                         {paths['json']}")
    if not summary.results:
        print("\nNothing matched — check --call/--limit or the ADIF contents.")
        return 1
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from qsl_send.adif import read_adif
    from qsl_send.render import CardRenderer

    cfg, adif, template, output = _resolve_inputs(args)
    qsos = read_adif(adif)
    renderer = CardRenderer(template, cfg.render)

    print(f"Config    : {cfg.path or '(defaults)'}")
    print(f"ADIF      : {adif} — {len(qsos)} QSO(s)")
    print(
        f"Template  : {template} — {renderer.template.width}x{renderer.template.height} px"
    )
    print(f"Font      : {cfg.render.font}")
    print(f"Output    : {output}")
    print(f"QRZ       : {'enabled' if cfg.qrz.enabled else 'disabled'}")
    print(f"SMTP      : {cfg.smtp.host or '(not configured)'}")
    print("\nFields:")
    for spec in cfg.render.fields:
        x, y, w, h = spec.box
        print(f"  {spec.name:<10} box=({x},{y},{w}x{h}) value={spec.value!r}")
    with_email = sum(1 for q in qsos if q.get("email").strip())
    print(f"\nQSOs with an <email> field in the log: {with_email}/{len(qsos)}")
    if renderer.scaled:
        print(
            "\nNote: template size differs from render.template_size; "
            "field boxes will be scaled."
        )
    return 0


def cmd_detect_fields(args: argparse.Namespace) -> int:
    from qsl_send.detect import DEFAULT_ORDER, detect_boxes, name_boxes

    config_path = Path(args.config) if args.config else _find_default_config()
    cfg = load_config(config_path)

    template = (
        Path(args.template).expanduser() if args.template else cfg.resolve(cfg.template)
    )
    if not template:
        raise ConfigError(
            "No template given. Pass one as an argument or set 'template' in the config."
        )
    if not template.is_file():
        raise ConfigError(f"Template image not found: {template}")

    forced = None
    if args.colour:
        raw = args.colour.lstrip("#")
        if len(raw) != 6:
            raise ConfigError("--colour must be six hex digits, e.g. 00AFF0")
        try:
            forced = tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))
        except ValueError as exc:
            raise ConfigError(f"--colour is not valid hex: {args.colour}") from exc

    detection = detect_boxes(
        template,
        search_top=args.search_top,
        tolerance=args.tolerance,
        colour=forced,  # type: ignore[arg-type]
    )
    if not detection.boxes:
        print(
            f"No field boxes found in {template}.\n"
            "The detector looks for flat rectangles of one colour in the lower "
            f"{100 - int(args.search_top * 100)}% of the card. Try --search-top 0.3, "
            "a larger --tolerance, or --colour RRGGBB to name the fill directly.",
            file=sys.stderr,
        )
        return 1

    order = [n.strip() for n in args.order.split(",")] if args.order else None
    named = name_boxes(detection, order)
    r, g, b = detection.colour

    print(f"Template : {template} ({detection.size[0]}x{detection.size[1]})")
    print(f"Fill     : #{r:02X}{g:02X}{b:02X}")
    print(f"Rows     : {detection.rows}    Boxes: {len(detection.boxes)}")
    print()
    print("  #  row  box                        name")
    for i, (box, name, _value) in enumerate(named):
        print(f"  {i}  {box.row:<3}  {str(box.box):<25}  {name}")

    expected = len(order or DEFAULT_ORDER)
    if len(detection.boxes) != expected:
        print(
            f"\n! Found {len(detection.boxes)} boxes but expected {expected}. "
            "Check the list above before using it.",
            file=sys.stderr,
        )

    print()
    print("Names come from reading order, not from the card — verify they match.")
    print()
    yaml_block = _fields_yaml(named, detection.size)
    print(yaml_block)

    if args.preview:
        _save_preview(template, named, Path(args.preview))
        print(f"Preview written to {args.preview}")

    if args.write:
        if cfg.path is None:
            raise ConfigError("--write needs a config file; none was found.")
        _write_fields(cfg.path, detection, yaml_block)
        print(f"Wrote render.template_size and render.fields to {cfg.path}")
        print("Now run: qsl-send generate --limit 1   and check the card.")
    return 0


def _fields_yaml(named, size: tuple[int, int]) -> str:
    lines = [
        f"  template_size: [{size[0]}, {size[1]}]",
        "  fields:",
    ]
    for box, name, value in named:
        lines.append(f"    - name: {name}")
        lines.append(f"      box: {box.box}")
        if value:
            lines.append(f'      value: "{value}"')
    return "\n".join(lines)


def _save_preview(template: Path, named, out: Path) -> None:
    from PIL import Image, ImageDraw

    img = Image.open(template).convert("RGB")
    draw = ImageDraw.Draw(img)
    for i, (box, name, _v) in enumerate(named):
        x, y, w, h = box.box
        draw.rectangle([x - 2, y - 2, x + w + 2, y + h + 2], outline=(255, 0, 0), width=3)
        draw.text((x + 4, max(0, y - 18)), f"{i} {name}", fill=(255, 0, 0))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)


def _write_fields(config_path: Path, detection, yaml_block: str) -> None:
    """Replace render.template_size and render.fields in the config in place."""
    text = config_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    out: list[str] = []
    i = 0
    replaced = False
    while i < len(lines):
        line = lines[i]
        if not replaced and line.strip().startswith("template_size:"):
            out.extend(yaml_block.splitlines())
            i += 1
            # Skip everything through the end of the existing fields list.
            while i < len(lines):
                nxt = lines[i]
                stripped = nxt.strip()
                if stripped.startswith("fields:"):
                    i += 1
                    while i < len(lines):
                        f = lines[i]
                        if f.strip() and not f.startswith(("    -", "      ", "    #")):
                            break
                        i += 1
                    break
                if stripped and not nxt.startswith(("  #", "    ", "      ")):
                    break
                i += 1
            replaced = True
            continue
        out.append(line)
        i += 1

    if not replaced:
        raise ConfigError(
            "Could not find 'template_size:' under render: in the config; "
            "paste the fields block above in by hand."
        )
    config_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _output_dir_for(cfg: Config, args: argparse.Namespace) -> Path:
    raw = getattr(args, "output_dir", None) or cfg.output_dir
    out = Path(raw).expanduser()
    if not out.is_absolute() and not getattr(args, "output_dir", None):
        out = cfg.resolve(str(out)) or out
    return out


def cmd_send(args: argparse.Namespace) -> int:
    from qsl_send.mailer import MailError, SentLog, deliver
    from qsl_send.sending import SendError, build_queue, format_preview, format_sample

    config_path = Path(args.config) if args.config else _find_default_config()
    cfg = load_config(config_path)
    output = _output_dir_for(cfg, args)

    if not cfg.smtp.host:
        raise ConfigError("smtp.host is not set — nothing to send through.")

    sent_log = SentLog(output / "sent.json")
    queue = build_queue(
        cfg,
        output,
        to_override=(args.to or "").strip(),
        limit=args.limit,
        only_calls=set(args.call) if args.call else None,
        resend=args.resend,
        sent_log=sent_log,
    )

    print(format_preview(cfg, queue, output))
    print(format_sample(cfg, queue))

    if not queue.items:
        print("\nNothing to send.")
        return 0

    if not args.confirm:
        target = queue.redirected_to or "the recipients listed above"
        print(
            f"\nDry run — no mail was sent. Re-run with --confirm to deliver "
            f"{len(queue.items)} message(s) to {target}."
        )
        return 0

    delay = args.delay if args.delay is not None else cfg.smtp.delay
    print(f"\nSending {len(queue.items)} message(s)…\n")
    try:
        outcomes = deliver(
            cfg.smtp,
            queue.items,
            attachment_template=cfg.smtp.attachment_name,
            # A redirected test run must not mark real recipients as done.
            sent_log=None if queue.is_test else sent_log,
            delay=delay,
            progress=lambda m: print(m),
        )
    except MailError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1

    sent = sum(1 for o in outcomes if o.status == "sent")
    failed = [o for o in outcomes if o.status == "failed"]
    print(f"\nSent {sent}/{len(outcomes)} message(s).")
    if queue.is_test:
        print(f"Test run: everything went to {queue.redirected_to}; sent log untouched.")
    elif sent:
        print(f"Recorded in {output / 'sent.json'} — a re-run will skip these.")
    if failed:
        print("\nFailures:")
        for o in failed:
            print(f"  {o.callsign} -> {o.to_address}: {o.detail}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "generate": cmd_generate,
        "check": cmd_check,
        "send": cmd_send,
        "detect-fields": cmd_detect_fields,
    }
    try:
        return handlers[args.command](args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # SendError and friends carry actionable messages
        from qsl_send.sending import SendError

        if not isinstance(exc, SendError):
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
