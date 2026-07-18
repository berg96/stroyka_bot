"""Виды работ помимо плитки: штукатурка, ламинат, плинтус, откосы, сантехника.

Одна комната = замеры (стены/высота/пол — раз) + несколько работ, каждая берёт
нужную геометрию из замеров. Здесь только чистый расчёт: вход + прайс → строки
работы и список материалов. Никакого Telegram и БД — калькуляторы тестируются
отдельно, как ядро плитки.

Модель по брифу Артёма 18.07: держим ПРОСТО (Саня «теряется», телефон слабый).
Сантехника — список точек × цена, без штроб/труб.
"""

import math
from dataclasses import dataclass, field
from enum import StrEnum

from tilebot.core.estimate import PriceList, WorkLine
from tilebot.core.materials import MaterialLine


class WorkKind(StrEnum):
    TILE = "tile"  # считается отдельным ядром (core/project), тут только для полноты
    PLASTER = "plaster"  # штукатурка/шпаклёвка
    LAMINATE = "laminate"
    BASEBOARD = "baseboard"  # плинтус
    REVEALS = "reveals"  # откосы
    PLUMBING = "plumbing"  # сантехника (точки)


WORK_NAME: dict[str, str] = {
    WorkKind.TILE: "Плитка",
    WorkKind.PLASTER: "Штукатурка",
    WorkKind.LAMINATE: "Ламинат",
    WorkKind.BASEBOARD: "Плинтус",
    WorkKind.REVEALS: "Откосы",
    WorkKind.PLUMBING: "Сантехника",
}


@dataclass(frozen=True)
class WorkResult:
    """Итог одной работы: строки работы, материалы, и «герой» для карточки."""

    kind: WorkKind
    work_lines: list[WorkLine] = field(default_factory=list)
    materials: list[MaterialLine] = field(default_factory=list)
    hero_value: str = ""  # крупно на карточке: «20,5 м²», «4 точки»
    hero_note: str = ""  # под ним: «6 мешков», «≈»

    @property
    def work_sum(self) -> float:
        return sum(w.total for w in self.work_lines)


def _fmt(v: float) -> str:
    """Число по-русски: 20.5 → «20,5», 156.0 → «156»."""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


# --- Штукатурка / шпаклёвка ---------------------------------------------------


def plaster(area_m2: float, *, layers: int, kg_per_m2: float, price: PriceList) -> WorkResult:
    """Стены/потолок: работа по площади + смесь мешками.

    Расход смеси зависит от материала (шпаклёвка ~1.2 кг/м²/слой, штукатурка ~9) —
    берём параметром, дефолт мастер правит.
    """
    area = max(0.0, area_m2)
    work = [WorkLine("Штукатурка/шпаклёвка", round(area, 2), "м²", price.plastering)]
    kg = area * kg_per_m2 * max(1, layers)
    bags = math.ceil(kg / 25) if kg else 0
    mats = [
        MaterialLine(
            "Смесь штукатурная", bags, "мешков",
            note=f"{_fmt(kg_per_m2)} кг/м² × {layers} сл. ≈ {math.ceil(kg)} кг",
            kind="plaster",
        )
    ]
    return WorkResult(
        WorkKind.PLASTER, work, mats,
        hero_value=f"{_fmt(area)} м²", hero_note=f"{bags} мешк.",
    )


# --- Ламинат ------------------------------------------------------------------


def laminate(
    floor_m2: float, *, pack_m2: float, waste: float, underlay: bool, price: PriceList
) -> WorkResult:
    """Пол: работа по площади + пачки ламината (с запасом) + подложка."""
    area = max(0.0, floor_m2)
    work = [WorkLine("Укладка ламината", round(area, 2), "м²", price.laminate_laying)]
    packs = math.ceil(area * (1 + waste) / pack_m2) if area and pack_m2 > 0 else 0
    mats = [
        MaterialLine(
            "Ламинат", packs, "пачек",
            note=f"{_fmt(area)} м² + запас {round(waste * 100)}%, пачка {_fmt(pack_m2)} м²",
            kind="laminate",
        )
    ]
    if underlay:
        mats.append(MaterialLine("Подложка", round(area, 2), "м²", kind="underlay"))
    return WorkResult(
        WorkKind.LAMINATE, work, mats,
        hero_value=f"{_fmt(area)} м²", hero_note=f"{packs} пачек",
    )


# --- Плинтус ------------------------------------------------------------------


def baseboard(
    perimeter_m: float, *, plank_m: float, corners: int, price: PriceList
) -> WorkResult:
    """Напольный плинтус: работа по пог.м + планки + фурнитура (углы/заглушки/стыки)."""
    per = max(0.0, perimeter_m)
    work = [WorkLine("Монтаж плинтуса", round(per, 2), "пог.м", price.baseboard_mount)]
    planks = math.ceil(per / plank_m) if per and plank_m > 0 else 0
    # фурнитура: по углу + по стыку между планками
    joints = max(0, planks - 1)
    fittings = max(0, corners) + joints
    mats = [
        MaterialLine("Плинтус (планка)", planks, "шт",
                     note=f"{_fmt(per)} пог.м, планка {_fmt(plank_m)} м", kind="baseboard"),
    ]
    if fittings:
        mats.append(MaterialLine(
            "Уголки, заглушки, стыки", fittings, "шт",
            note=f"{corners} углов + {joints} стыков", kind="baseboard_corner"))
    return WorkResult(
        WorkKind.BASEBOARD, work, mats,
        hero_value=f"{_fmt(per)} пог.м", hero_note=f"{planks} планок",
    )


# --- Откосы -------------------------------------------------------------------


@dataclass(frozen=True)
class Opening:
    """Проём под откос: окно или дверь."""

    name: str
    width_m: float
    height_m: float
    is_door: bool = False


def reveals(openings: list[Opening], *, reveal_width_cm: float, price: PriceList) -> WorkResult:
    """Откосы по проёмам: у окна три стороны (2 боковые + верх), у двери — тоже верх и
    две боковые (низ у двери нет). Площадь = периметр откоса × ширина откоса."""
    w = reveal_width_cm / 100
    total = 0.0
    for o in openings:
        # окно: 2×высота + ширина (верх) [низ обычно подоконник, не откос]
        # дверь: 2×высота + ширина (верх)
        run = 2 * o.height_m + o.width_m
        total += run * w
    total = round(total, 2)
    work = [WorkLine("Откосы", total, "м²", price.reveals)]
    return WorkResult(
        WorkKind.REVEALS, work, [],
        hero_value=f"{len(openings)} проём." if openings else "0 проёмов",
        hero_note=f"{_fmt(total)} м²",
    )


# --- Сантехника (точки) -------------------------------------------------------

# Точки по умолчанию: имя → ориентировочная цена (правится мастером под объект).
# Саня: цены индивидуальны, поэтому это лишь стартовые ориентиры.
PLUMBING_POINTS: list[tuple[str, float]] = [
    ("Раковина", 3500),
    ("Ванна / душ", 5000),
    ("Унитаз", 3000),
    ("Инсталляция", 6000),
    ("Стиральная машина", 3000),
    ("Полотенцесушитель", 4000),
    ("Смеситель", 1500),
    ("Гигиенический душ", 2500),
]


def plumbing(points: list[dict]) -> WorkResult:
    """Сантехника — сумма отмеченных точек. points: [{name, price, on}].

    Никакого расчёта штроб/труб — только выбранные точки по своей цене (Саня просил
    не усложнять). Материалы мастер закупает индивидуально. Сумму держим в строке
    как qty=1 × price=сумма, чтобы WorkLine.total её отдал.
    """
    chosen = [p for p in points if p.get("on")]
    total = sum(float(p.get("price", 0)) for p in chosen)
    names = ", ".join(p["name"] for p in chosen) or "точки не выбраны"
    work = [WorkLine(f"Сантехника ({len(chosen)} точ.): {names}", 1, "", total)]
    return WorkResult(
        WorkKind.PLUMBING, work, [],
        hero_value=f"{len(chosen)} точ." if chosen else "0 точек",
        hero_note="≈",
    )


# --- Геометрия из замеров комнаты и диспетчер --------------------------------
#
# Замеры: {"walls": [длины, м], "height_m": .., "floor_m2": ..}. Каждый вид работ
# берёт нужное: штукатурка — площадь стен, ламинат — пол, плинтус — периметр.


def wall_area_m2(m: dict) -> float:
    return sum(m.get("walls") or []) * (m.get("height_m") or 0)


def floor_area_m2(m: dict) -> float:
    return m.get("floor_m2") or 0.0


def perimeter_m(m: dict) -> float:
    return sum(m.get("walls") or [])


def default_input(kind: str, measures: dict) -> dict:
    """Дефолты новой работы — чтобы открывалась уже посчитанной («бот думает»)."""
    if kind == WorkKind.PLASTER:
        return {"surface": "walls", "layers": 1, "kg_per_m2": 1.2}
    if kind == WorkKind.LAMINATE:
        return {"pack_m2": 2.1, "waste": 0.05, "underlay": True}
    if kind == WorkKind.BASEBOARD:
        return {
            "perimeter_m": round(perimeter_m(measures), 2),
            "plank_m": 2.5,
            "corners": len(measures.get("walls") or []) or 4,
        }
    if kind == WorkKind.REVEALS:
        return {"openings": [], "reveal_width_cm": 25}
    if kind == WorkKind.PLUMBING:
        return {"points": [{"name": n, "price": p, "on": False} for n, p in PLUMBING_POINTS]}
    return {}


def compute_work(kind: str, inp: dict, measures: dict, price: PriceList) -> WorkResult:
    """Посчитать работу: её вход + замеры комнаты → результат нужным калькулятором.

    Пустое `area_m2`/`perimeter_m` во входе = «взять из замеров»; заданное — мастер
    переопределил вручную.
    """
    if kind == WorkKind.PLASTER:
        area = inp.get("area_m2")
        if area is None:
            area = wall_area_m2(measures) if inp.get("surface", "walls") == "walls" else 0.0
        return plaster(area, layers=int(inp.get("layers", 1)),
                       kg_per_m2=float(inp.get("kg_per_m2", 1.2)), price=price)
    if kind == WorkKind.LAMINATE:
        area = inp.get("area_m2")
        if area is None:
            area = floor_area_m2(measures)
        return laminate(area, pack_m2=float(inp.get("pack_m2", 2.1)),
                        waste=float(inp.get("waste", 0.05)),
                        underlay=bool(inp.get("underlay", True)), price=price)
    if kind == WorkKind.BASEBOARD:
        per = inp.get("perimeter_m")
        if per is None:
            per = perimeter_m(measures)
        return baseboard(float(per), plank_m=float(inp.get("plank_m", 2.5)),
                         corners=int(inp.get("corners", 4)), price=price)
    if kind == WorkKind.REVEALS:
        ops = [
            Opening(o.get("name", "Проём"), float(o.get("width_m", 0)),
                    float(o.get("height_m", 0)), bool(o.get("is_door", False)))
            for o in inp.get("openings", [])
        ]
        return reveals(ops, reveal_width_cm=float(inp.get("reveal_width_cm", 25)), price=price)
    if kind == WorkKind.PLUMBING:
        return plumbing(inp.get("points", []))
    raise ValueError(f"неизвестный вид работ: {kind}")
