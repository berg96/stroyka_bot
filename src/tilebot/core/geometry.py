"""Площадь помещения по замерам рулеткой.

Ровно та задача, на которой проект встал год назад: площадь многоугольника по
одним лишь длинам сторон не считается — четырёхугольник «шарнирный», при тех же
сторонах его площадь меняется. Но плиточнику не нужна теория: он может померить
рулеткой ещё и диагональ. Сторона + диагональ жёстко фиксируют треугольник, а из
треугольников собирается любая комната.
"""

import math
from dataclasses import dataclass, field


class GeometryError(ValueError):
    """Замеры не сходятся — из таких сторон фигуру не собрать."""


Point = tuple[float, float]


@dataclass(frozen=True)
class AreaResult:
    area_m2: float
    perimeter_m: float
    method: str
    note: str = ""
    # Вершины фигуры в метрах — чтобы показать мастеру, что именно посчитали.
    # Пусто, если фигуру по замерам не восстановить (составная комната).
    vertices: list[Point] = field(default_factory=list)


def shoelace_area(points: list[Point]) -> float:
    """Площадь многоугольника по координатам вершин."""
    n = len(points)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def _third_vertex(origin: Point, prev: Point, from_origin: float, from_prev: float) -> Point:
    """Вершина на заданных расстояниях от двух известных точек.

    Пересечение двух окружностей. Из двух решений берём то, что лежит слева от
    луча origin→prev: так обход идёт против часовой и фигура не выворачивается.
    """
    ox, oy = origin
    px, py = prev
    dx, dy = px - ox, py - oy
    d = math.hypot(dx, dy)
    if d <= 1e-9:
        raise GeometryError("Замеры не сходятся — точки совпали.")

    # Классическое пересечение окружностей радиусов from_origin и from_prev.
    a = (from_origin**2 - from_prev**2 + d**2) / (2 * d)
    h_sq = from_origin**2 - a**2
    if h_sq < -1e-6:
        raise GeometryError(
            "Замеры не сходятся: с такими сторонами и диагоналями фигура не "
            "собирается. Перемерь диагонали."
        )
    h = math.sqrt(max(0.0, h_sq))

    mx, my = ox + a * dx / d, oy + a * dy / d
    # Нормаль к origin→prev; знак выбираем так, чтобы вершина ушла влево.
    return (mx - h * dy / d, my + h * dx / d)


def _heron(a: float, b: float, c: float) -> float:
    """Площадь треугольника по трём сторонам. Стороны в метрах."""
    if min(a, b, c) <= 0:
        raise GeometryError("Сторона не может быть нулевой или отрицательной.")
    # Неравенство треугольника: иначе замер сделан с ошибкой.
    sides = sorted((a, b, c))
    if sides[0] + sides[1] <= sides[2] + 1e-9:
        raise GeometryError(
            f"Из сторон {a:g}, {b:g}, {c:g} треугольник не собирается — "
            f"самая длинная ({sides[2]:g} м) не короче суммы двух других. "
            "Перемерь: скорее всего ошибка в замере."
        )
    s = (a + b + c) / 2
    return math.sqrt(max(0.0, s * (s - a) * (s - b) * (s - c)))


def fan_vertices(sides: list[float], diagonals: list[float]) -> list[Point]:
    """Координаты вершин по сторонам и диагоналям из первой вершины.

    Первую сторону кладём на ось X, дальше каждую следующую вершину находим по
    двум расстояниям: до первой вершины (диагональ) и до предыдущей (сторона).
    """
    n = len(sides)
    points: list[Point] = [(0.0, 0.0), (sides[0], 0.0)]
    chords = [*diagonals, sides[n - 1]]  # до последней вершины «диагональ» = замыкающая сторона

    for i in range(1, n - 1):
        points.append(_third_vertex(points[0], points[i], chords[i - 1], sides[i]))

    return points


def rectangle(width_m: float, length_m: float) -> AreaResult:
    if width_m <= 0 or length_m <= 0:
        raise GeometryError("Стороны должны быть больше нуля.")
    return AreaResult(
        area_m2=width_m * length_m,
        perimeter_m=2 * (width_m + length_m),
        method="прямоугольник",
        vertices=[(0.0, 0.0), (width_m, 0.0), (width_m, length_m), (0.0, length_m)],
    )


def triangle(a: float, b: float, c: float) -> AreaResult:
    area = _heron(a, b, c)
    return AreaResult(
        area_m2=area,
        perimeter_m=a + b + c,
        method="треугольник (Герон)",
        vertices=fan_vertices([a, b, c], []),
    )


# Насколько противоположные стены могут разойтись, чтобы углы всё ещё считались
# прямыми. Стены никогда не идеальны, но расхождение больше этого — уже косой угол,
# и площадь надо брать через диагональ.
SQUARE_TOLERANCE_M = 0.10


def right_angled_quad(a: float, b: float, c: float, d: float) -> AreaResult:
    """Четырёхугольник, у которого мастер подтвердил прямые углы.

    Если все четыре угла прямые — это прямоугольник, и диагональ мерить незачем:
    она пересчитывается из сторон. Противоположные стены при этом обязаны совпасть,
    так что расхождение замеров — сигнал, что углы на самом деле косые.
    """
    for x in (a, b, c, d):
        if x <= 0:
            raise GeometryError("Сторона не может быть нулевой или отрицательной.")

    for first, second, what in ((a, c, "первая и третья"), (b, d, "вторая и четвёртая")):
        if abs(first - second) > SQUARE_TOLERANCE_M:
            raise GeometryError(
                f"Углы не прямые: {what} стены отличаются на "
                f"{abs(first - second):.2f} м ({first:g} и {second:g}). "
                "При прямых углах противоположные стены равны. "
                "Либо перемерь, либо посчитай через диагональ — кнопка «Есть косой угол»."
            )

    # Замеры почти никогда не сходятся до миллиметра — усредняем противоположные.
    width = (a + c) / 2
    length = (b + d) / 2
    note = ""
    if abs(a - c) > 1e-9 or abs(b - d) > 1e-9:
        note = (
            f"Стены разошлись на {max(abs(a - c), abs(b - d)) * 100:.0f} см — "
            f"взял среднее: {width:.2f} × {length:.2f} м."
        )

    return AreaResult(
        area_m2=width * length,
        perimeter_m=a + b + c + d,
        method="прямоугольник (углы прямые, диагональ не нужна)",
        note=note,
        vertices=[(0.0, 0.0), (width, 0.0), (width, length), (0.0, length)],
    )


def _check_diagonal(a: float, b: float, c: float, d: float, diagonal: float) -> None:
    """Диагональ должна собирать оба треугольника — иначе замер битый.

    Проверяем до Герона, чтобы вместо «фигура не собирается» сказать мастеру,
    в каких пределах диагональ вообще может быть.
    """
    low = max(abs(a - b), abs(c - d))
    high = min(a + b, c + d)
    if low < diagonal < high:
        return

    hint = ""
    if abs(a - c) <= SQUARE_TOLERANCE_M and abs(b - d) <= SQUARE_TOLERANCE_M:
        # Стороны как у прямоугольника — подскажем, какой была бы диагональ.
        square_diag = math.hypot((a + c) / 2, (b + d) / 2)
        hint = (
            f"\n\nСудя по сторонам, у тебя прямоугольник — тогда диагональ "
            f"должна быть ≈ {square_diag:.2f} м, а не {diagonal:g}. "
            "Если углы прямые, диагональ вообще не нужна — жми «Углы прямые»."
        )

    raise GeometryError(
        f"Диагональ {diagonal:g} м не сходится со сторонами: она должна быть "
        f"больше {low:.2f} м и меньше {high:.2f} м, иначе фигура не собирается "
        f"(стены складываются в линию). Перемерь из угла в угол.{hint}"
    )


def quadrilateral(a: float, b: float, c: float, d: float, diagonal: float) -> AreaResult:
    """Четырёхугольник по четырём сторонам и диагонали.

    Стороны идут по кругу: a, b, c, d. Диагональ соединяет вершину между d и a с
    вершиной между b и c — то есть режет фигуру на треугольники (a, b, diag) и
    (c, d, diag).
    """
    _check_diagonal(a, b, c, d, diagonal)
    t1 = _heron(a, b, diagonal)
    t2 = _heron(c, d, diagonal)
    return AreaResult(
        area_m2=t1 + t2,
        perimeter_m=a + b + c + d,
        method="четырёхугольник (2 треугольника по диагонали)",
        note=f"Треугольники {t1:.2f} + {t2:.2f} м²",
        vertices=fan_vertices([a, b, c, d], [diagonal]),
    )


def polygon_fan(sides: list[float], diagonals: list[float]) -> AreaResult:
    """Произвольный многоугольник: стороны по кругу + диагонали из первой вершины.

    Мастер обходит комнату по периметру, потом меряет диагонали из одного угла в
    каждый несмежный. Для n сторон нужно n-3 диагонали — фигура режется веером на
    n-2 треугольника.
    """
    n = len(sides)
    if n < 3:
        raise GeometryError("Нужно минимум три стороны.")
    if n == 3:
        return triangle(*sides)

    need = n - 3
    if len(diagonals) != need:
        raise GeometryError(
            f"Для {n} сторон нужно {need} диагонал"
            f"{'ь' if need == 1 else 'и'} из одного угла, а дано {len(diagonals)}."
        )

    # Веер: треугольники (s0, s1, d0), (d0, s2, d1), ..., (d[-1], s[n-2], s[n-1]).
    chords = [sides[0], *diagonals, sides[n - 1]]
    total = 0.0
    parts = []
    for i in range(n - 2):
        a = chords[i]
        b = sides[i + 1]
        c = chords[i + 1]
        area = _heron(a, b, c)
        parts.append(area)
        total += area

    return AreaResult(
        area_m2=total,
        perimeter_m=sum(sides),
        method=f"многоугольник {n} сторон (веер из {n - 2} треугольников)",
        note=" + ".join(f"{p:.2f}" for p in parts) + " м²",
        vertices=fan_vertices(sides, diagonals),
    )


@dataclass(frozen=True)
class Part:
    """Кусок комнаты: прямоугольный участок, который прибавляют или вычитают.

    Так собирается Г-образная кухня (два прямоугольника) или ванная с коробом
    (прямоугольник минус короб) — без всякой тригонометрии, только рулетка.
    """

    name: str
    width_m: float
    length_m: float
    subtract: bool = False

    @property
    def area_m2(self) -> float:
        a = self.width_m * self.length_m
        return -a if self.subtract else a


def composite(parts: list[Part]) -> AreaResult:
    """Площадь комнаты, собранной из прямоугольных участков и вычетов."""
    if not parts:
        raise GeometryError("Нужен хотя бы один участок.")
    total = sum(p.area_m2 for p in parts)
    if total <= 0:
        raise GeometryError("Вычеты съели всю площадь — проверь замеры.")

    added = [p for p in parts if not p.subtract]
    cut_out = len(parts) - len(added)
    note = " ".join(f"{'−' if p.subtract else '+'}{abs(p.area_m2):.2f}" for p in parts)
    method = f"составная комната: участков {len(added)}, вычетов {cut_out}"
    return AreaResult(
        area_m2=total,
        # Периметр составной фигуры по кускам не восстановить — честно не считаем,
        # для плинтуса пусть мастер меряет отдельно.
        perimeter_m=0.0,
        method=method,
        note=f"{note} = {total:.2f} м²",
    )
