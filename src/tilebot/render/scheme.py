"""Схема раскладки картинкой.

Мастеру нужно увидеть стену: где целые плитки, где подрезка и какой она ширины.
Рисуем в чистом виде — плитки, размеры по краям, подрезка выделена.
"""

import io

from PIL import Image, ImageDraw, ImageFont

from tilebot.core.layout import Layout
from tilebot.core.models import StartFrom
from tilebot.core.units import fmt_mm

# Палитра: спокойный чертёж, подрезка — тёплым акцентом.
BG = (250, 250, 249)
TILE_FILL = (226, 232, 240)
TILE_EDGE = (148, 163, 184)
CUT_FILL = (254, 215, 170)
CUT_EDGE = (234, 138, 47)
OPENING_FILL = (203, 213, 225)
OPENING_EDGE = (100, 116, 139)
TEXT = (30, 41, 59)
MUTED = (100, 116, 139)

MARGIN = 70
MAX_CANVAS = 1400
MIN_CANVAS = 520


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def render_layout(layout: Layout, title: str | None = None) -> bytes:
    """Отрисовать раскладку в PNG."""
    surface = layout.surface
    tile = layout.tile
    sw, sh = surface.width_mm, surface.height_mm

    # Масштаб под холст: длинная сторона стены → MAX_CANVAS минус поля.
    scale = min(
        (MAX_CANVAS - 2 * MARGIN) / max(sw, 1),
        (MAX_CANVAS - 2 * MARGIN) / max(sh, 1),
    )
    cw = max(MIN_CANVAS, int(sw * scale) + 2 * MARGIN)
    ch = max(MIN_CANVAS, int(sh * scale) + 2 * MARGIN + 40)

    img = Image.new("RGB", (cw, ch), BG)
    d = ImageDraw.Draw(img)
    f_small = _font(15)
    f_mid = _font(17)
    f_title = _font(20)

    ox = MARGIN
    oy = ch - MARGIN  # низ стены: рисуем снизу вверх, как кладут плитку

    def px(x_mm: float) -> float:
        return ox + x_mm * scale

    def py(y_mm: float) -> float:
        return oy - y_mm * scale

    # Рисуем ровно те плитки, которые посчитало ядро — включая пропуски под проёмами.
    for cell in layout.cells:
        d.rectangle(
            [px(cell.x), py(cell.y + cell.h), px(cell.x + cell.w), py(cell.y)],
            fill=CUT_FILL if cell.is_cut else TILE_FILL,
            outline=CUT_EDGE if cell.is_cut else TILE_EDGE,
            width=2,
        )

    for op in surface.openings:
        if op.x_mm is None or op.y_mm is None:
            continue
        d.rectangle(
            [px(op.x_mm), py(op.y_mm + op.height_mm), px(op.x_mm + op.width_mm), py(op.y_mm)],
            fill=OPENING_FILL,
            outline=OPENING_EDGE,
            width=3,
        )
        d.text(
            (px(op.x_mm + op.width_mm / 2), py(op.y_mm + op.height_mm / 2)),
            op.name,
            fill=TEXT,
            font=f_small,
            anchor="mm",
        )

    # Контур стены поверх плиток.
    d.rectangle([px(0), py(sh), px(sw), py(0)], outline=TEXT, width=3)

    # Размеры: ширина снизу, высота слева.
    d.text((px(sw / 2), oy + 26), f"{sw / 1000:.2f} м", fill=TEXT, font=f_mid, anchor="mm")
    d.text(
        (ox - 34, py(sh / 2)),
        f"{sh / 1000:.2f} м",
        fill=TEXT,
        font=f_mid,
        anchor="mm",
    )

    head = title or surface.name
    d.text((MARGIN, 22), head, fill=TEXT, font=f_title, anchor="lm")
    sub = (
        f"плитка {tile.width_mm:.0f}×{tile.height_mm:.0f} мм · шов {fmt_mm(tile.joint_mm)} мм · "
        f"{layout.tiles_grid} шт, из них резаных {layout.cuts_count}"
    )
    d.text((MARGIN, 46), sub, fill=MUTED, font=f_small, anchor="lm")

    # Подписи ширины подрезки — то, ради чего схема и рисуется.
    if layout.x.cut_start_mm > 0:
        d.text(
            (px(layout.x.cut_start_mm / 2), py(sh) - 14),
            f"{layout.x.cut_start_mm:.0f}",
            fill=CUT_EDGE,
            font=f_small,
            anchor="mm",
        )
    if layout.x.cut_end_mm > 0:
        d.text(
            (px(sw - layout.x.cut_end_mm / 2), py(sh) - 14),
            f"{layout.x.cut_end_mm:.0f}",
            fill=CUT_EDGE,
            font=f_small,
            anchor="mm",
        )
    if layout.y.cut_end_mm > 0:
        d.text(
            (px(sw) + 22, py(sh - layout.y.cut_end_mm / 2)),
            f"{layout.y.cut_end_mm:.0f}",
            fill=CUT_EDGE,
            font=f_small,
            anchor="mm",
        )

    start_label = "от центра" if layout.start_from is StartFrom.CENTER else "от угла"
    d.text(
        (cw - MARGIN, ch - 18),
        f"раскладка {start_label}",
        fill=MUTED,
        font=f_small,
        anchor="rm",
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
