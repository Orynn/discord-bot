from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

MAX_TEXT_LENGTH = 2500
_WIDTH = 920
_MIN_HEIGHT = 640
_MAX_HEIGHT = 2400
_MARGIN_X = 96
_MARGIN_TOP = 120
_MARGIN_BOTTOM = 140
_INK = (72, 42, 22)
_INK_SOFT = (98, 62, 34)
_BORDER = (92, 54, 28)
_SEAL = (138, 36, 32)
_SEAL_DARK = (92, 18, 16)
_PAPER = (224, 196, 150)

_FONT_REGULAR = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
    Path("/usr/share/fonts/truetype/freefont/FreeSerif.ttf"),
)
_FONT_BOLD = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"),
    Path("/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf"),
)


class ParchmentError(ValueError):
    pass


def parse_document_text(raw: str) -> tuple[str | None, str]:
    text = (raw or "").strip()
    if not text:
        raise ParchmentError("Texte manquant.")
    if len(text) > MAX_TEXT_LENGTH:
        raise ParchmentError(
            f"Texte trop long ({len(text)} caractères, maximum {MAX_TEXT_LENGTH})."
        )
    if " -- " in text:
        title, _, body = text.partition(" -- ")
        title, body = title.strip(), body.strip()
        if title and body:
            return title, body
    return None, text


def _load_font(
    candidates: tuple[Path, ...], size: int
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _wrap_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for word in paragraph.split():
            trial = word if not current else f"{current} {word}"
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
                continue
            if current:
                lines.append(current)
            if draw.textlength(word, font=font) <= max_width:
                current = word
                continue
            chunk = ""
            for char in word:
                tentative = f"{chunk}{char}"
                if chunk and draw.textlength(tentative, font=font) > max_width:
                    lines.append(chunk)
                    chunk = char
                else:
                    chunk = tentative
            current = chunk
        if current:
            lines.append(current)
    return lines or [""]


def _line_height(font: ImageFont.ImageFont) -> int:
    bbox = font.getbbox("Hg")
    return bbox[3] - bbox[1]


def _make_paper(width: int, height: int) -> Image.Image:
    paper = Image.new("RGB", (width, height), _PAPER)
    noise = Image.effect_noise((width, height), 28).convert("RGB")
    paper = Image.blend(paper, noise, 0.16)
    stain = Image.new("RGB", (width, height), (186, 142, 90))
    paper = Image.blend(paper, stain, 0.07)

    vignette = Image.new("L", (width, height), 0)
    vdraw = ImageDraw.Draw(vignette)
    vdraw.ellipse(
        (-int(width * 0.12), -int(height * 0.1), int(width * 1.12), int(height * 1.1)),
        fill=255,
    )
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=max(40, width // 16)))
    darkened = ImageEnhance.Brightness(paper).enhance(0.74)
    return Image.composite(paper, darkened, vignette)


def _draw_ornaments(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    inset = 36
    outer = [inset, inset, width - inset, height - inset]
    inner = [inset + 8, inset + 8, width - inset - 8, height - inset - 8]
    draw.rectangle(outer, outline=_BORDER, width=3)
    draw.rectangle(inner, outline=_BORDER, width=1)

    for x, y in (
        (inset + 18, inset + 18),
        (width - inset - 18, inset + 18),
        (inset + 18, height - inset - 18),
        (width - inset - 18, height - inset - 18),
    ):
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), outline=_BORDER, width=2)
        draw.line((x - 14, y, x + 14, y), fill=_BORDER, width=1)
        draw.line((x, y - 14, x, y + 14), fill=_BORDER, width=1)

    mid_y_top = inset + 28
    mid_y_bot = height - inset - 28
    draw.line(
        (inset + 48, mid_y_top, width - inset - 48, mid_y_top), fill=_BORDER, width=1
    )
    draw.line(
        (inset + 48, mid_y_bot, width - inset - 48, mid_y_bot), fill=_BORDER, width=1
    )


def _draw_seal(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    cx, cy = width // 2, height - 78
    draw.ellipse(
        (cx - 28, cy - 28, cx + 28, cy + 28), fill=_SEAL, outline=_SEAL_DARK, width=3
    )
    draw.ellipse((cx - 18, cy - 18, cx + 18, cy + 18), outline=(196, 150, 84), width=2)
    draw.polygon(
        [(cx, cy - 10), (cx + 8, cy + 8), (cx - 8, cy + 8)],
        outline=(196, 150, 84),
    )


def render_parchment(*, title: str | None, body: str) -> io.BytesIO:
    title_text = (title or "").strip()
    body_text = (body or "").strip()
    if not body_text and not title_text:
        raise ParchmentError("Texte manquant.")

    measure = ImageDraw.Draw(Image.new("RGB", (1, 1), _PAPER))
    max_width = _WIDTH - (2 * _MARGIN_X)

    font_size = 28
    title_font: ImageFont.ImageFont | None = None
    body_font: ImageFont.ImageFont | None = None
    title_lines: list[str] = []
    body_lines: list[str] = []
    line_h = 0
    title_h = 0
    needed = _MIN_HEIGHT

    while font_size >= 16:
        body_font = _load_font(_FONT_REGULAR, font_size)
        title_font = _load_font(_FONT_BOLD, font_size + 8)
        body_lines = (
            _wrap_lines(measure, body_text, body_font, max_width) if body_text else []
        )
        title_lines = (
            _wrap_lines(measure, title_text, title_font, max_width)
            if title_text
            else []
        )
        line_h = int(_line_height(body_font) * 1.45)
        title_h = int(_line_height(title_font) * 1.35) if title_lines else 0
        title_block = title_h * len(title_lines) + (28 if title_lines else 0)
        needed = (
            _MARGIN_TOP
            + title_block
            + line_h * max(len(body_lines), 1)
            + _MARGIN_BOTTOM
        )
        if needed <= _MAX_HEIGHT:
            break
        font_size -= 2

    assert body_font is not None and title_font is not None
    height = max(_MIN_HEIGHT, min(_MAX_HEIGHT, needed))
    image = _make_paper(_WIDTH, height)
    draw = ImageDraw.Draw(image)
    _draw_ornaments(draw, _WIDTH, height)

    y = _MARGIN_TOP
    for line in title_lines:
        draw.text((_WIDTH // 2, y), line, font=title_font, fill=_INK, anchor="ma")
        y += title_h
    if title_lines:
        y += 18
        draw.line(
            (_MARGIN_X + 40, y, _WIDTH - _MARGIN_X - 40, y), fill=_INK_SOFT, width=1
        )
        y += 22

    for line in body_lines:
        if line:
            draw.text((_MARGIN_X, y), line, font=body_font, fill=_INK)
        y += line_h
        if y > height - _MARGIN_BOTTOM:
            break

    _draw_seal(draw, _WIDTH, height)
    image = ImageChops.multiply(image, Image.new("RGB", image.size, (255, 248, 236)))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    buffer.name = "parchemin.png"
    return buffer
