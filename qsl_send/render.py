"""Draw QSL card text onto the template image."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from qsl_send.config import ConfigError, FieldSpec, RenderConfig
from qsl_send.fields import format_template


@lru_cache(maxsize=64)
def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError as exc:
        raise ConfigError(f"Cannot load font '{path}': {exc}") from exc


def _text_size(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont
) -> tuple[int, int, int, int]:
    """Return (width, height, offset_x, offset_y) of the inked bounding box."""
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top, left, top


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: str,
    max_size: int,
    min_size: int,
    max_w: int,
    max_h: int,
) -> ImageFont.FreeTypeFont:
    """Largest size in [min_size, max_size] whose text fits the box."""
    size = max(min_size, max_size)
    while size > min_size:
        font = _load_font(font_path, size)
        w, h, _, _ = _text_size(draw, text, font)
        if w <= max_w and h <= max_h:
            return font
        size -= 1
    return _load_font(font_path, min_size)


class CardRenderer:
    """Renders one card per QSO from a single template image."""

    def __init__(self, template_path: str | Path, render: RenderConfig):
        self.render = render
        path = Path(template_path)
        if not path.is_file():
            raise ConfigError(f"Template image not found: {path}")
        try:
            self.template = Image.open(path).convert("RGB")
        except OSError as exc:
            raise ConfigError(f"Cannot open template '{path}': {exc}") from exc

        ref_w, ref_h = render.template_size
        self.scale_x = self.template.width / ref_w if ref_w else 1.0
        self.scale_y = self.template.height / ref_h if ref_h else 1.0

    @property
    def scaled(self) -> bool:
        return abs(self.scale_x - 1.0) > 1e-6 or abs(self.scale_y - 1.0) > 1e-6

    def _scale_box(self, box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x, y, w, h = box
        return (
            round(x * self.scale_x),
            round(y * self.scale_y),
            round(w * self.scale_x),
            round(h * self.scale_y),
        )

    def _draw_field(
        self,
        draw: ImageDraw.ImageDraw,
        spec: FieldSpec,
        values: dict[str, str],
    ) -> None:
        text = format_template(spec.value, values).strip()
        if spec.uppercase:
            text = text.upper()
        if spec.max_chars and len(text) > spec.max_chars:
            text = text[: max(1, spec.max_chars - 1)].rstrip() + "…"
        if not text:
            return

        x, y, w, h = self._scale_box(spec.box)
        pad = round(spec.padding * self.scale_x)
        inner_w = max(1, w - 2 * pad)
        inner_h = max(1, h - 2 * pad)

        font_path = spec.font or self.render.font
        max_size = spec.max_font_size or int(inner_h)
        min_size = max(4, round(spec.min_font_size * self.scale_y))
        max_size = max(min_size, round(max_size * self.scale_y) if spec.max_font_size else max_size)

        if spec.fit == "clip":
            font = _load_font(font_path, max_size)
        else:
            font = _fit_font(draw, text, font_path, max_size, min_size, inner_w, inner_h)

        tw, th, ox, oy = _text_size(draw, text, font)

        if spec.align == "left":
            tx = x + pad
        elif spec.align == "right":
            tx = x + w - pad - tw
        else:
            tx = x + (w - tw) / 2

        if spec.valign == "top":
            ty = y + pad
        elif spec.valign == "bottom":
            ty = y + h - pad - th
        else:
            ty = y + (h - th) / 2

        draw.text((tx - ox, ty - oy), text, font=font, fill=spec.color)

    def render_card(self, values: dict[str, str]) -> Image.Image:
        """Return a new card image with every configured field drawn."""
        card = self.template.copy()
        draw = ImageDraw.Draw(card)
        for spec in self.render.fields:
            self._draw_field(draw, spec, values)

        if self.render.max_width and card.width > self.render.max_width:
            ratio = self.render.max_width / card.width
            card = card.resize(
                (self.render.max_width, round(card.height * ratio)),
                Image.LANCZOS,
            )
        return card

    def save(self, card: Image.Image, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.render.format == "png":
            card.save(path, format="PNG", optimize=True)
        else:
            card.save(path, format="JPEG", quality=self.render.quality, subsampling=1)

    @property
    def extension(self) -> str:
        return ".png" if self.render.format == "png" else ".jpg"
