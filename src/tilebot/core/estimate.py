"""Смета: работа мастера по его прайсу.

Ответ заказчику «сколько будет стоить» — то, что мастер сейчас считает в голове и
называет цифрой без расшифровки. Смета показывает, за что берутся деньги.

Деньги за материалы сюда не идут: мастер продаёт работу, а плитку заказчик покупает
сам — по списку покупок, который считается отдельно. Посчитать материалы в рублях
можно, если мастер закупается сам, но это его отдельная история, а не строка в
счёте заказчику.
"""

import math
from dataclasses import dataclass, field

from tilebot.core.layout import Layout
from tilebot.core.materials import MaterialLine, Materials, merge_materials
from tilebot.core.models import GroutKind, LayoutPattern, SurfaceKind

# По-русски, а не enum'ом: строка уходит заказчику в смету.
PATTERN_TITLES: dict[LayoutPattern, str] = {
    LayoutPattern.STRAIGHT: "шов в шов",
    LayoutPattern.BRICK: "вразбежку",
    LayoutPattern.DIAGONAL: "диагональ",
    LayoutPattern.HERRINGBONE: "ёлочка",
}

# Надбавка за сложную раскладку: класть дольше, рисунок надо держать. Рез считается
# отдельной строкой — по фактическому числу подрезанных плиток.
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
    grouting: float = 200.0  # затирка швов цементной, ₽/м²
    grouting_epoxy: float = 450.0  # эпоксидной — дольше и муторнее, ₽/м²
    demolition: float = 500.0  # демонтаж старой плитки, ₽/м²
    cutting: float = 60.0  # рез плитки, ₽/шт — считается по факту раскладки
    min_order: float = 0.0  # минимальный чек за выезд

    # Справочные цены материалов — чтобы в смете была прикидка «во сколько выйдет
    # всё». Это ориентир, а не счёт: заказчик покупает сам и может взять дешевле
    # или дороже. Цифры — средние по рынку на июль 2026, правятся в прайсе.
    mat_tile_m2: float = 1500.0  # плитка, ₽/м² — разброс самый большой
    mat_glue_kg: float = 18.0  # мешок 25 кг ≈ 450 ₽
    mat_grout_kg: float = 175.0  # цементная, пачка 2 кг ≈ 350 ₽
    mat_grout_epoxy_kg: float = 1200.0  # эпоксидная, от 1899 ₽ за упаковку
    mat_primer_l: float = 80.0  # канистра 10 л ≈ 800 ₽
    mat_waterproof_kg: float = 150.0  # ведро 20 кг ≈ 3000 ₽
    mat_clip_pcs: float = 4.0  # СВП-зажимы, 100 шт ≈ 400 ₽
    mat_cross_pcs: float = 1.0  # крестики, 100 шт ≈ 100 ₽
    mat_tape_m: float = 150.0  # гидроизоляционная лента, ₽/м


# Какая цена прайса отвечает за какой материал. Плитка считается по площади с
# запасом, остальное — по количеству в списке покупок.
MATERIAL_PRICE_FIELDS: dict[str, str] = {
    "tile": "mat_tile_m2",
    "glue": "mat_glue_kg",
    "grout": "mat_grout_kg",
    "grout_epoxy": "mat_grout_epoxy_kg",
    "primer": "mat_primer_l",
    "waterproof": "mat_waterproof_kg",
    "clips": "mat_clip_pcs",
    "crosses": "mat_cross_pcs",
    "tape": "mat_tape_m",
}


def tile_paid_area_m2(line: MaterialLine) -> float:
    """Метры, за которые придётся заплатить.

    Цену плитки пишут за м², но продают её упаковками: нужна 21.5 пачки — берёшь 22
    и платишь за все. Считать по голой площади — занижать чек.
    """
    if not line.per_pack or not line.qty:
        return line.area_m2 or 0.0
    tile_area = (line.area_m2 or 0.0) / line.qty  # площадь одной плитки
    packs = math.ceil(line.qty / line.per_pack)
    return packs * line.per_pack * tile_area


def rough_material_cost(line: MaterialLine, price: PriceList) -> float:
    """Прикидка стоимости строки закупки по справочным ценам."""
    field = MATERIAL_PRICE_FIELDS.get(line.kind)
    if not field:
        return 0.0
    rate = getattr(price, field, 0.0)
    if line.kind == "tile":
        return tile_paid_area_m2(line) * rate
    return line.qty * rate


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
    material_costs: dict[str, float] = field(default_factory=dict)  # факт: название → ₽
    rough_costs: dict[str, float] = field(default_factory=dict)  # прикидка по справочным
    note: str = ""

    @property
    def works_total(self) -> float:
        return sum(w.total for w in self.works)

    @property
    def materials_total(self) -> float:
        """Материалы по факту — то, что мастер реально потратил."""
        return sum(self.material_costs.values())

    @property
    def rough_materials_total(self) -> float:
        """Прикидка материалов: факт там, где он известен, справочная цена — где нет."""
        return sum(self.material_costs.values()) + sum(self.rough_costs.values())

    @property
    def grand_total(self) -> float:
        return self.works_total + self.materials_total

    @property
    def rough_total(self) -> float:
        """Во сколько примерно обойдётся всё — работа плюс материалы."""
        return self.works_total + self.rough_materials_total


def build_estimate(
    title: str,
    layouts: list[Layout],
    materials: list[Materials],
    price: PriceList,
    *,
    waterproofing: bool = False,
    demolition_m2: float = 0.0,
    include_materials_cost: bool = True,
    grout_kind: GroutKind = GroutKind.CEMENT,
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
                f"Надбавка за раскладку ({PATTERN_TITLES[pattern_name]}), +{surcharge:.0%}",
                1,
                "",
                round(base * surcharge, 2),
            )
        )

    # Рез — отдельная работа, а не часть укладки: на диагонали режется весь периметр,
    # и это руками, по одной плитке. Надбавка за раскладку — за сложность самой
    # кладки (рисунок, углы), а рез считаем по факту: сколько плиток, столько и резов.
    cuts = sum(lay.cuts_count for lay in layouts)
    if cuts and price.cutting:
        est.works.append(
            WorkLine("Подрезка плитки", cuts, "шт", price.cutting)
        )

    if total_area > 0:
        est.works.append(WorkLine("Грунтование", round(total_area, 2), "м²", price.priming))
        # Эпоксидную затирать дольше и муторнее — это дороже в работе, а не в мешке.
        epoxy = grout_kind is GroutKind.EPOXY
        est.works.append(
            WorkLine(
                "Затирка швов" + (" эпоксидной" if epoxy else ""),
                round(total_area, 2),
                "м²",
                price.grouting_epoxy if epoxy else price.grouting,
            )
        )
    if waterproofing and total_area > 0:
        est.works.append(
            WorkLine("Гидроизоляция", round(total_area, 2), "м²", price.waterproofing)
        )
    if demolition_m2 > 0:
        est.works.append(
            WorkLine("Демонтаж старой плитки", round(demolition_m2, 2), "м²", price.demolition)
        )

    est.materials = merge_materials(materials)

    # Деньги за материалы бывают двух сортов и путать их нельзя. Точные — это то,
    # что мастер реально отдал в кассе (знаем, если он вбил цену плитки): идут в
    # акт. Прикидка по справочным ценам — ориентир для сметы, чтобы заказчик
    # понимал масштаб; взять он может дешевле или дороже.
    if include_materials_cost:
        for line in est.materials:
            if line.kind != "tile":
                continue
            tile_price = next(
                (lay.tile.price_per_m2 for lay in layouts if lay.tile.price_per_m2), None
            )
            if tile_price:
                # Платим за упаковки целиком — как в магазине.
                cost = tile_paid_area_m2(line) * tile_price
                est.material_costs[line.name] = round(cost, 2)

    known_tile_price = any(lay.tile.price_per_m2 for lay in layouts)
    for line in est.materials:
        if line.kind == "tile" and known_tile_price and include_materials_cost:
            continue  # цену плитки мастер знает точно — прикидка не нужна
        est.rough_costs[line.name] = round(rough_material_cost(line, price), 2)

    if price.min_order and est.works_total < price.min_order:
        est.works.append(
            WorkLine("Добор до минимального заказа", 1, "", price.min_order - est.works_total)
        )

    return est


def money(value: float) -> str:
    """Деньги с неразрывным пробелом между тысячами: 63 146 ₽."""
    return f"{value:,.0f}".replace(",", " ") + " ₽"


def _qty_with_packs(line: MaterialLine) -> str:
    """«172 шт (22 уп.)» — в магазине плитку берут пачками, а не штуками."""
    base = f"{line.format_qty()} {line.unit}"
    if line.kind == "tile" and line.per_pack:
        packs = math.ceil(line.qty / line.per_pack)
        return f"{base} ({packs} уп.)"
    return base


def _work_lines(est: Estimate) -> list[str]:
    lines = []
    for w in est.works:
        if w.unit:
            qty = f"{w.qty:g} {w.unit}"
            lines.append(f"• {w.name}: {qty} × {money(w.price)} = <b>{money(w.total)}</b>")
        else:
            lines.append(f"• {w.name}: <b>{money(w.total)}</b>")
    return lines


def format_estimate(est: Estimate) -> str:
    """Смета — документ ДО работ: сколько будет стоить и что купить.

    Итог — это работа мастера. Материалы идут ниже списком: заказчик покупает их
    сам, и складывать их с работой в одну цифру нечестно — выглядело бы так, будто
    мастер берёт эти деньги себе.
    """
    lines = [f"<b>Смета — {est.title}</b>", "", "<b>Работы</b>"]
    lines += _work_lines(est)
    lines += ["", f"<b>РАБОТА: {money(est.works_total)}</b>"]

    lines += ["", "<b>Материалы — купить</b>"]
    for m in est.materials:
        rough = est.rough_costs.get(m.name) or est.material_costs.get(m.name)
        tail = f" ≈ {money(rough)}" if rough else ""
        lines.append(f"• {m.name}: {_qty_with_packs(m)}{tail}")

    if est.rough_materials_total:
        lines += [
            "",
            f"Материалы ≈ <b>{money(est.rough_materials_total)}</b>",
            f"<b>ВСЁ ВМЕСТЕ ≈ {money(est.rough_total)}</b>",
            "",
            "<i>Материалы заказчик покупает сам, в стоимость работы они не входят. "
            "Цены примерные, для ориентира — можно взять дешевле или дороже.</i>",
        ]
    else:
        lines.append("\n<i>Материалы в стоимость работы не входят — покупаются отдельно.</i>")

    if est.note:
        lines += ["", f"<i>{est.note}</i>"]

    return "\n".join(lines)


def format_act(est: Estimate) -> str:
    """Акт — документ ПОСЛЕ работ: что сделано, что закуплено, сколько к оплате.

    Смету составляют заранее и по прайсу, а акт — по факту: мастер уже отработал и
    закупился на свои, и заказчику надо вернуть деньги за материалы и заплатить за
    работу. Поэтому здесь, в отличие от сметы, материалы в итог входят.
    """
    lines = [f"<b>Акт выполненных работ — {est.title}</b>", "", "<b>Выполнено</b>"]
    lines += _work_lines(est)
    lines += ["", f"Работа: <b>{money(est.works_total)}</b>"]

    if est.materials:
        lines += ["", "<b>Материалы</b>"]
        for m in est.materials:
            cost = est.material_costs.get(m.name)
            tail = f" — <b>{money(cost)}</b>" if cost else " <i>(куплено заказчиком)</i>"
            lines.append(f"• {m.name}: {_qty_with_packs(m)}{tail}")

    if est.materials_total:
        lines.append(f"\nМатериалы: <b>{money(est.materials_total)}</b>")

    lines += ["", f"<b>ИТОГО К ОПЛАТЕ: {money(est.grand_total)}</b>"]
    if est.note:
        lines += ["", f"<i>{est.note}</i>"]

    return "\n".join(lines)
