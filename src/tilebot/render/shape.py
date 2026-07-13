"""Картинка обмеренной фигуры — «вот что я посчитал, проверь».

Числа в ответе ничего не доказывают: мастер мог перепутать порядок сторон, и бот
честно посчитает не ту фигуру. Схема это сразу показывает.
"""

import io

from PIL import Image, ImageDraw

from tilebot.core.geometry import AreaResult, Part, Point
from tilebot.render.scheme import BG, CUT_EDGE, MUTED, TEXT, TILE_EDGE, TILE_FILL, _font

MARGIN = 78
CANVAS = 900
SUBTRACT_FILL = (254, 226, 226)
SUBTRACT_EDGE = (220, 38, 38)


def _fit(points: list[Point], width: int, height: int) -> list[tuple[float, float]]:
    """Вписать фигуру в холст, сохранив пропорции. Y переворачиваем: на экране он вниз."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    span_x = max(max(xs) - min(xs), 1e-6)
    span_y = max(max(ys) - min(ys), 1e-6)
    scale = min((width - 2 * MARGIN) / span_x, (height - 2 * MARGIN) / span_y)

    # Центрируем то, что получилось.
    off_x = (width - span_x * scale) / 2
    off_y = (height - span_y * scale) / 2
    return [
        (off_x + (x - min(xs)) * scale, height - off_y - (y - min(ys)) * scale)
        for x, y in points
    ]


def render_shape(result: AreaResult, title: str = "Обмер") -> bytes | None:
    """Многоугольник с подписанными сторонами. None — если вершин нет."""
    if len(result.vertices) < 3:
        return None

    img = Image.new("RGB", (CANVAS, CANVAS), BG)
    d = ImageDraw.Draw(img)
    f_small = _font(16)
    f_mid = _font(18)
    f_title = _font(22)

    pts = _fit(result.vertices, CANVAS, CANVAS)
    d.polygon(pts, fill=TILE_FILL, outline=TILE_EDGE)
    d.line([*pts, pts[0]], fill=TEXT, width=3, joint="curve")

    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]

        # Длину берём из исходных метров, а не из пикселей.
        ax, ay = result.vertices[i]
        bx, by = result.vertices[(i + 1) % n]
        length = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5

        # Подпись отодвигаем наружу от центра фигуры, чтобы не легла на контур.
        cx = sum(p[0] for p in pts) / n
        cy = sum(p[1] for p in pts) / n
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        dx, dy = mx - cx, my - cy
        norm = max((dx**2 + dy**2) ** 0.5, 1e-6)
        lx, ly = mx + dx / norm * 26, my + dy / norm * 26

        d.text((lx, ly), f"{length:.2f}", fill=TEXT, font=f_mid, anchor="mm")
        d.ellipse([x1 - 4, y1 - 4, x1 + 4, y1 + 4], fill=TEXT)

    # Диагонали из первой вершины — по ним и собиралась фигура.
    for i in range(2, n - 1):
        d.line([pts[0], pts[i]], fill=CUT_EDGE, width=2)
        ax, ay = result.vertices[0]
        bx, by = result.vertices[i]
        length = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        mx = (pts[0][0] + pts[i][0]) / 2
        my = (pts[0][1] + pts[i][1]) / 2
        d.text((mx, my - 12), f"{length:.2f}", fill=CUT_EDGE, font=f_small, anchor="mm")

    d.text((MARGIN // 2, 26), title, fill=TEXT, font=f_title, anchor="lm")
    d.text(
        (MARGIN // 2, 52),
        f"{result.area_m2:.2f} м² · {result.method}",
        fill=MUTED,
        font=f_small,
        anchor="lm",
    )
    if n > 3:
        d.text(
            (CANVAS - MARGIN // 2, CANVAS - 20),
            "оранжевым — диагонали",
            fill=MUTED,
            font=f_small,
            anchor="rm",
        )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_parts(parts: list[Part], result: AreaResult, title: str = "Обмер") -> bytes:
    """Составная комната: участки и вычеты отдельными блоками.

    Где куски стоят друг относительно друга, мастер не сообщал — поэтому рисуем их
    в ряд и честно подписываем, что схема условная. Площадь от этого не зависит.
    """
    gap = 24
    top_pad = 104  # заголовок плюс строка «+12.00 м²» над самым высоким блоком
    bottom_pad = 64  # имя участка и его размеры

    scale = (CANVAS - 2 * MARGIN - gap * max(len(parts) - 1, 0)) / max(
        sum(p.width_m for p in parts), 1e-6
    )
    tallest = max(p.length_m for p in parts)
    scale = min(scale, (CANVAS - top_pad - bottom_pad) / tallest)
    height = int(tallest * scale)

    img = Image.new("RGB", (CANVAS, height + top_pad + bottom_pad), BG)
    d = ImageDraw.Draw(img)
    f_small = _font(15)
    f_mid = _font(17)
    f_title = _font(22)

    x = MARGIN
    base = img.height - bottom_pad  # снизу оставляем место под имя и размеры
    for part in parts:
        w = part.width_m * scale
        h = part.length_m * scale
        box = [x, base - h, x + w, base]
        d.rectangle(
            box,
            fill=SUBTRACT_FILL if part.subtract else TILE_FILL,
            outline=SUBTRACT_EDGE if part.subtract else TEXT,
            width=3,
        )
        # Подписи ставим снаружи: узкий блок (вычет-короб) их внутри не вмещает.
        label = f"{'−' if part.subtract else '+'}{abs(part.area_m2):.2f} м²"
        d.text(
            (x + w / 2, base - h - 16),
            label,
            fill=SUBTRACT_EDGE if part.subtract else TEXT,
            font=f_mid,
            anchor="mm",
        )
        d.text((x + w / 2, base + 18), part.name, fill=TEXT, font=f_small, anchor="mm")
        d.text(
            (x + w / 2, base + 38),
            f"{part.width_m:g} × {part.length_m:g} м",
            fill=MUTED,
            font=f_small,
            anchor="mm",
        )
        x += w + gap

    d.text((MARGIN // 2, 26), title, fill=TEXT, font=f_title, anchor="lm")
    d.text(
        (MARGIN // 2, 52),
        f"{result.area_m2:.2f} м² · участки показаны отдельно, не по месту",
        fill=MUTED,
        font=f_small,
        anchor="lm",
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
