"""Комната целиком: обмер по кругу → поверхности под укладку.

Мастер не считает стену за стеной — он обмеряет ванную рулеткой по периметру и
кладёт все стены одной плиткой. Одна комната = одна закупка и одна смета.
"""

from tilebot.core.models import Surface, SurfaceKind

# Насколько противоположные стены могут разойтись, чтобы пол ещё считался
# прямоугольным. Больше — комната кривая, пол честнее померить отдельно.
FLOOR_TOLERANCE_M = 0.10


def floor_dims(walls: list[float]) -> tuple[float, float] | None:
    """Размеры пола по четырём стенам — если комната прямоугольная.

    None — по таким стенам пол не восстановить: комната кривая или стен не четыре.
    """
    if len(walls) != 4:
        return None
    a, b, c, d = walls
    if abs(a - c) > FLOOR_TOLERANCE_M or abs(b - d) > FLOOR_TOLERANCE_M:
        return None
    # Замеры почти никогда не сходятся до миллиметра — усредняем противоположные.
    return (a + c) / 2, (b + d) / 2


def room_surfaces(walls: list[float], height_m: float, *, with_floor: bool) -> list[Surface]:
    """Стены комнаты (и пол) — по одной поверхности на стену, высота общая."""
    surfaces = [
        Surface(
            name=f"Стена {i}",
            width_mm=length * 1000,
            height_mm=height_m * 1000,
            kind=SurfaceKind.WALL,
        )
        for i, length in enumerate(walls, start=1)
    ]

    dims = floor_dims(walls) if with_floor else None
    if dims:
        width, length = dims
        surfaces.append(
            Surface(
                name="Пол",
                width_mm=width * 1000,
                height_mm=length * 1000,
                kind=SurfaceKind.FLOOR,
            )
        )
    return surfaces
