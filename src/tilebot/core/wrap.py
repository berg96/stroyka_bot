"""Эконом-раскладка: непрерывная лента по периметру комнаты.

Обычная раскладка считает каждую стену отдельно: в углу кладётся целая плитка, а
в другой край уходит подрезка — и остаток каждого реза летит в мусор. На ванной
2×2 м плиткой 1200×600 это 20 огрызков и перерасход в треть закупки.

Мастер (Саня, голосовое 16.07): «от угла начал, целую положил, потом от целой
отрезал, допустим 798, и от неё, от угла прошло продолжение дальше — это
безотходный вариант». То есть стены разворачиваются в одну ленту длиной в
периметр: плитка, попавшая на угол, режется, её остаток становится первым куском
следующей стены. Швы по кругу сходятся, отхода почти нет.

Плата за это — симметрия: «где-то там смесители идут, где-то шов должен быть по
центру для максимальной эстетики». Поэтому режим включается кнопкой, а не по
умолчанию: «заказчики разные и не все будут хотеть такую раскладку».
"""

from tilebot.core.layout import (
    ANGLED,
    MIN_CUT_MM,
    NO_AXIS,
    Cell,
    Layout,
    apply_openings,
    build_layout,
)
from tilebot.core.models import DEFAULT_OFFSET, LayoutPattern, StartFrom, Surface, SurfaceKind, Tile
from tilebot.core.units import fmt_mm

EPS = 1e-6

# Толщина пропила: рез съедает материал, и остаток КОРОЧЕ, чем «плитка минус
# отрезанное». В обычной раскладке это никого не волнует — остаток летит в мусор.
# В ленте идут в дело обе половины, поэтому пропил надо вычитать, иначе бот обещает
# кусок, которого не существует.
#
# 2 мм — алмазный диск мокрореза/болгарки (1,6–2,2 мм) плюс шлифовка кромки. Ручной
# плиткорез раскалывает и почти не ест, распил крупноформата с подгонкой съедает
# больше. ⚠️ Цифру надо подтвердить у Сани: он режет, ему и знать. Артём (16.07):
# «при разрезе тоже сколько-то мм теряется, а может даже и см».
KERF_MM = 2.0


def supports_wrap(pattern: LayoutPattern) -> bool:
    """Лента бывает только у прямых раскладок.

    Под 45° плитка у стены и так уходит треугольником — «продолжить за угол»
    там нечего, режется весь периметр в любом случае. Плюс куски диагонали —
    многоугольники, разрезать их по углу прямоугольной рамкой нельзя.
    """
    return pattern not in ANGLED


def _slice_cells(
    cells: list[Cell], x0: float, x1: float, kerf_mm: float = KERF_MM
) -> list[Cell]:
    """Куски плиток, попавшие на участок ленты [x0, x1) — в координатах участка.

    Плитка, лежащая через границу, попадает сюда дважды: левой частью в одну
    стену, правой — в другую. Купленной она считается там, где начинается.

    Остаток короче на пропил: из плитки 1200 отрезали 798 — в руках не 402, а
    402 минус диск. Недостачу отдаём В УГОЛ (кусок сдвигаем от угла на пропил),
    а не в шов с соседней плиткой: в углу и так стык двух стен, шов и затирка,
    а расширенный шов посреди стены мастер увидит.
    """
    out: list[Cell] = []
    for cell in cells:
        left = max(cell.x, x0)
        right = min(cell.x + cell.w, x1)
        width = right - left
        if width <= EPS:
            continue

        crosses = cell.x < x0 - EPS  # плитка началась на прошлой стене
        x_local = left - x0
        if crosses:
            width -= kerf_mm
            x_local += kerf_mm

        # Кусок, который меньше минимальной подрезки, к стене не приклеить —
        # он крошится и вылетает. Такой огрызок не кладём: у следующей стены
        # раскладка начнётся новой плиткой, а этот кусок уйдёт в бой (запас).
        if crosses and width < MIN_CUT_MM:
            continue

        out.append(
            Cell(
                x=x_local,
                y=cell.y,
                w=width,
                h=cell.h,
                is_cut=cell.is_cut or width < cell.w - EPS,
                counts_as_tile=not crosses,
            )
        )
    return out


def wrap_wall_layouts(
    walls: list[Surface],
    tile: Tile,
    pattern: LayoutPattern = LayoutPattern.STRAIGHT,
    offset_ratio: float = DEFAULT_OFFSET,
    kerf_mm: float = KERF_MM,
) -> list[Layout]:
    """Разложить стены комнаты одной непрерывной лентой и нарезать её по углам.

    Возвращает по одному Layout на стену — как и обычный расчёт, чтобы схемы и
    смета строились дальше без изменений. Плитка, разрезанная на углу, посчитана
    ровно один раз: на той стене, где она начинается.

    Стены идут в порядке обмера — это и есть порядок обхода комнаты. Раскладка
    всегда от угла: у ленты «центра» нет, а начало ряда — это первый угол.

    Проёмы остаются за каждой стеной: лента их не знает, поэтому дверь вырезается
    уже после нарезки, той же логикой, что и в обычной раскладке.
    """
    if not supports_wrap(pattern):
        raise ValueError(f"эконом-лента не считается для раскладки {pattern}")

    walls = [w for w in walls if w.width_mm > EPS]
    if not walls:
        return []

    height_mm = walls[0].height_mm
    band = Surface(
        name="Периметр",
        width_mm=sum(w.width_mm for w in walls),
        height_mm=height_mm,
        kind=SurfaceKind.WALL,
    )
    band_layout = build_layout(band, tile, pattern, StartFrom.EDGE, offset_ratio)

    layouts: list[Layout] = []
    x0 = 0.0
    for wall in walls:
        x1 = x0 + wall.width_mm
        cells = apply_openings(_slice_cells(band_layout.cells, x0, x1, kerf_mm), wall)
        layouts.append(
            Layout(
                surface=wall,
                tile=tile,
                pattern=pattern,
                start_from=StartFrom.EDGE,
                # Ось X у ленты одна на весь периметр: её «подрезка в конце» — это
                # замыкающий кусок всей комнаты, а не этой стены. Подписать им край
                # стены значит соврать (на схеме стояло 791 там, где кусок 396).
                # Ширина каждого куска и так написана на самой плитке.
                x=NO_AXIS,
                y=band_layout.y,
                cells=cells,
                advice=_advice(cells, len(walls), kerf_mm),
            )
        )
        x0 = x1

    return layouts


def _advice(cells: list[Cell], walls_count: int, kerf_mm: float = KERF_MM) -> list[str]:
    """Что мастеру важно знать про ленту — на его же языке."""
    from_corner = sum(1 for c in cells if not c.counts_as_tile)
    out: list[str] = []
    if from_corner:
        out.append(
            f"Эконом: {from_corner} шт — остатки плиток с прошлой стены, режешь их "
            "по углу и кладёшь дальше. Отдельно покупать не надо, они уже в закупке."
        )
        # Рез съедает материал, поэтому остаток не дотягивает до угла. Ставим его
        # по шву от соседней плитки, а щель прячем в угол — но мастер увидит её на
        # схеме, поэтому говорим сразу и с цифрой.
        if kerf_mm > 0:
            out.append(
                f"Считаю пропил {fmt_mm(kerf_mm)} мм: остаток на столько короче, "
                f"и в углу остаётся щель ~{fmt_mm(kerf_mm)} мм — она уходит под "
                "затирку. Режешь тоньше или толще — скажи, пересчитаю."
            )
    out.append(
        "Кладка идёт по кругу непрерывно: закончил стену — остаток плитки заворачивает "
        f"за угол на следующую. Стен {walls_count}, порядок держи тот же, что при обмере."
    )
    out.append(
        "Симметрии по стенам тут нет — шов не встанет по центру. Если на стене "
        "смеситель или видное место, лучше обычная раскладка."
    )
    return out


def wrap_savings(
    walls: list[Surface],
    tile: Tile,
    pattern: LayoutPattern = LayoutPattern.STRAIGHT,
    start_from: StartFrom = StartFrom.EDGE,
) -> tuple[int, int]:
    """(плиток обычной раскладкой, плиток эконом-лентой) — чтобы показать разницу.

    Мастеру важна не идея, а сколько плиток он не купит: «огромный расход» из его
    голосового — это конкретные упаковки денег.
    """
    per_wall = sum(build_layout(w, tile, pattern, start_from).tiles_grid for w in walls)
    banded = sum(lay.tiles_grid for lay in wrap_wall_layouts(walls, tile, pattern))
    return per_wall, banded
