"""Раскладка плитки по поверхности: сетка, подрезка, советы мастеру.

Главное, чего нет в онлайн-калькуляторах «площадь ÷ площадь плитки»: где именно
встанет подрезка и не получится ли по краю тонкая полоска, которую плиточник
считает браком работы.
"""

import math
from dataclasses import dataclass

from tilebot.core.angled import Point, angled_pieces
from tilebot.core.models import DEFAULT_OFFSET, LayoutPattern, StartFrom, Surface, Tile

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
    """Одна плитка на поверхности. Координаты в мм от левого нижнего угла.

    polygon непустой — плитка лежит под углом (диагональ, ёлочка) и прямоугольником
    уже не описывается; x/y/w/h тогда её габаритная рамка.

    counts_as_tile=False — это второй кусок плитки, разрезанной на углу: сама плитка
    уже посчитана на соседней стене (эконом-раскладка по периметру). Класть его надо,
    а покупать второй раз — нет.
    """

    x: float
    y: float
    w: float
    h: float
    is_cut: bool
    polygon: tuple[Point, ...] = ()
    counts_as_tile: bool = True


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
        """Штук плитки на поверхность: целые и подрезанные, каждая — из своей плитки.

        Куски, приехавшие из-за угла (эконом-раскладка), не в счёт — их плитка уже
        куплена на соседней стене, иначе закупка удвоит каждый угол.
        """
        return sum(1 for c in self.cells if c.counts_as_tile)

    @property
    def cuts_count(self) -> int:
        """Сколько плиток придётся резать — за это в смете отдельная строка.

        Считаем плитки, а не куски: угловая плитка режется ОДИН раз и даёт два
        куска на две стены. Кусок из-за угла (counts_as_tile=False) — вторая
        половина уже посчитанного реза, не новый рез.
        """
        return sum(1 for c in self.cells if c.is_cut and c.counts_as_tile)

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

    if start is StartFrom.CENTER and full >= 1:
        # Убираем одну целую плитку и раскидываем освободившееся на две стороны,
        # чтобы подрезка была симметричной. При крошечном остатке (cut почти 0)
        # это как раз спасает от волосяной полоски по краю.
        #
        # Ряд из (full-1) целых, двух обрезков и full швов обязан лечь ровно в стену:
        #   (full-1)·tile + 2·side + full·joint = length
        # откуда side = (tile + cut)/2. Лишний вычет шва здесь оставлял стену
        # непокрытой на joint — и края разъезжались на пару миллиметров.
        side = (cut + tile_mm) / 2
        return Axis(full=full - 1, cut_start_mm=side, cut_end_mm=side, total=full + 1)

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


def _staggered_spans(
    surface_w: float, tile_mm: float, joint_mm: float, shift: float, base_x: float
) -> list[tuple[float, float, bool]]:
    """Смещённый ряд кирпичной кладки: сетка соседнего ряда, сдвинутая на shift.

    Считать смещение от края стены нельзя: если базовый ряд сам начинается с
    подрезки (раскладка от центра), то ряды разъезжаются не на полплитки, а на
    сколько получится — у стены 2 м это давало 97 мм вместо 301. Разбежка — это
    сдвиг ОТНОСИТЕЛЬНО соседнего ряда, поэтому пляшем от его целых плиток.
    """
    step = tile_mm + joint_mm

    # Отходим назад от первой целой плитки соседнего ряда, пока не накроем левый край.
    pos = base_x + shift
    while pos > -tile_mm:
        pos -= step
    pos += step

    out: list[tuple[float, float, bool]] = []
    while pos < surface_w - 1e-6:
        left = max(0.0, pos)
        right = min(surface_w, pos + tile_mm)
        width = right - left
        if width > 1e-6:
            out.append((left, width, width < tile_mm - 1e-6))
        pos += step
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


def apply_openings(cells: list[Cell], surface: Surface) -> list[Cell]:
    """Убрать плитки, попавшие в проём, и пометить резаными те, что задели косяк."""
    out: list[Cell] = []
    for cell in cells:
        if _covered_by_opening(cell, surface):
            continue  # плитка целиком в проёме — не кладём
        if not cell.is_cut and _clipped_by_opening(cell, surface):
            cell = Cell(
                x=cell.x,
                y=cell.y,
                w=cell.w,
                h=cell.h,
                is_cut=True,
                polygon=cell.polygon,
                counts_as_tile=cell.counts_as_tile,
            )
        out.append(cell)
    return out


def build_cells(
    surface: Surface,
    tile: Tile,
    x: Axis,
    y: Axis,
    pattern: LayoutPattern,
    offset_ratio: float = DEFAULT_OFFSET,
) -> list[Cell]:
    """Разложить сетку в конкретные плитки — на этом строятся и счёт, и схема."""
    cols = _spans(x, tile.width_mm, tile.joint_mm)
    rows = _spans(y, tile.height_mm, tile.joint_mm)
    sw = surface.width_mm

    cells: list[Cell] = []
    for r, (cy, ch, cut_y) in enumerate(rows):
        # Вразбежку каждый второй ряд сдвинут на полплитки; слева появляется
        # обрезок, справа плитка уходит за стену и тоже режется.
        # Каждый ряд уезжает на свою долю: при 1/2 это 0, ½, 0, ½; при 1/3 —
        # 0, ⅓, ⅔, 0 (палубная раскладка, ряды идут лесенкой, а не через один).
        step = tile.width_mm + tile.joint_mm
        shift = 0.0
        if pattern is LayoutPattern.BRICK:
            shift = ((r * offset_ratio) % 1.0) * step
        staggered = shift > 1e-6

        row_cells: list[Cell] = []
        # Первая целая плитка базового ряда — от неё и пляшет разбежка.
        base_x = x.cut_start_mm + tile.joint_mm if x.cut_start_mm > 0 else 0.0
        spans = (
            _staggered_spans(sw, tile.width_mm, tile.joint_mm, shift, base_x)
            if staggered
            else cols
        )

        for cx, cw, cut_x in spans:
            gx = cx
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

        cells.extend(apply_openings(row_cells, surface))

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


ANGLED = (LayoutPattern.DIAGONAL, LayoutPattern.HERRINGBONE)

# Оси для раскладок под 45°: сетка повёрнута, и «подрезка слева/справа» смысла не
# имеет — режется весь периметр. Пустая ось честнее выдуманных цифр.
NO_AXIS = Axis(full=0, cut_start_mm=0.0, cut_end_mm=0.0, total=0)


def _angled_cells(surface: Surface, tile: Tile, pattern: LayoutPattern) -> list[Cell]:
    pieces = angled_pieces(
        surface.width_mm,
        surface.height_mm,
        tile.width_mm,
        tile.height_mm,
        tile.joint_mm,
        herringbone=pattern is LayoutPattern.HERRINGBONE,
    )

    cells = [
        Cell(
            x=piece.bbox[0],
            y=piece.bbox[1],
            w=piece.bbox[2] - piece.bbox[0],
            h=piece.bbox[3] - piece.bbox[1],
            is_cut=piece.is_cut,
            polygon=piece.polygon,
        )
        for piece in pieces
    ]
    return apply_openings(cells, surface)


def _angled_advice(cells: list[Cell], pattern: LayoutPattern) -> list[str]:
    """Что важно знать про 45°: режется много, и это нормально.

    Без цифр: сколько резать, уже написано строкой выше («Класть: N шт, резаных M»),
    а в комнате у каждой стены они свои — и один и тот же совет с разными числами
    сыпался мастеру по четыре раза подряд.
    """
    name = "Диагональ" if pattern is LayoutPattern.DIAGONAL else "Ёлочка"

    out = [
        f"{name}: режется весь периметр — плитки у стен уходят треугольниками. "
        "Это не ошибка замера, так кладётся любая раскладка под 45°.",
        "Каждую крайнюю плитку режут по месту: прикладываешь и чертишь. "
        "Заранее размеры не считаю — у 45° они все разные.",
        "Начинай от центра стены и веди в обе стороны — иначе рисунок уползёт, "
        "и это будет видно.",
    ]
    if pattern is LayoutPattern.HERRINGBONE:
        out.append(
            "Ёлочку кладут парами: одна плитка лёжа, следующая стоя, торец в бок. "
            "Держи угол — на длинной стене ошибка копится."
        )
    return out


def build_layout(
    surface: Surface,
    tile: Tile,
    pattern: LayoutPattern = LayoutPattern.STRAIGHT,
    start_from: StartFrom = StartFrom.EDGE,
    offset_ratio: float = DEFAULT_OFFSET,
) -> Layout:
    """Посчитать раскладку плитки на поверхности."""
    if pattern in ANGLED:
        # Под 45° сетка повёрнута: плитки становятся многоугольниками, а осей нет.
        cells = _angled_cells(surface, tile, pattern)
        return Layout(
            surface=surface,
            tile=tile,
            pattern=pattern,
            start_from=start_from,
            x=NO_AXIS,
            y=NO_AXIS,
            cells=cells,
            advice=_angled_advice(cells, pattern),
        )

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
        cells=build_cells(surface, tile, x, y, pattern, offset_ratio),
        advice=_advice(x, y, tile, surface, start_from),
    )


def best_orientation(
    surface: Surface,
    tile: Tile,
    pattern: LayoutPattern = LayoutPattern.STRAIGHT,
    start_from: StartFrom = StartFrom.EDGE,
    offset_ratio: float = DEFAULT_OFFSET,
) -> tuple[Layout, Layout]:
    """Разложить плитку в обеих ориентациях и вернуть (лучшую, альтернативную).

    Лучшая — та, где самая узкая подрезка шире: меньше риска расколоть полоску и
    аккуратнее выглядит угол.
    """
    normal = build_layout(surface, tile, pattern, start_from, offset_ratio)
    turned = build_layout(surface, tile.rotated(), pattern, start_from, offset_ratio)

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
