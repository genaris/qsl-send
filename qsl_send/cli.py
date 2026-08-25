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
    handlers = {"generate": cmd_generate, "check": cmd_check, "send": cmd_send}
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
