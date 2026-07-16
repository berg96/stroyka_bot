"""Раскладки под 45°: диагональ и ёлочка.

Прямая укладка ложится на сетку из прямоугольников, и её легко посчитать по осям.
Диагональ и ёлочка — нет: сетка повёрнута, и у стены плитки режутся треугольниками
по всему периметру. Поэтому здесь плитка перестаёт быть парой (ширина, высота) и
становится многоугольником, который обрезается по стене.

Раньше обе раскладки считались как прямая (плюс запас на бой), то есть бот показывал
мастеру подрезку, которой не будет, и советовал «раскладка ровная» там, где режется
весь периметр.
"""

import math
from dataclasses import dataclass

Point = tuple[float, float]

# Допуск на арифметику с плавающей точкой: миллиметровые доли нас не интересуют,
# а вот «плитка вылезла на 1e-9» — ложная подрезка.
EPS = 1e-6


@dataclass(frozen=True)
class Piece:
    """Кусок плитки, который реально ляжет на стену."""

    polygon: tuple[Point, ...]
    area_mm2: float
    is_cut: bool

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.polygon]
        ys = [p[1] for p in self.polygon]
        return min(xs), min(ys), max(xs), max(ys)


def polygon_area(points: tuple[Point, ...]) -> float:
    """Площадь многоугольника по вершинам."""
    n = len(points)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def clip_to_rect(polygon: tuple[Point, ...], width: float, height: float) -> tuple[Point, ...]:
    """Обрезать многоугольник прямоугольником стены (Сазерленд — Ходжман).

    Плитка у края стены превращается в треугольник или трапецию — именно это мастер
    и режет плиткорезом.
    """
    edges = (
        (lambda p: p[0] >= -EPS, 0, 0.0),  # левый край
        (lambda p: p[0] <= width + EPS, 0, width),  # правый
        (lambda p: p[1] >= -EPS, 1, 0.0),  # низ
        (lambda p: p[1] <= height + EPS, 1, height),  # верх
    )

    current = list(polygon)
    for inside, axis, bound in edges:
        if not current:
            return ()
        out: list[Point] = []
        for i, cur in enumerate(current):
            prev = current[i - 1]
            cur_in, prev_in = inside(cur), inside(prev)
            if cur_in != prev_in:
                out.append(_cross(prev, cur, axis, bound))
            if cur_in:
                out.append(cur)
        current = out

    return tuple(current)


def _cross(a: Point, b: Point, axis: int, bound: float) -> Point:
    """Точка, где отрезок a→b пересекает границу стены."""
    delta = b[axis] - a[axis]
    if abs(delta) < EPS:
        return b
    t = (bound - a[axis]) / delta
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _rotate(point: Point, angle: float, around: Point) -> Point:
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    dx, dy = point[0] - around[0], point[1] - around[1]
    return (around[0] + dx * cos_a - dy * sin_a, around[1] + dx * sin_a + dy * cos_a)


def _rect(x: float, y: float, w: float, h: float) -> tuple[Point, ...]:
    return ((x, y), (x + w, y), (x + w, y + h), (x, y + h))


def diagonal_tiles(
    tile_w: float, tile_h: float, joint: float, reach: float
) -> list[tuple[Point, ...]]:
    """Плитки диагональной раскладки — обычная сетка, повёрнутая на 45°."""
    step_x, step_y = tile_w + joint, tile_h + joint
    cols = int(reach / step_x) + 2
    rows = int(reach / step_y) + 2

    return [
        _rect(i * step_x, j * step_y, tile_w, tile_h)
        for i in range(-cols, cols + 1)
        for j in range(-rows, rows + 1)
    ]


def herringbone_tiles(
    tile_w: float, tile_h: float, joint: float, reach: float
) -> list[tuple[Point, ...]]:
    """Плитки ёлочки: пары «лежит + стоит», торец одной в бок другой.

    Пара — горизонтальная плитка в начале координат и вертикальная сразу за ней.
    Такие пары замощают плоскость решёткой с векторами (-W, W) и (L, L): её
    определитель равен 2·L·W, то есть ровно площади пары — без дыр и нахлёстов.
    """
    long_side, short_side = max(tile_w, tile_h), min(tile_w, tile_h)
    lj, wj = long_side + joint, short_side + joint

    v1 = (-wj, wj)
    v2 = (lj, lj)
    steps = int(reach / min(wj, lj)) + 2

    tiles: list[tuple[Point, ...]] = []
    for a in range(-steps, steps + 1):
        for b in range(-steps, steps + 1):
            ox = a * v1[0] + b * v2[0]
            oy = a * v1[1] + b * v2[1]
            tiles.append(_rect(ox, oy, long_side, short_side))  # лежит
            tiles.append(_rect(ox + lj, oy, short_side, long_side))  # стоит
    return tiles


def angled_pieces(
    surface_w: float,
    surface_h: float,
    tile_w: float,
    tile_h: float,
    joint: float,
    *,
    herringbone: bool = False,
    angle_deg: float = 45.0,
) -> list[Piece]:
    """Разложить стену раскладкой под углом и обрезать всё лишнее по её краям."""
    if surface_w <= 0 or surface_h <= 0 or tile_w <= 0 or tile_h <= 0:
        return []

    # Сетку строим с запасом: после поворота углы стены уезжают, и её надо накрыть
    # целиком — иначе по краям появятся дыры.
    reach = math.hypot(surface_w, surface_h) + max(tile_w, tile_h) * 2
    raw = (
        herringbone_tiles(tile_w, tile_h, joint, reach)
        if herringbone
        else diagonal_tiles(tile_w, tile_h, joint, reach)
    )

    angle = math.radians(angle_deg)
    centre = (surface_w / 2, surface_h / 2)
    full_area = tile_w * tile_h

    pieces: list[Piece] = []
    for tile in raw:
        turned = tuple(_rotate(p, angle, centre) for p in tile)
        clipped = clip_to_rect(turned, surface_w, surface_h)
        area = polygon_area(clipped)
        if area <= EPS:
            continue  # плитка целиком за стеной
        pieces.append(
            Piece(polygon=clipped, area_mm2=area, is_cut=area < full_area - 1.0)
        )

    return pieces
