"""Расход материалов на укладку.

Нормы — усреднённые по производителям (Ceresit, Litokol, Vetonit); мешок мешку
рознь, поэтому расчёт всегда показывает, из какой нормы исходил, и норму можно
переопределить.
"""

import math
from dataclasses import dataclass

from tilebot.core.layout import Layout
from tilebot.core.models import WASTE_BY_PATTERN, SurfaceKind, Tile

# Гребёнка (высота зуба) по размеру плитки и средний расход сухой смеси.
# Ключ — наибольшая сторона плитки в мм (верхняя граница диапазона).
TROWEL_TABLE: list[tuple[float, int, float]] = [
    # (макс. сторона плитки, зуб гребёнки мм, расход клея кг/м²)
    (100, 4, 2.5),
    (200, 6, 3.5),
    (300, 8, 4.5),
    (600, 10, 6.0),
    (1200, 12, 7.5),
    (math.inf, 15, 9.0),
]

GROUT_DENSITY = 1.6  # кг/дм³, цементная затирка
PRIMER_L_PER_M2 = 0.15  # грунтовка, литров на м² в один слой
WATERPROOF_KG_PER_M2 = 1.4  # обмазочная гидроизоляция, кг/м² в два слоя
LEVELING_CLIPS_PER_TILE = 4  # СВП: зажимов на плитку
CROSSES_PER_TILE = 4  # крестики на плитку


@dataclass(frozen=True)
class MaterialLine:
    """Строка списка закупки."""

    name: str
    qty: float
    unit: str
    note: str = ""

    def format_qty(self) -> str:
        if self.unit == "шт" or self.qty >= 100:
            return f"{self.qty:.0f}"
        return f"{self.qty:.1f}".rstrip("0").rstrip(".")


@dataclass(frozen=True)
class Materials:
    """Что нужно купить на одну поверхность или на объект целиком."""

    area_m2: float  # нетто, без запаса
    tile_area_with_waste_m2: float
    tiles_count: int  # штук плитки с запасом
    packs: int | None
    lines: list[MaterialLine]


def trowel_for(tile: Tile) -> tuple[int, float]:
    """Гребёнка и норма расхода клея под размер плитки."""
    side = max(tile.width_mm, tile.height_mm)
    for max_side, teeth, kg in TROWEL_TABLE:
        if side <= max_side:
            return teeth, kg
    raise AssertionError("TROWEL_TABLE должна покрывать любой размер")


def grout_kg_per_m2(tile: Tile) -> float:
    """Расход затирки, кг/м².

    Классическая формула: ((A+B)/(A*B)) * толщина плитки * ширина шва * плотность,
    все размеры в мм.
    """
    a, b = tile.width_mm, tile.height_mm
    if a <= 0 or b <= 0 or tile.joint_mm <= 0:
        return 0.0
    return ((a + b) / (a * b)) * tile.thickness_mm * tile.joint_mm * GROUT_DENSITY


def tile_glue_kg(area_m2: float, tile: Tile) -> tuple[float, int]:
    """Клей на площадь: (кг, зуб гребёнки)."""
    teeth, kg_per_m2 = trowel_for(tile)
    return area_m2 * kg_per_m2, teeth


def calc_materials(
    layout: Layout,
    *,
    waterproofing: bool = False,
    use_leveling_system: bool = True,
) -> Materials:
    """Список закупки под одну разложенную поверхность."""
    tile = layout.tile
    surface = layout.surface
    area = surface.net_area_m2
    waste = WASTE_BY_PATTERN[layout.pattern]

    # Плитку считаем по сетке раскладки, а не «площадь ÷ площадь плитки»: подрезка
    # из целой плитки, обрезки в дело идут не всегда. Запас — сверху на бой.
    tiles = math.ceil(layout.tiles_grid * (1 + waste))
    tile_area_waste = tiles * tile.area_m2
    packs = math.ceil(tiles / tile.per_pack) if tile.per_pack else None

    glue, teeth = tile_glue_kg(area, tile)
    grout = area * grout_kg_per_m2(tile)

    lines: list[MaterialLine] = [
        MaterialLine(
            name=f"Плитка {tile.width_mm:.0f}×{tile.height_mm:.0f}",
            qty=tiles,
            unit="шт",
            note=(
                f"{tile_area_waste:.1f} м² с запасом {waste:.0%}"
                + (f", ≈{packs} уп." if packs else "")
            ),
        ),
        MaterialLine(
            name="Плиточный клей",
            qty=math.ceil(glue),
            unit="кг",
            note=f"гребёнка {teeth} мм; мешков 25 кг ≈ {math.ceil(glue / 25)}",
        ),
        MaterialLine(
            name=f"Затирка (шов {tile.joint_mm:.0f} мм)",
            qty=max(1.0, math.ceil(grout * 10) / 10),
            unit="кг",
            note=f"{grout_kg_per_m2(tile):.2f} кг/м²",
        ),
        MaterialLine(
            name="Грунтовка",
            qty=math.ceil(area * PRIMER_L_PER_M2 * 10) / 10,
            unit="л",
            note=f"{PRIMER_L_PER_M2} л/м², один слой",
        ),
    ]

    if use_leveling_system:
        clips = layout.tiles_grid * LEVELING_CLIPS_PER_TILE
        lines.append(
            MaterialLine(
                name="СВП, зажимы",
                qty=clips,
                unit="шт",
                note=f"≈{LEVELING_CLIPS_PER_TILE} на плитку; клинья многоразовые",
            )
        )
    else:
        lines.append(
            MaterialLine(
                name="Крестики",
                qty=layout.tiles_grid * CROSSES_PER_TILE,
                unit="шт",
                note=f"{tile.joint_mm:.0f} мм",
            )
        )

    if waterproofing:
        lines.append(
            MaterialLine(
                name="Гидроизоляция обмазочная",
                qty=math.ceil(area * WATERPROOF_KG_PER_M2),
                unit="кг",
                note=f"{WATERPROOF_KG_PER_M2} кг/м², два слоя",
            )
        )
        if surface.kind is SurfaceKind.FLOOR:
            lines.append(
                MaterialLine(
                    name="Гидроизоляционная лента",
                    qty=math.ceil(2 * (surface.width_mm + surface.height_mm) / 1000),
                    unit="м",
                    note="по периметру, в углы",
                )
            )

    return Materials(
        area_m2=area,
        tile_area_with_waste_m2=tile_area_waste,
        tiles_count=tiles,
        packs=packs,
        lines=lines,
    )


def merge_materials(items: list[Materials]) -> list[MaterialLine]:
    """Свести закупку по нескольким поверхностям в один список.

    Ровно то, что Саша сейчас делает на бумажке: посчитал стену, посчитал вторую,
    потом сложил.
    """
    bucket: dict[tuple[str, str], float] = {}
    notes: dict[tuple[str, str], str] = {}
    for m in items:
        for line in m.lines:
            key = (line.name, line.unit)
            bucket[key] = bucket.get(key, 0.0) + line.qty
            notes.setdefault(key, line.note)

    out = []
    for (name, unit), qty in bucket.items():
        note = notes[(name, unit)]
        if name == "Плиточный клей":
            note = f"мешков 25 кг ≈ {math.ceil(qty / 25)}"
        out.append(MaterialLine(name=name, qty=qty, unit=unit, note=note))
    return out
