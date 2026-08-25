"""Configuration loading for qsl-send.

The config is YAML.  Anything the CLI accepts as a flag can also live here;
CLI flags win.  Secrets may be written as ``${ENV_VAR}`` and are expanded from
the environment (and from a ``.env`` file next to the config, if present).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    """Raised for a malformed or incomplete configuration."""


# Field boxes measured on the reference template QSL_LU2AOG.jpg (1583x1061).
# They are scaled automatically if the template has different pixel dimensions.
DEFAULT_TEMPLATE_SIZE = (1583, 1061)
DEFAULT_FIELDS: list[dict[str, Any]] = [
    {"name": "date", "box": [101, 950, 166, 42], "value": "{date}"},
    {"name": "qso_with", "box": [284, 952, 168, 41], "value": "{callsign}"},
    {"name": "name", "box": [463, 951, 291, 42], "value": "{name}"},
    {"name": "qrg", "box": [767, 952, 150, 40], "value": "{qrg}"},
    {"name": "utc", "box": [926, 954, 150, 38], "value": "{utc}"},
    {"name": "mode", "box": [1088, 950, 64, 42], "value": "{mode}"},
    {"name": "rst", "box": [1170, 958, 71, 34], "value": "{rst}"},
]

_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


@dataclass
class FieldSpec:
    """One text box printed on the card."""

    name: str
    box: tuple[int, int, int, int]  # x, y, width, height in template pixels
    value: str = ""
    align: str = "center"  # left | center | right
    valign: str = "center"  # top | center | bottom
    font: str | None = None
    color: str = "#0b2d5c"
    max_font_size: int | None = None
    min_font_size: int = 8
    padding: int = 4
    uppercase: bool = False
    fit: str = "shrink"  # shrink | clip
    max_chars: int | None = None


@dataclass
class RenderConfig:
    font: str = ""
    color: str = "#0b2d5c"
    format: str = "jpeg"  # jpeg | png
    quality: int = 92
    max_width: int | None = None  # downscale the finished card, if set
    filename: str = "{callsign}_{date_iso}_{utc_raw}"
    fields: list[FieldSpec] = field(default_factory=list)
    template_size: tuple[int, int] = DEFAULT_TEMPLATE_SIZE


@dataclass
class QrzConfig:
    enabled: bool = False
    username: str = ""
    password: str = ""
    api_key: str = ""  # optional QRZ Logbook key (unused for XML lookups)
    agent: str = "qsl-send"
    cache_file: str = ".qrz-cache.json"
    timeout: int = 15
    # Where the recipient address comes from: prefer the ADIF <email> field or
    # the QRZ record.  The other one is used as fallback.
    prefer: str = "adif"  # adif | qrz


@dataclass
class SmtpConfig:
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    use_tls: bool = True  # STARTTLS on 587; port 465 always uses implicit SSL
    from_address: str = ""
    from_name: str = ""
    reply_to: str = ""
    subject: str = "QSL {my_callsign} <-> {callsign}"
    body: str = ""
    timeout: int = 30
    delay: float = 2.0  # seconds between messages, to stay under rate limits
    attachment_name: str = "QSL_{my_callsign}_{callsign}"


@dataclass
class Config:
    template: str = ""
    adif: str = ""
    output_dir: str = "output"
    contacts_file: str = ""  # local address-book overrides; see contacts.py
    my_callsign: str = ""
    date_format: str = "%d/%m/%Y"
    time_format: str = "%H:%M"
    qrg_decimals: int = 3
    skip_without_email: bool = False
    group_by: str = "qso"  # qso | callsign
    render: RenderConfig = field(default_factory=RenderConfig)
    qrz: QrzConfig = field(default_factory=QrzConfig)
    smtp: SmtpConfig = field(default_factory=SmtpConfig)
    path: Path | None = None

    def resolve(self, value: str | None) -> Path | None:
        """Resolve a path from the config relative to the config file."""
        if not value:
            return None
        p = Path(value).expanduser()
        if p.is_absolute() or self.path is None:
            return p
        return (self.path.parent / p).resolve()


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip("'\""))


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def default_font() -> str:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    raise ConfigError(
        "No default font found. Set render.font in the config to a .ttf/.otf path."
    )


def _field_from_dict(raw: dict[str, Any], defaults: RenderConfig) -> FieldSpec:
    name = raw.get("name")
    if not name:
        raise ConfigError(f"Every render.fields entry needs a 'name': {raw!r}")
    box = raw.get("box")
    if not (isinstance(box, (list, tuple)) and len(box) == 4):
        raise ConfigError(f"Field '{name}': 'box' must be [x, y, width, height]")
    try:
        box_t = tuple(int(v) for v in box)  # type: ignore[assignment]
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Field '{name}': box values must be integers") from exc
    align = str(raw.get("align", "center")).lower()
    if align not in {"left", "center", "right"}:
        raise ConfigError(f"Field '{name}': align must be left|center|right")
    valign = str(raw.get("valign", "center")).lower()
    if valign not in {"top", "center", "bottom"}:
        raise ConfigError(f"Field '{name}': valign must be top|center|bottom")
    return FieldSpec(
        name=str(name),
        box=box_t,  # type: ignore[arg-type]
        value=str(raw.get("value", "")),
        align=align,
        valign=valign,
        font=raw.get("font") or None,
        color=str(raw.get("color", defaults.color)),
        max_font_size=raw.get("max_font_size"),
        min_font_size=int(raw.get("min_font_size", 8)),
        padding=int(raw.get("padding", 4)),
        uppercase=bool(raw.get("uppercase", False)),
        fit=str(raw.get("fit", "shrink")).lower(),
        max_chars=raw.get("max_chars"),
    )


def load_config(path: str | Path | None) -> Config:
    """Load a YAML config; an absent path yields defaults."""
    cfg = Config()
    data: dict[str, Any] = {}

    if path is not None:
        p = Path(path).expanduser()
        if not p.is_file():
            raise ConfigError(f"Config file not found: {p}")
        _load_dotenv(p.parent / ".env")
        loaded = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ConfigError(f"{p}: top level of the config must be a mapping")
        data = _expand(loaded)
        cfg.path = p.resolve()

    for key in (
        "template",
        "adif",
        "output_dir",
        "contacts_file",
        "my_callsign",
        "date_format",
        "time_format",
    ):
        if data.get(key) is not None:
            setattr(cfg, key, str(data[key]))
    if data.get("qrg_decimals") is not None:
        cfg.qrg_decimals = int(data["qrg_decimals"])
    cfg.skip_without_email = bool(data.get("skip_without_email", False))
    cfg.group_by = str(data.get("group_by", "qso")).lower()
    if cfg.group_by not in {"qso", "callsign"}:
        raise ConfigError("group_by must be 'qso' or 'callsign'")

    render_raw = data.get("render") or {}
    if not isinstance(render_raw, dict):
        raise ConfigError("'render' must be a mapping")
    r = cfg.render
    r.font = str(render_raw.get("font") or "") or default_font()
    r.color = str(render_raw.get("color", r.color))
    r.format = str(render_raw.get("format", r.format)).lower()
    if r.format not in {"jpeg", "jpg", "png"}:
        raise ConfigError("render.format must be jpeg or png")
    r.format = "jpeg" if r.format == "jpg" else r.format
    r.quality = int(render_raw.get("quality", r.quality))
    r.max_width = render_raw.get("max_width")
    if r.max_width is not None:
        r.max_width = int(r.max_width)
    r.filename = str(render_raw.get("filename", r.filename))
    size = render_raw.get("template_size")
    if size:
        if not (isinstance(size, (list, tuple)) and len(size) == 2):
            raise ConfigError("render.template_size must be [width, height]")
        r.template_size = (int(size[0]), int(size[1]))

    raw_fields = render_raw.get("fields")
    if raw_fields is None:
        raw_fields = DEFAULT_FIELDS
    if not isinstance(raw_fields, list) or not raw_fields:
        raise ConfigError("render.fields must be a non-empty list")
    r.fields = [_field_from_dict(f, r) for f in raw_fields]

    qrz_raw = data.get("qrz") or {}
    if not isinstance(qrz_raw, dict):
        raise ConfigError("'qrz' must be a mapping")
    q = cfg.qrz
    q.enabled = bool(qrz_raw.get("enabled", False))
    q.username = str(qrz_raw.get("username", ""))
    q.password = str(qrz_raw.get("password", ""))
    q.api_key = str(qrz_raw.get("api_key", ""))
    q.agent = str(qrz_raw.get("agent", q.agent))
    q.cache_file = str(qrz_raw.get("cache_file", q.cache_file))
    q.timeout = int(qrz_raw.get("timeout", q.timeout))
    q.prefer = str(qrz_raw.get("prefer", q.prefer)).lower()
    if q.prefer not in {"adif", "qrz"}:
        raise ConfigError("qrz.prefer must be 'adif' or 'qrz'")

    smtp_raw = data.get("smtp") or {}
    if not isinstance(smtp_raw, dict):
        raise ConfigError("'smtp' must be a mapping")
    s = cfg.smtp
    s.host = str(smtp_raw.get("host", ""))
    s.port = int(smtp_raw.get("port", s.port))
    s.username = str(smtp_raw.get("username", ""))
    s.password = str(smtp_raw.get("password", ""))
    s.use_tls = bool(smtp_raw.get("use_tls", True))
    s.from_address = str(smtp_raw.get("from_address", ""))
    s.from_name = str(smtp_raw.get("from_name", ""))
    s.reply_to = str(smtp_raw.get("reply_to", ""))
    s.subject = str(smtp_raw.get("subject", s.subject))
    s.body = str(smtp_raw.get("body", ""))
    s.timeout = int(smtp_raw.get("timeout", s.timeout))
    s.delay = float(smtp_raw.get("delay", s.delay))
    s.attachment_name = str(smtp_raw.get("attachment_name", s.attachment_name))

    return cfg
