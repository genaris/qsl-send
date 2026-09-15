"""Write the run report: which card goes to which address."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from qsl_send.i18n import t
from qsl_send.pipeline import RunSummary

CSV_COLUMNS = [
    "callsign",
    "name",
    "email",
    "email_source",
    "name_source",
    "qso_date",
    "time_on",
    "mode",
    "band",
    "freq",
    "rst_sent",
    "qso_count",
    "card_file",
    "status",
    "notes",
]


def write_manifest(summary: RunSummary, output_dir: Path, *, stem: str = "manifest") -> dict[str, Path]:
    """Write manifest.csv and manifest.json; return the paths written."""
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{stem}.csv"
    json_path = output_dir / f"{stem}.json"

    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for result in summary.results:
            writer.writerow(asdict(result))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "qsos_read": summary.qsos_read,
        "cards_written": summary.cards_written,
        "recipients_with_email": summary.with_email,
        "recipients_without_email": summary.without_email,
        "errors": summary.errors,
        "qrz_lookups": summary.qrz_queried,
        "warnings": summary.warnings,
        "cards": [asdict(r) for r in summary.results],
    }
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {"csv": csv_path, "json": json_path}


def format_summary(summary: RunSummary, output_dir: Path) -> str:
    lines = [
        "",
        t("Summary"),
        "-------",
        t("  QSOs in log          : {n}", n=summary.qsos_read),
        t("  Cards generated      : {n}", n=summary.cards_written),
        t("  Ready to e-mail      : {n}", n=summary.with_email),
        t("  Missing an address   : {n}", n=summary.without_email),
    ]
    if summary.without_name:
        lines.append(t("  No name logged       : {n}", n=summary.without_name))
    if summary.errors:
        lines.append(t("  Errors               : {n}", n=summary.errors))
    if summary.qrz_queried:
        lines.append(t("  New QRZ lookups      : {n}", n=summary.qrz_queried))
    lines.append(t("  Output               : {path}", path=output_dir))
    if summary.warnings:
        lines.append("")
        lines.append("Warnings")
        lines.append("--------")
        lines.extend(f"  ! {w}" for w in summary.warnings)
    missing = [r.callsign for r in summary.results if not r.email]
    if missing:
        lines.append("")
        shown = ", ".join(missing[:15]) + ("…" if len(missing) > 15 else "")
        lines.append(t("No e-mail address for: {calls}", calls=shown))
    return "\n".join(lines)
