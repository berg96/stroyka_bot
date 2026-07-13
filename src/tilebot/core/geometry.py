"""Площадь помещения по замерам рулеткой.

Ровно та задача, на которой проект встал год назад: площадь многоугольника по
одним лишь длинам сторон не считается — четырёхугольник «шарнирный», при тех же
сторонах его площадь меняется. Но плиточнику не нужна теория: он может померить
рулеткой ещё и диагональ. Сторона + диагональ жёстко фиксируют треугольник, а из
треугольников собирается любая комната.
"""

import math
from dataclasses import dataclass


class GeometryError(ValueError):
    """Замеры не сходятся — из таких сторон фигуру не собрать."""


@dataclass(frozen=True)
class AreaResult:
    area_m2: float
    perimeter_m: float
    method: str
    note: str = ""


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


def rectangle(width_m: float, length_m: float) -> AreaResult:
    if width_m <= 0 or length_m <= 0:
        raise GeometryError("Стороны должны быть больше нуля.")
    return AreaResult(
        area_m2=width_m * length_m,
        perimeter_m=2 * (width_m + length_m),
        method="прямоугольник",
    )


def triangle(a: float, b: float, c: float) -> AreaResult:
    return AreaResult(
        area_m2=_heron(a, b, c),
        perimeter_m=a + b + c,
        method="треугольник (Герон)",
    )


def quadrilateral(a: float, b: float, c: float, d: float, diagonal: float) -> AreaResult:
    """Четырёхугольник по четырём сторонам и диагонали.

    Стороны идут по кругу: a, b, c, d. Диагональ соединяет вершину между d и a с
    вершиной между b и c — то есть режет фигуру на треугольники (a, b, diag) и
    (c, d, diag).
    """
    t1 = _heron(a, b, diagonal)
    t2 = _heron(c, d, diagonal)
    return AreaResult(
        area_m2=t1 + t2,
        perimeter_m=a + b + c + d,
        method="четырёхугольник (2 треугольника по диагонали)",
        note=f"Треугольники {t1:.2f} + {t2:.2f} м²",
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
