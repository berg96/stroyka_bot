"""Раскладка плитки по поверхности: сетка, подрезка, советы мастеру.

Главное, чего нет в онлайн-калькуляторах «площадь ÷ площадь плитки»: где именно
встанет подрезка и не получится ли по краю тонкая полоска, которую плиточник
считает браком работы.
"""

import math
from dataclasses import dataclass

from tilebot.core.models import LayoutPattern, StartFrom, Surface, Tile

# Подрезка уже этой доли плитки выглядит плохо и крошится при резке — классическое
# правило мастеров «не меньше трети/половины плитки».
MIN_CUT_RATIO = 1 / 3
# Абсолютный минимум: полоска тоньше — почти гарантированно лопнет.
MIN_CUT_MM = 30.0


@dataclass(frozen=True)
class Axis:
    """Раскладка вдоль одной оси поверхности."""

    full: int  # целых плиток в ряду
    cut_start_mm: float  # ширина подрезки в начале (0 — подрезки нет)
    cut_end_mm: float  # ширина подрезки в конце
    total: int  # всего позиций в ряду, включая подрезанные

    @property
    def cuts(self) -> list[float]:
        return [c for c in (self.cut_start_mm, self.cut_end_mm) if c > 0]

    @property
    def min_cut_mm(self) -> float:
        """Самая узкая подрезка на оси. inf — подрезки нет вообще."""
        return min(self.cuts) if self.cuts else math.inf


@dataclass(frozen=True)
class Cell:
    """Одна плитка на поверхности. Координаты в мм от левого нижнего угла."""

    x: float
    y: float
    w: float
    h: float
    is_cut: bool


@dataclass(frozen=True)
class Layout:
    """Готовая раскладка поверхности."""

    surface: Surface
    tile: Tile
    pattern: LayoutPattern
    start_from: StartFrom
    x: Axis  # по горизонтали
    y: Axis  # по вертикали
    cells: list[Cell]  # плитки, которые реально лягут (без тех, что в проёмах)
    advice: list[str]

    @property
    def tiles_grid(self) -> int:
        """Штук плитки на поверхность: целые и подрезанные, каждая — из своей плитки."""
        return len(self.cells)

    @property
    def cuts_count(self) -> int:
        return sum(1 for c in self.cells if c.is_cut)

    @property
    def rows(self) -> int:
        return self.y.total

    @property
    def cols(self) -> int:
        return self.x.total


def _axis(length_mm: float, step_mm: float, tile_mm: float, start: StartFrom) -> Axis:
    """Разложить ось: сколько целых плиток и какая подрезка по краям.

    Раскладка от края: первая плитка целая, весь остаток уходит в подрезку с
    противоположной стороны. От центра: остаток делится пополам на два края —
    так делают, когда крайняя плитка иначе получается тонкой.
    """
    if length_mm <= 0 or tile_mm <= 0:
        return Axis(full=0, cut_start_mm=0.0, cut_end_mm=0.0, total=0)

    # Целых плиток влезает n, если n плиток и (n-1) швов не длиннее поверхности.
    # Крайнему шву у стены места не нужно, поэтому считаем по шагу сетки с
    # поправкой на один недостающий шов.
    joint_mm = step_mm - tile_mm
    full = int(math.floor((length_mm + joint_mm) / step_mm + 1e-9))
    remainder = length_mm - (full * step_mm - joint_mm)
    if remainder < 1e-6:
        remainder = 0.0

    if remainder == 0.0:
        return Axis(full=full, cut_start_mm=0.0, cut_end_mm=0.0, total=full)

    # Остаток — это место под подрезку минус шов, который её отделяет.
    cut = max(0.0, remainder - joint_mm)

    if start is StartFrom.CENTER:
        # Убираем одну целую плитку и раскидываем освободившееся на две стороны,
        # чтобы подрезка была симметричной. При крошечном остатке (cut почти 0)
        # это как раз спасает от волосяной полоски по краю.
        if full >= 1 and cut < tile_mm:
            side = (cut + tile_mm - joint_mm) / 2
            # На каждый край добавился ещё один шов — он съедает по половине.
            return Axis(full=full - 1, cut_start_mm=side, cut_end_mm=side, total=full + 1)
        half = cut / 2
        return Axis(full=full - 1, cut_start_mm=half, cut_end_mm=half, total=full + 1)

    return Axis(full=full, cut_start_mm=0.0, cut_end_mm=cut, total=full + 1)


def _spans(axis: Axis, tile_mm: float, joint_mm: float) -> list[tuple[float, float, bool]]:
    """Ось → список (начало, длина, подрезка?) в мм."""
    out: list[tuple[float, float, bool]] = []
    pos = 0.0
    if axis.cut_start_mm > 0:
        out.append((pos, axis.cut_start_mm, True))
        pos += axis.cut_start_mm + joint_mm
    for _ in range(axis.full):
        out.append((pos, tile_mm, False))
        pos += tile_mm + joint_mm
    if axis.cut_end_mm > 0:
        out.append((pos, axis.cut_end_mm, True))
    return out


def _covered_by_opening(cell: Cell, surface: Surface) -> bool:
    """Плитка целиком внутри проёма — её просто не кладут.

    Проём без координат (мастер не сказал где дверь) в расчёте сетки не участвует:
    его площадь уже вычтена из нетто, а гадать, какие плитки убрать, мы не станем.
    """
    for op in surface.openings:
        if op.x_mm is None or op.y_mm is None:
            continue
        inside_x = cell.x >= op.x_mm - 1e-6 and cell.x + cell.w <= op.x_mm + op.width_mm + 1e-6
        inside_y = cell.y >= op.y_mm - 1e-6 and cell.y + cell.h <= op.y_mm + op.height_mm + 1e-6
        if inside_x and inside_y:
            return True
    return False


def _clipped_by_opening(cell: Cell, surface: Surface) -> bool:
    """Плитка задевает край проёма — её придётся резать по косяку."""
    for op in surface.openings:
        if op.x_mm is None or op.y_mm is None:
            continue
        overlaps_x = cell.x < op.x_mm + op.width_mm - 1e-6 and cell.x + cell.w > op.x_mm + 1e-6
        overlaps_y = cell.y < op.y_mm + op.height_mm - 1e-6 and cell.y + cell.h > op.y_mm + 1e-6
        if overlaps_x and overlaps_y:
            return True
    return False


def build_cells(
    surface: Surface, tile: Tile, x: Axis, y: Axis, pattern: LayoutPattern
) -> list[Cell]:
    """Разложить сетку в конкретные плитки — на этом строятся и счёт, и схема."""
    cols = _spans(x, tile.width_mm, tile.joint_mm)
    rows = _spans(y, tile.height_mm, tile.joint_mm)
    sw = surface.width_mm

    cells: list[Cell] = []
    for r, (cy, ch, cut_y) in enumerate(rows):
        # Вразбежку каждый второй ряд сдвинут на полплитки; слева появляется
        # обрезок, справа плитка уходит за стену и тоже режется.
        staggered = pattern is LayoutPattern.BRICK and r % 2 == 1
        shift = (tile.width_mm + tile.joint_mm) / 2 if staggered else 0.0

        row_cells: list[Cell] = []
        if shift > 0:
            row_cells.append(
                Cell(x=0.0, y=cy, w=max(0.0, shift - tile.joint_mm), h=ch, is_cut=True)
            )

        for cx, cw, cut_x in cols:
            gx = cx + shift
            if gx >= sw - 1e-6:
                continue  # ряд кончился, плитке места нет
            gw = cw
            cut = cut_x or cut_y
            if gx + gw > sw:  # вылезла за стену — режем по краю
                gw = sw - gx
                cut = True
            if gw <= 1e-6:
                continue
            row_cells.append(Cell(x=gx, y=cy, w=gw, h=ch, is_cut=cut))

        for cell in row_cells:
            if _covered_by_opening(cell, surface):
                continue  # плитка целиком в проёме — не кладём
            if not cell.is_cut and _clipped_by_opening(cell, surface):
                # Задело косяк двери — плитку придётся подрезать.
                cell = Cell(x=cell.x, y=cell.y, w=cell.w, h=cell.h, is_cut=True)
            cells.append(cell)

    return cells


def _advice(x: Axis, y: Axis, tile: Tile, surface: Surface, start: StartFrom) -> list[str]:
    """Подсказки уровня «что бы сказал опытный плиточник, посмотрев на схему»."""
    out: list[str] = []

    thin_x = x.min_cut_mm < max(MIN_CUT_MM, tile.width_mm * MIN_CUT_RATIO)
    if thin_x and start is StartFrom.EDGE:
        out.append(
            f"По горизонтали крайняя подрезка {x.min_cut_mm:.0f} мм — тонкая полоска. "
            f"Начни от центра: подрезка разойдётся на два края примерно по "
            f"{(x.min_cut_mm + tile.width_mm) / 2:.0f} мм."
        )
    elif thin_x:
        out.append(
            f"Даже от центра крайняя подрезка {x.min_cut_mm:.0f} мм. "
            "Подумай про другой размер плитки или шов пошире."
        )

    thin_y = y.min_cut_mm < max(MIN_CUT_MM, tile.height_mm * MIN_CUT_RATIO)
    if thin_y:
        where = "у пола" if surface.kind.value == "wall" else "у стены"
        out.append(
            f"По вертикали подрезка {y.min_cut_mm:.0f} мм — тонкий ряд {where}. "
            "Обычно его прячут вниз/под плинтус, целую плитку ставят на видное место."
        )

    if y.cut_start_mm == 0 and y.cut_end_mm > 0 and surface.kind.value == "wall":
        out.append(
            "Верхний ряд получается резаным. Если потолок неровный или сверху "
            "натяжной — это нормально, режь верх; если укладка до потолка — "
            "начинай сверху целой плиткой."
        )

    if not out:
        out.append("Раскладка ровная: тонких полосок по краям нет.")
    return out


def build_layout(
    surface: Surface,
    tile: Tile,
    pattern: LayoutPattern = LayoutPattern.STRAIGHT,
    start_from: StartFrom = StartFrom.EDGE,
) -> Layout:
    """Посчитать раскладку плитки на поверхности."""
    x = _axis(surface.width_mm, tile.step_x_mm, tile.width_mm, start_from)
    # По вертикали всегда стартуем от низа целой плиткой: подрезку прячут внизу.
    y = _axis(surface.height_mm, tile.step_y_mm, tile.height_mm, StartFrom.EDGE)

    return Layout(
        surface=surface,
        tile=tile,
        pattern=pattern,
        start_from=start_from,
        x=x,
        y=y,
        cells=build_cells(surface, tile, x, y, pattern),
        advice=_advice(x, y, tile, surface, start_from),
    )


def best_orientation(
    surface: Surface,
    tile: Tile,
    pattern: LayoutPattern = LayoutPattern.STRAIGHT,
    start_from: StartFrom = StartFrom.EDGE,
) -> tuple[Layout, Layout]:
    """Разложить плитку в обеих ориентациях и вернуть (лучшую, альтернативную).

    Лучшая — та, где самая узкая подрезка шире: меньше риска расколоть полоску и
    аккуратнее выглядит угол.
    """
    normal = build_layout(surface, tile, pattern, start_from)
    turned = build_layout(surface, tile.rotated(), pattern, start_from)

    def score(lay: Layout) -> tuple[float, float]:
        worst_cut = min(lay.x.min_cut_mm, lay.y.min_cut_mm)
        # При равной подрезке предпочитаем меньше плиток — меньше швов и работы.
        return (worst_cut, -lay.tiles_grid)

    return (normal, turned) if score(normal) >= score(turned) else (turned, normal)


def common_orientation(
    surfaces: list[Surface],
    tile: Tile,
    pattern: LayoutPattern = LayoutPattern.STRAIGHT,
    start_from: StartFrom = StartFrom.EDGE,
) -> Tile:
    """Одна ориентация плитки на все поверхности сразу.

    Стены одной комнаты кладут одинаково: плитка, повёрнутая на второй стене
    иначе, чем на первой, — это брак работы, даже если подрезка там вышла удачнее.
    Поэтому ориентацию выбираем по комнате целиком, а не по каждой стене.
    """
    if not surfaces:
        return tile

    def score(candidate: Tile) -> tuple[float, float]:
        layouts = [build_layout(s, candidate, pattern, start_from) for s in surfaces]
        worst_cut = min(min(lay.x.min_cut_mm, lay.y.min_cut_mm) for lay in layouts)
        return (worst_cut, -sum(lay.tiles_grid for lay in layouts))

    turned = tile.rotated()
    return tile if score(tile) >= score(turned) else turned
