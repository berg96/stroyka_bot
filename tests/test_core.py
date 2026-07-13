import math

import pytest

from tilebot.core.geometry import (
    GeometryError,
    Part,
    composite,
    polygon_fan,
    quadrilateral,
    rectangle,
    triangle,
)
from tilebot.core.layout import best_orientation, build_layout
from tilebot.core.materials import calc_materials, grout_kg_per_m2, trowel_for
from tilebot.core.models import LayoutPattern, Opening, StartFrom, Surface, SurfaceKind, Tile


class TestGeometry:
    def test_rectangle(self):
        assert rectangle(3, 4).area_m2 == pytest.approx(12)

    def test_triangle_345(self):
        assert triangle(3, 4, 5).area_m2 == pytest.approx(6)

    def test_impossible_triangle_is_a_bad_measurement(self):
        with pytest.raises(GeometryError, match="не собирается"):
            triangle(1, 2, 10)

    def test_quadrilateral_square_via_diagonal(self):
        # Квадрат 3×3, диагональ 3√2 → площадь 9.
        r = quadrilateral(3, 3, 3, 3, 3 * math.sqrt(2))
        assert r.area_m2 == pytest.approx(9, rel=1e-6)

    def test_quadrilateral_rectangle_via_diagonal(self):
        # Прямоугольник 3×4, диагональ 5 → 12 м².
        assert quadrilateral(3, 4, 3, 4, 5).area_m2 == pytest.approx(12)

    def test_polygon_fan_needs_right_number_of_diagonals(self):
        with pytest.raises(GeometryError, match="диагонал"):
            polygon_fan([3, 4, 3, 4, 5], [])

    def test_polygon_fan_pentagon(self):
        # Комната-«домик» с вершинами (0,0) (4,0) (4,3) (2,5) (0,3).
        # Площадь по формуле шнурков = 16 м² — веер должен дать столько же.
        s = [4, 3, math.hypot(2, 2), math.hypot(2, 2), 3]  # стороны по кругу
        d = [5, math.hypot(2, 5)]  # диагонали из вершины (0,0) в (4,3) и (2,5)
        r = polygon_fan(s, d)
        assert r.area_m2 == pytest.approx(16, rel=1e-6)
        assert r.perimeter_m == pytest.approx(sum(s))

    def test_composite_l_shaped_room(self):
        # Г-образная кухня: 4×3 плюс 2×2, минус короб 0.5×0.5.
        r = composite(
            [
                Part("основная", 4, 3),
                Part("выступ", 2, 2),
                Part("короб", 0.5, 0.5, subtract=True),
            ]
        )
        assert r.area_m2 == pytest.approx(12 + 4 - 0.25)

    def test_composite_all_subtracted_is_error(self):
        with pytest.raises(GeometryError):
            composite([Part("а", 1, 1), Part("б", 2, 2, subtract=True)])


class TestLayout:
    def test_exact_fit_no_cuts(self):
        # Стена 1200×600 под плитку 600×300 со швом 0: ровно 2×2, подрезки нет.
        wall = Surface("стена", 1200, 600)
        tile = Tile(600, 300, joint_mm=0)
        lay = build_layout(wall, tile)
        assert (lay.cols, lay.rows) == (2, 2)
        assert lay.x.cuts == [] and lay.y.cuts == []
        assert lay.tiles_grid == 4
        assert "ровная" in lay.advice[0]

    def test_cut_lands_on_the_far_edge(self):
        # 1000 мм под плитку 300 + шов 0 → 3 целых, остаток 100 в подрезку.
        wall = Surface("стена", 1000, 300)
        tile = Tile(300, 300, joint_mm=0)
        lay = build_layout(wall, tile, start_from=StartFrom.EDGE)
        assert lay.x.full == 3
        assert lay.x.cut_end_mm == pytest.approx(100)
        assert lay.x.total == 4

    def test_joints_are_counted(self):
        # 3 плитки по 300 и 2 шва по 5 = 910 мм. Ровно влезает, подрезки нет.
        wall = Surface("стена", 910, 300)
        tile = Tile(300, 300, joint_mm=5)
        lay = build_layout(wall, tile)
        assert lay.x.full == 3
        assert lay.x.cuts == []

    def test_thin_sliver_triggers_center_advice(self):
        # Остаток 20 мм — тонкая полоска, бот должен посоветовать центрировать.
        wall = Surface("стена", 920, 300)
        tile = Tile(300, 300, joint_mm=0)
        lay = build_layout(wall, tile, start_from=StartFrom.EDGE)
        assert lay.x.min_cut_mm == pytest.approx(20)
        assert any("от центра" in a for a in lay.advice)

    def test_center_start_splits_the_cut_in_two(self):
        wall = Surface("стена", 920, 300)
        tile = Tile(300, 300, joint_mm=0)
        lay = build_layout(wall, tile, start_from=StartFrom.CENTER)
        # Тонкие 20 мм превращаются в два края по 160 мм — резать не страшно.
        assert lay.x.cut_start_mm == pytest.approx(lay.x.cut_end_mm)
        assert lay.x.cut_start_mm == pytest.approx(160)
        assert lay.x.min_cut_mm > 100

    def test_tiles_under_a_known_opening_are_not_counted(self):
        # Стена 3000×2500 и дверь 1000×2000 в углу: плитки, целиком попавшие в
        # проём, класть не будут — в закупку они попадать не должны.
        tile = Tile(500, 500, joint_mm=0)
        plain = Surface("без двери", 3000, 2500)
        with_door = Surface(
            "с дверью",
            3000,
            2500,
            openings=[Opening("дверь", 1000, 2000, x_mm=0, y_mm=0)],
        )
        # Дверь ровно 2×4 плитки по сетке.
        assert build_layout(plain, tile).tiles_grid == 30
        assert build_layout(with_door, tile).tiles_grid == 30 - 8

    def test_opening_without_coordinates_only_affects_area(self):
        # Не знаем, где дверь — плитку по сетке не выкидываем, но площадь режем.
        tile = Tile(500, 500, joint_mm=0)
        surface = Surface("стена", 3000, 2500, openings=[Opening("дверь", 1000, 2000)])
        assert build_layout(surface, tile).tiles_grid == 30
        assert surface.net_area_m2 == pytest.approx(7.5 - 2.0)

    def test_best_orientation_prefers_wider_cut(self):
        wall = Surface("стена", 920, 600)
        tile = Tile(300, 600, joint_mm=0)
        best, alt = best_orientation(wall, tile)
        worst_best = min(best.x.min_cut_mm, best.y.min_cut_mm)
        worst_alt = min(alt.x.min_cut_mm, alt.y.min_cut_mm)
        assert worst_best >= worst_alt


class TestMaterials:
    def test_openings_reduce_the_area(self):
        wall = Surface(
            "стена с дверью",
            3000,
            2500,
            openings=[Opening("дверь", 800, 2100)],
        )
        assert wall.gross_area_m2 == pytest.approx(7.5)
        assert wall.net_area_m2 == pytest.approx(7.5 - 1.68)

    def test_grout_formula_matches_reference(self):
        # Эталон из справочника: плитка 330×330×10, шов 2 мм, плотность 1.6
        # → 0.194 кг/м².
        tile = Tile(330, 330, thickness_mm=10, joint_mm=2)
        assert grout_kg_per_m2(tile) == pytest.approx(0.194, abs=0.001)

    def test_trowel_grows_with_tile_size(self):
        assert trowel_for(Tile(100, 100))[0] < trowel_for(Tile(600, 600))[0]

    def test_materials_include_everything_needed(self):
        wall = Surface("стена", 3000, 2500, kind=SurfaceKind.WALL)
        tile = Tile(600, 300, thickness_mm=9, joint_mm=2, per_pack=8)
        lay = build_layout(wall, tile)
        m = calc_materials(lay, waterproofing=True)

        names = [line.name for line in m.lines]
        assert any("Плитка" in n for n in names)
        assert "Плиточный клей" in names
        assert any("Затирка" in n for n in names)
        assert "Грунтовка" in names
        assert "СВП, зажимы" in names
        assert "Гидроизоляция обмазочная" in names

        # Запас 10% сверх сетки, упаковки округлены вверх.
        assert m.tiles_count >= lay.tiles_grid
        assert m.packs == math.ceil(m.tiles_count / 8)

    def test_diagonal_pattern_costs_more_tile(self):
        wall = Surface("стена", 3000, 2500)
        tile = Tile(300, 300)
        straight = calc_materials(build_layout(wall, tile, LayoutPattern.STRAIGHT))
        diagonal = calc_materials(build_layout(wall, tile, LayoutPattern.DIAGONAL))
        assert diagonal.tiles_count > straight.tiles_count
