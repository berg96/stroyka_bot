"""Схема раскладки картинкой.

Мастеру нужно увидеть стену: где целые плитки, где подрезка и какой она ширины.
Рисуем в чистом виде — плитки, размеры по краям, подрезка выделена.

Если мастер прислал фото своей плитки, схема перестаёт быть чертежом «в серых
квадратиках»: плитка рисуется настоящая, а швы — того цвета затирки, который он
собирается купить. Это уже не «сколько штук», а «как будет выглядеть» — то, что
заказчику показывают до начала работ.
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

# Шов 1,4 мм на схеме — меньше пикселя, и цвет затирки не разглядеть. На стене он
# виден, потому что стена не 20 см шириной. Поэтому шов рисуем не тоньше этого:
# плитка теряет пару пикселей из трёхсот, зато мастер видит, что покупает.
MIN_JOINT_PX = 3.0

# Затирка. Мастер выбирает не hex, а мешок в магазине — поэтому ходовые цвета.
GROUT_COLORS: dict[str, tuple[str, tuple[int, int, int]]] = {
    "white": ("Белая", (242, 242, 240)),
    "grey": ("Серая", (156, 160, 162)),
    "beige": ("Бежевая", (214, 199, 174)),
    "graphite": ("Графит", (86, 90, 94)),
    "black": ("Чёрная", (38, 40, 42)),
}
DEFAULT_GROUT = "grey"


def grout_rgb(name: str | None) -> tuple[int, int, int]:
    return GROUT_COLORS.get(name or DEFAULT_GROUT, GROUT_COLORS[DEFAULT_GROUT])[1]


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


def _texture(photo: Image.Image, tile_w_px: int, tile_h_px: int) -> Image.Image:
    """Фото плитки под размер плитки на схеме.

    Мастер снимает плитку как придётся — лёжа или стоя. Если кадр развёрнут не так,
    как плитка лежит на стене, поворачиваем, иначе рисунок растянет поперёк.
    """
    if (photo.width > photo.height) != (tile_w_px > tile_h_px):
        photo = photo.rotate(90, expand=True)
    return photo.resize((max(1, tile_w_px), max(1, tile_h_px)), Image.LANCZOS)


def render_layout(
    layout: Layout,
    title: str | None = None,
    *,
    tile_photo: Image.Image | None = None,
    grout: str | None = None,
) -> bytes:
    """Отрисовать раскладку в PNG.

    tile_photo — фото настоящей плитки; grout — ключ цвета затирки из GROUT_COLORS.
    """
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

    # Стена целиком — цветом затирки: между плитками остаётся шов, и он же виден
    # по краям подрезки. Без фото это просто фон и рисовать его незачем.
    if tile_photo is not None or grout:
        d.rectangle([px(0), py(sh), px(sw), py(0)], fill=grout_rgb(grout))

    # Насколько ужать плитку, чтобы шов стало видно.
    gap = max(0.0, MIN_JOINT_PX - tile.joint_mm * scale) / 2 if (tile_photo or grout) else 0.0

    texture = None
    if tile_photo is not None:
        texture = _texture(
            tile_photo, round(tile.width_mm * scale), round(tile.height_mm * scale)
        )

    # Рисуем ровно те плитки, которые посчитало ядро — включая пропуски под проёмами.
    for cell in layout.cells:
        if cell.polygon:
            # Плитка под 45°: рисуем её настоящую форму — у стены это треугольники
            # и трапеции. Текстуру сюда не натянуть, поэтому берём цвет.
            points = [(px(x), py(y)) for x, y in cell.polygon]
            d.polygon(
                points,
                fill=CUT_FILL if cell.is_cut else TILE_FILL,
                outline=CUT_EDGE if cell.is_cut else TILE_EDGE,
            )
            continue

        box = [
            px(cell.x) + gap,
            py(cell.y + cell.h) + gap,
            px(cell.x + cell.w) - gap,
            py(cell.y) - gap,
        ]

        if texture is not None:
            # Подрезанная плитка — это кусок целой: обрезаем текстуру, а не жмём её.
            w_px = max(1, round(box[2] - box[0]))
            h_px = max(1, round(box[3] - box[1]))
            patch = texture.crop((0, 0, min(w_px, texture.width), min(h_px, texture.height)))
            if patch.size != (w_px, h_px):
                patch = patch.resize((w_px, h_px), Image.LANCZOS)
            img.paste(patch, (round(box[0]), round(box[1])))
            # Подрезку всё равно надо видеть, но тонко: тут смотрят на плитку, а не
            # на чертёж — жирная рамка забивает вид.
            if cell.is_cut:
                d.rectangle(box, outline=CUT_EDGE, width=1)
            continue

        d.rectangle(
            box,
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
    if grout:
        sub += f" · затирка {GROUT_COLORS[grout][0].lower()}"
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

    _legend(d, ch, f_small, has_cuts=any(c.is_cut for c in layout.cells), photo=tile_photo)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _legend(
    d: ImageDraw.ImageDraw,
    canvas_h: int,
    font: ImageFont.FreeTypeFont,
    *,
    has_cuts: bool,
    photo: Image.Image | None,
) -> None:
    """Что тут какого цвета. Без этого мастер гадает, почему часть плиток оранжевая."""
    x, y = MARGIN, canvas_h - 24
    box = 13

    def swatch(fill, edge, text: str) -> None:
        nonlocal x
        d.rectangle([x, y - box // 2, x + box, y + box // 2], fill=fill, outline=edge, width=1)
        x += box + 6
        d.text((x, y), text, fill=MUTED, font=font, anchor="lm")
        x += int(d.textlength(text, font=font)) + 18

    if photo is None:
        swatch(TILE_FILL, TILE_EDGE, "целая плитка")
    if has_cuts:
        swatch(CUT_FILL if photo is None else None, CUT_EDGE, "резать")
        d.text((x, y), "оранжевым — ширина подрезки, мм", fill=MUTED, font=font, anchor="lm")
