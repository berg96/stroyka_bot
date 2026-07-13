"""Модель предметной области: поверхность, плитка, раскладка.

Здесь только данные и никакой логики Telegram — ядро тестируется отдельно.
Все линейные размеры внутри ядра — в миллиметрах, площади — в м².
"""

from dataclasses import dataclass, field
from enum import StrEnum


class SurfaceKind(StrEnum):
    WALL = "wall"
    FLOOR = "floor"


class LayoutPattern(StrEnum):
    """Схема раскладки. Влияет на подрезку и запас материала."""

    STRAIGHT = "straight"  # шов в шов
    BRICK = "brick"  # вразбежку (кирпичная), смещение задаётся offset_ratio
    DIAGONAL = "diagonal"  # по диагонали 45°
    HERRINGBONE = "herringbone"  # ёлочка


class StartFrom(StrEnum):
    """Откуда начинается раскладка по горизонтали."""

    EDGE = "edge"  # от угла: целая плитка слева, вся подрезка справа
    CENTER = "center"  # от центра: подрезка симметрична по краям


# Запас материала сверх нетто-площади, доля. Диагональ и ёлочка дают больше боя
# на подрезке — цифры из практики (прямая 10%, диагональ 15%).
WASTE_BY_PATTERN: dict[LayoutPattern, float] = {
    LayoutPattern.STRAIGHT: 0.10,
    LayoutPattern.BRICK: 0.10,
    LayoutPattern.DIAGONAL: 0.15,
    LayoutPattern.HERRINGBONE: 0.15,
}


@dataclass(frozen=True)
class Tile:
    """Плитка. width/height — как она лежит на поверхности (уже с учётом поворота)."""

    width_mm: float
    height_mm: float
    thickness_mm: float = 9.0
    joint_mm: float = 2.0  # ширина шва
    per_pack: int | None = None  # штук в упаковке
    price_per_m2: float | None = None  # ₽ за м², если мастер считает смету

    @property
    def area_m2(self) -> float:
        return (self.width_mm / 1000) * (self.height_mm / 1000)

    @property
    def step_x_mm(self) -> float:
        """Шаг сетки по горизонтали — плитка плюс шов."""
        return self.width_mm + self.joint_mm

    @property
    def step_y_mm(self) -> float:
        return self.height_mm + self.joint_mm

    def rotated(self) -> "Tile":
        """Та же плитка, положенная на бок (60×30 → 30×60)."""
        return Tile(
            width_mm=self.height_mm,
            height_mm=self.width_mm,
            thickness_mm=self.thickness_mm,
            joint_mm=self.joint_mm,
            per_pack=self.per_pack,
            price_per_m2=self.price_per_m2,
        )


@dataclass(frozen=True)
class Opening:
    """Вычет из поверхности: дверь, окно, короб, ниша под ванну."""

    name: str
    width_mm: float
    height_mm: float
    # Левый нижний угол проёма от левого нижнего угла поверхности. None — не
    # знаем где именно (в площадь вычтем, на схеме не рисуем).
    x_mm: float | None = None
    y_mm: float | None = None

    @property
    def area_m2(self) -> float:
        return (self.width_mm / 1000) * (self.height_mm / 1000)


@dataclass(frozen=True)
class Surface:
    """Одна плоскость под укладку: стена или пол."""

    name: str
    width_mm: float
    height_mm: float  # для пола — глубина комнаты
    kind: SurfaceKind = SurfaceKind.WALL
    openings: list[Opening] = field(default_factory=list)

    @property
    def gross_area_m2(self) -> float:
        return (self.width_mm / 1000) * (self.height_mm / 1000)

    @property
    def openings_area_m2(self) -> float:
        return sum(o.area_m2 for o in self.openings)

    @property
    def net_area_m2(self) -> float:
        """Площадь под плитку — за вычетом проёмов, но не меньше нуля."""
        return max(0.0, self.gross_area_m2 - self.openings_area_m2)
