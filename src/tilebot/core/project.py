"""Расчёт объекта целиком: сохранённые замеры → раскладки, закупка, сводка.

Раньше это жило внутри telegram-хэндлера, и посчитать объект можно было, только
отправив сообщение. Теперь считает ядро, а бот и miniapp — два способа показать
одни и те же цифры. Разъехаться они не могут: расчёт ровно один.

Здесь только счёт и никакого форматирования: «5 плиток — это 3 упаковки» каждый
канал пишет по-своему, а вот сколько их — решается тут.
"""

import math
from dataclasses import dataclass

from tilebot.core.layout import (
    Layout,
    best_orientation,
    build_layout,
    common_orientation,
)
from tilebot.core.materials import MaterialLine, Materials, calc_materials, merge_materials
from tilebot.core.models import (
    DEFAULT_OFFSET,
    WASTE_BY_PATTERN,
    LayoutPattern,
    SavedSurface,
    StartFrom,
    Surface,
    SurfaceKind,
    Tile,
)
from tilebot.core.wrap import supports_wrap, wrap_savings, wrap_wall_layouts


@dataclass(frozen=True)
class Savings:
    """Что эконом-раскладка сберегла — в плитках и упаковках.

    Упаковки считаются от закупки с запасом, а не от голой сетки: покупают
    целыми пачками, поэтому «−5 плиток» и «−1 упаковка» — разные числа, и
    мастеру важно второе.
    """

    tiles: int
    packs: int


@dataclass(frozen=True)
class ProjectResult:
    """Посчитанный объект: по раскладке на поверхность и одна закупка на всё."""

    layouts: list[Layout]
    materials: list[Materials]
    head: SavedSurface  # параметры, общие для объекта: плитка, запас, затирка

    @property
    def tile(self) -> Tile:
        """Плитка, как она реально легла — с учётом подобранной ориентации."""
        return self.layouts[0].tile

    @property
    def area_m2(self) -> float:
        return sum(lay.surface.net_area_m2 for lay in self.layouts)

    @property
    def tiles_grid(self) -> int:
        return sum(lay.tiles_grid for lay in self.layouts)

    @property
    def cuts_count(self) -> int:
        return sum(lay.cuts_count for lay in self.layouts)

    @property
    def walls(self) -> list[Layout]:
        return [lay for lay in self.layouts if lay.surface.kind is SurfaceKind.WALL]

    @property
    def has_floor(self) -> bool:
        return any(lay.surface.kind is SurfaceKind.FLOOR for lay in self.layouts)

    @property
    def can_wrap(self) -> bool:
        """Можно ли пустить стены лентой по кругу — стен хотя бы две и раскладка позволяет."""
        return len(self.walls) >= 2 and supports_wrap(self.layouts[0].pattern)

    @property
    def purchase(self) -> list[MaterialLine]:
        """Закупка одним списком: метры и упаковки — от суммы, а не от первой стены."""
        return merge_materials(self.materials)

    @property
    def tile_cost(self) -> float | None:
        """Во сколько выйдет плитка, если мастер сам её считает. None — цены нет."""
        if not self.tile.price_per_m2:
            return None
        return sum(m.tile_area_with_waste_m2 for m in self.materials) * self.tile.price_per_m2

    @property
    def advice(self) -> list[str]:
        """Советы по объекту. У стен одинаковой высоты они повторяются — по разу каждый."""
        seen: list[str] = []
        for lay in self.layouts:
            for advice in lay.advice:
                if advice not in seen:
                    seen.append(advice)
        return seen

    @property
    def savings(self) -> Savings | None:
        """Экономия ленты. None — экономии нет или считать нечего.

        Обещать выгоду, которой не вышло, хуже, чем промолчать.
        """
        if not self.head.wrap or len(self.walls) < 2:
            return None

        tile = self.walls[0].tile
        pattern = self.walls[0].pattern
        per_wall, banded = wrap_savings([lay.surface for lay in self.walls], tile, pattern)

        share = WASTE_BY_PATTERN[pattern] if self.head.waste is None else self.head.waste
        buy_normal = math.ceil(per_wall * (1 + share))
        buy_eco = math.ceil(banded * (1 + share))
        diff = buy_normal - buy_eco
        if diff <= 0:
            return None

        packs = 0
        if tile.per_pack:
            packs = math.ceil(buy_normal / tile.per_pack) - math.ceil(buy_eco / tile.per_pack)
        return Savings(tiles=diff, packs=max(0, packs))


def wall_orientation(
    surfaces: list[Surface], tile: Tile, pattern: LayoutPattern, start: StartFrom
) -> Tile | None:
    """Ориентация плитки, общая для всех стен. None — стен меньше двух, выбирать нечего.

    Стены одной комнаты, положенные разной ориентацией, — это брак работы, а не
    экономия подрезки.
    """
    walls = [s for s in surfaces if s.kind is SurfaceKind.WALL]
    if len(walls) < 2:
        return None
    return common_orientation(walls, tile, pattern, start)


def lay_surface(
    surface: Surface,
    tile: Tile,
    pattern: LayoutPattern,
    start: StartFrom,
    *,
    turn: bool = True,
    resolve_start: bool = False,
    offset_ratio: float = DEFAULT_OFFSET,
) -> Layout:
    """Разложить одну поверхность.

    turn=False — ориентация плитки выбрана снаружи (стены комнаты кладутся
    одинаково), поворачивать её под эту стену нельзя.
    resolve_start=True — «реши сам»: перебираем оба старта и берём тот, где
    подрезка шире. Ориентацию перебираем только если вертеть разрешено.
    """
    starts = [StartFrom.EDGE, StartFrom.CENTER] if resolve_start else [start]
    candidates = [
        best_orientation(surface, tile, pattern, s, offset_ratio=offset_ratio)[0]
        if turn
        else build_layout(surface, tile, pattern, s, offset_ratio=offset_ratio)
        for s in starts
    ]
    return max(candidates, key=lambda lay: min(lay.x.min_cut_mm, lay.y.min_cut_mm))


def build_layouts(saved_all: list[SavedSurface], *, resolve_start: bool = False) -> list[Layout]:
    """Разложить все поверхности объекта — в том же порядке, что они сохранены.

    Обычно каждая поверхность считается сама по себе. Эконом-раскладка (wrap)
    ломает это допущение: стены комнаты кладутся ОДНОЙ лентой по кругу, и посчитать
    их порознь нельзя — остаток плитки с одной стены живёт на следующей. Пол в
    ленту не входит, у него своя плитка и свои углы.
    """
    head = saved_all[0]
    # Мастер повернул плитку сам — берём как есть. Иначе бот тут же перевернёт её
    # обратно «как лучше», и кнопка поворота окажется обманкой.
    walls_tile = (
        None
        if head.tile_locked
        else wall_orientation(
            [s.surface for s in saved_all], head.tile, head.pattern, head.start_from
        )
    )

    wall_at = [i for i, s in enumerate(saved_all) if s.surface.kind is SurfaceKind.WALL]
    banded: dict[int, Layout] = {}
    if head.wrap and len(wall_at) >= 2 and supports_wrap(head.pattern):
        tile = walls_tile or head.tile
        band = wrap_wall_layouts(
            [saved_all[i].surface for i in wall_at], tile, head.pattern, head.offset_ratio
        )
        banded = dict(zip(wall_at, band, strict=True))

    out: list[Layout] = []
    for i, saved in enumerate(saved_all):
        if lay := banded.get(i):
            out.append(lay)
            continue
        fixed = walls_tile if saved.surface.kind is SurfaceKind.WALL else None
        out.append(
            lay_surface(
                saved.surface,
                fixed or saved.tile,
                saved.pattern,
                saved.start_from,
                turn=fixed is None and not saved.tile_locked,
                resolve_start=resolve_start,
                offset_ratio=saved.offset_ratio,
            )
        )
    return out


def compute_project(
    saved_all: list[SavedSurface], *, resolve_start: bool = False
) -> ProjectResult:
    """Посчитать объект по сохранённым замерам: раскладки + материалы + сводка.

    Единственная точка счёта: сюда приходят и бот, и API. Замеры мастер вводил
    один раз — второй раз спрашивать их незачем.
    """
    if not saved_all:
        raise ValueError("нечего считать: у объекта нет поверхностей")

    layouts = build_layouts(saved_all, resolve_start=resolve_start)
    materials = [
        calc_materials(
            layout,
            waterproofing=saved.waterproofing,
            waste=saved.waste,
            grout_kind=saved.grout_kind,
        )
        for layout, saved in zip(layouts, saved_all, strict=True)
    ]
    return ProjectResult(layouts=layouts, materials=materials, head=saved_all[0])
