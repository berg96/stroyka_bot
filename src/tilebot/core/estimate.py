"""Смета: работа мастера по его прайсу.

Ответ заказчику «сколько будет стоить» — то, что мастер сейчас считает в голове и
называет цифрой без расшифровки. Смета показывает, за что берутся деньги.

Деньги за материалы сюда не идут: мастер продаёт работу, а плитку заказчик покупает
сам — по списку покупок, который считается отдельно.

Справочных цен на материалы у нас нет вовсе (выпилены 01.08 по решению Артёма).
Кто покупает — мастер или заказчик — ситуативно, от объекта к объекту, поэтому
выдуманная средняя цена мешка молча уезжала в счёт заказчику: в акте она входила
в «ИТОГО К ОПЛАТЕ», то есть он платил за то, чего мастер не тратил. В деньги идёт
только факт — цена плитки, которую мастер вбил сам, и закупки по чекам из «Денег»
объекта (`Estimate.receipts_total`). Всё прочее в акте помечается «куплено заказчиком».
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

    # Другие виды работ (расширение 18.07), ₽ за единицу работы.
    plastering: float = 350.0  # штукатурка/шпаклёвка стен, ₽/м²
    laminate_laying: float = 600.0  # укладка ламината, ₽/м²
    baseboard_mount: float = 200.0  # монтаж плинтуса, ₽/пог.м
    reveals: float = 800.0  # откосы, ₽/м²

    # Справочных цен материалов в прайсе нет: см. модуль-докстринг. Старые ключи
    # `mat_*` из БД отбрасывает `from_dict` в storage.


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
    # Закупки мастера по чекам («Деньги» объекта): он купил на свои, заказчик вернёт.
    receipts_total: float = 0.0
    note: str = ""

    @property
    def works_total(self) -> float:
        return sum(w.total for w in self.works)

    @property
    def materials_total(self) -> float:
        """Материалы по факту — то, что мастер реально потратил."""
        return sum(self.material_costs.values())

    @property
    def grand_total(self) -> float:
        return self.works_total + self.materials_total + self.receipts_total


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

    # Деньги за материалы идут только в акт (`include_materials_cost`) и только по
    # факту: цена плитки, которую мастер вбил сам. Клей, затирку и прочее он то
    # покупает сам, то не покупает — гадать за него ценой мешка мы не будем, в
    # акте такая строка помечается «куплено заказчиком».
    if include_materials_cost:
        tile_price = next(
            (lay.tile.price_per_m2 for lay in layouts if lay.tile.price_per_m2), None
        )
        if tile_price:
            for line in est.materials:
                if line.kind != "tile":
                    continue
                # Платим за упаковки целиком — как в магазине.
                est.material_costs[line.name] = round(tile_paid_area_m2(line) * tile_price, 2)

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
    """Смета — документ ДО работ: сколько стоит работа и что купить.

    Итог — это работа мастера, и он единственный. Материалы идут ниже списком, без
    денег: заказчик покупает их сам, по своим магазинам и ценам, а любая цифра
    рядом читается как обещание мастера.
    """
    lines = [f"<b>Смета — {est.title}</b>", "", "<b>Работы</b>"]
    lines += _work_lines(est)
    lines += ["", f"<b>РАБОТА: {money(est.works_total)}</b>"]

    if est.materials:
        lines += ["", "<b>Материалы — купить</b>"]
        for m in est.materials:
            lines.append(f"• {m.name}: {_qty_with_packs(m)}")
        lines.append("\n<i>Материалы заказчик покупает сам, в стоимость работы они не входят.</i>")

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

    if est.receipts_total:
        # Закупки мастера идут одной строкой: расшифровка и фото чеков живут в
        # «Деньгах» объекта, а заказчику важна сумма к возврату.
        lines.append(f"\nМатериалы по чекам: <b>{money(est.receipts_total)}</b>")
        if est.materials_total:
            # Гасить одно другим нельзя: мы не знаем, за что чек. Молча выкинуть
            # цену плитки — потерять из документа реальные деньги мастера, поэтому
            # показываем оба источника и говорим прямо, что сверить их ему.
            lines.append(
                "<i>Плитка посчитана по твоей цене, закупки — по чекам. "
                "Если плитка в чеках уже есть, убери её из одного места.</i>"
            )

    lines += ["", f"<b>ИТОГО К ОПЛАТЕ: {money(est.grand_total)}</b>"]
    if est.note:
        lines += ["", f"<i>{est.note}</i>"]

    return "\n".join(lines)
