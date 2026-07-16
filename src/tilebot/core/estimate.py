"""Смета: работы по прайсу мастера плюс материалы.

Ответ заказчику «сколько будет стоить» — то, что мастер сейчас считает в голове и
называет цифрой без расшифровки. Смета показывает, за что берутся деньги.
"""

from dataclasses import dataclass, field

from tilebot.core.layout import Layout
from tilebot.core.materials import MaterialLine, Materials, merge_materials, tile_name
from tilebot.core.models import LayoutPattern, SurfaceKind

# Надбавка за сложную раскладку: резать больше, класть дольше.
PATTERN_SURCHARGE: dict[LayoutPattern, float] = {
    LayoutPattern.STRAIGHT: 0.0,
    LayoutPattern.BRICK: 0.0,
    LayoutPattern.DIAGONAL: 0.20,
    LayoutPattern.HERRINGBONE: 0.30,
}


@dataclass
class PriceList:
    """Прайс мастера, ₽. Настраивается под себя — цифры ниже просто дефолт."""

    wall_tiling: float = 1200.0  # укладка плитки на стену, ₽/м²
    floor_tiling: float = 1000.0  # на пол, ₽/м²
    waterproofing: float = 400.0  # гидроизоляция, ₽/м²
    priming: float = 100.0  # грунтовка, ₽/м²
    grouting: float = 200.0  # затирка швов, ₽/м²
    demolition: float = 500.0  # демонтаж старой плитки, ₽/м²
    min_order: float = 0.0  # минимальный чек за выезд


@dataclass(frozen=True)
class WorkLine:
    name: str
    qty: float
    unit: str
    price: float

    @property
    def total(self) -> float:
        return self.qty * self.price


@dataclass
class Estimate:
    """Смета по объекту."""

    title: str
    works: list[WorkLine] = field(default_factory=list)
    materials: list[MaterialLine] = field(default_factory=list)
    material_costs: dict[str, float] = field(default_factory=dict)  # название → ₽ всего
    note: str = ""

    @property
    def works_total(self) -> float:
        return sum(w.total for w in self.works)

    @property
    def materials_total(self) -> float:
        return sum(self.material_costs.values())

    @property
    def grand_total(self) -> float:
        return self.works_total + self.materials_total


def build_estimate(
    title: str,
    layouts: list[Layout],
    materials: list[Materials],
    price: PriceList,
    *,
    waterproofing: bool = False,
    demolition_m2: float = 0.0,
    include_materials_cost: bool = True,
) -> Estimate:
    """Смета по объекту: работы по площадям поверхностей + материалы по ценам плитки.

    Материалы считаем в деньгах только там, где мастер задал цену: плитка знает
    свою цену за м², остальное (клей, затирка) он обычно покупает по факту, и
    выдумывать за него цену мешка мы не будем.
    """
    est = Estimate(title=title)

    wall_area = sum(
        lay.surface.net_area_m2 for lay in layouts if lay.surface.kind is SurfaceKind.WALL
    )
    floor_area = sum(
        lay.surface.net_area_m2 for lay in layouts if lay.surface.kind is SurfaceKind.FLOOR
    )
    total_area = wall_area + floor_area

    # Надбавку за раскладку берём по самой сложной поверхности объекта.
    surcharge = max((PATTERN_SURCHARGE[lay.pattern] for lay in layouts), default=0.0)

    if wall_area > 0:
        est.works.append(
            WorkLine("Укладка плитки, стены", round(wall_area, 2), "м²", price.wall_tiling)
        )
    if floor_area > 0:
        est.works.append(
            WorkLine("Укладка плитки, пол", round(floor_area, 2), "м²", price.floor_tiling)
        )
    if surcharge > 0 and total_area > 0:
        pattern_name = max(layouts, key=lambda lay: PATTERN_SURCHARGE[lay.pattern]).pattern
        base = wall_area * price.wall_tiling + floor_area * price.floor_tiling
        est.works.append(
            WorkLine(
                f"Надбавка за раскладку ({pattern_name.value}), +{surcharge:.0%}",
                1,
                "",
                round(base * surcharge, 2),
            )
        )

    if total_area > 0:
        est.works.append(WorkLine("Грунтование", round(total_area, 2), "м²", price.priming))
        est.works.append(WorkLine("Затирка швов", round(total_area, 2), "м²", price.grouting))
    if waterproofing and total_area > 0:
        est.works.append(
            WorkLine("Гидроизоляция", round(total_area, 2), "м²", price.waterproofing)
        )
    if demolition_m2 > 0:
        est.works.append(
            WorkLine("Демонтаж старой плитки", round(demolition_m2, 2), "м²", price.demolition)
        )

    est.materials = merge_materials(materials)

    if include_materials_cost:
        for lay, m in zip(layouts, materials, strict=True):
            if lay.tile.price_per_m2:
                key = tile_name(lay.tile)
                cost = m.tile_area_with_waste_m2 * lay.tile.price_per_m2
                est.material_costs[key] = est.material_costs.get(key, 0.0) + round(cost, 2)

    if price.min_order and est.works_total < price.min_order:
        est.works.append(
            WorkLine("Добор до минимального заказа", 1, "", price.min_order - est.works_total)
        )

    if not est.material_costs:
        est.note = "Стоимость материалов не считалась — цена плитки не задана."

    return est


def money(value: float) -> str:
    """Деньги с неразрывным пробелом между тысячами: 63 146 ₽."""
    return f"{value:,.0f}".replace(",", " ") + " ₽"


def format_estimate(est: Estimate) -> str:
    """Смета текстом — можно переслать заказчику прямо из Telegram."""
    lines = [f"<b>Смета — {est.title}</b>", "", "<b>Работы</b>"]
    for w in est.works:
        if w.unit:
            qty = f"{w.qty:g} {w.unit}"
            lines.append(f"• {w.name}: {qty} × {money(w.price)} = <b>{money(w.total)}</b>")
        else:
            lines.append(f"• {w.name}: <b>{money(w.total)}</b>")
    lines.append(f"Работы итого: <b>{money(est.works_total)}</b>")

    lines += ["", "<b>Материалы</b>"]
    for m in est.materials:
        cost = est.material_costs.get(m.name)
        tail = f" — {money(cost)}" if cost else ""
        lines.append(f"• {m.name}: {m.format_qty()} {m.unit}{tail}")
    if est.materials_total:
        lines.append(f"Материалы итого: <b>{money(est.materials_total)}</b>")

    lines += ["", f"<b>ВСЕГО: {money(est.grand_total)}</b>"]
    if est.note:
        lines += ["", f"<i>{est.note}</i>"]

    return "\n".join(lines)
