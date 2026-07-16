import io
import math

import pytest
from PIL import Image

from tilebot.core.angled import angled_pieces, polygon_area
from tilebot.core.estimate import PriceList, rough_material_cost, tile_paid_area_m2
from tilebot.core.geometry import (
    GeometryError,
    Part,
    composite,
    polygon_fan,
    quadrilateral,
    rectangle,
    right_angled_quad,
    shoelace_area,
    triangle,
)
from tilebot.core.layout import best_orientation, build_layout, common_orientation
from tilebot.core.materials import (
    calc_materials,
    grout_kg_per_m2,
    merge_materials,
    tile_name,
    trowel_for,
)
from tilebot.core.models import LayoutPattern, Opening, StartFrom, Surface, SurfaceKind, Tile
from tilebot.core.room import floor_dims, room_surfaces
from tilebot.core.units import fmt_mm
from tilebot.render.scheme import _texture, grout_rgb, render_layout


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

    def test_right_angled_quad_needs_no_diagonal(self):
        """Ванная 2×1.8 с прямыми углами: диагональ мерить незачем."""
        r = right_angled_quad(2, 1.8, 2, 1.8)
        assert r.area_m2 == pytest.approx(3.6)
        assert "диагональ не нужна" in r.method

    def test_right_angled_quad_averages_imperfect_walls(self):
        """Стены никогда не идеальны — небольшое расхождение усредняем и говорим об этом."""
        r = right_angled_quad(2.03, 1.8, 1.99, 1.82)
        assert r.area_m2 == pytest.approx(2.01 * 1.81)
        assert "среднее" in r.note

    def test_right_angled_quad_rejects_skewed_walls(self):
        """Если противоположные стены разные — углы не прямые, нужна диагональ."""
        with pytest.raises(GeometryError, match="не прямые"):
            right_angled_quad(4, 2, 2, 2)

    def test_degenerate_diagonal_suggests_the_right_one(self):
        """Сашин ввод: квадрат 2×2 и диагональ 4 — фигура вырождается в линию.

        Вместо «перемерь» подсказываем, какой диагональ должна быть на самом деле.
        """
        with pytest.raises(GeometryError) as e:
            quadrilateral(2, 2, 2, 2, 4)
        assert "2.83" in str(e.value)
        assert "Углы прямые" in str(e.value)

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

    def test_vertices_match_the_computed_area(self):
        # Схему рисуем по восстановленным вершинам. Если они врут, мастер увидит не
        # ту фигуру — поэтому площадь по вершинам обязана сойтись с расчётной.
        cases = [
            rectangle(4, 3),
            triangle(3, 4, 5),
            quadrilateral(4, 3, 4, 3, 5),
            quadrilateral(3, 3, 3, 3, 3 * math.sqrt(2)),
            polygon_fan([4, 3, math.hypot(2, 2), math.hypot(2, 2), 3], [5, math.hypot(2, 5)]),
        ]
        for result in cases:
            assert len(result.vertices) >= 3
            assert shoelace_area(result.vertices) == pytest.approx(result.area_m2, rel=1e-6)

    def test_rectangle_by_diagonal_is_reconstructed_square(self):
        # Прямоугольник 3×4 по диагонали 5 — вершины должны встать под прямым углом.
        r = quadrilateral(3, 4, 3, 4, 5)
        assert r.vertices[0] == pytest.approx((0, 0))
        assert r.vertices[2] == pytest.approx((3, 4))

    def test_impossible_diagonal_is_reported(self):
        # Диагональ длиннее суммы сторон — фигура не собирается.
        with pytest.raises(GeometryError):
            quadrilateral(3, 4, 3, 4, 20)

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

        # Запас сверх сетки, упаковки округлены вверх.
        assert m.tiles_count >= lay.tiles_grid
        assert m.packs == math.ceil(m.tiles_count / 8)

    def test_straight_waste_is_seven_percent(self):
        """Саша берёт 7%, а не магазинные 10% — на прямой раскладке лишнего не кладём."""
        lay = build_layout(Surface("стена", 3000, 2500), Tile(300, 300), LayoutPattern.STRAIGHT)
        m = calc_materials(lay)
        assert m.tiles_count == math.ceil(lay.tiles_grid * 1.07)

    def test_waste_can_be_overridden(self):
        lay = build_layout(Surface("стена", 3000, 2500), Tile(300, 300), LayoutPattern.STRAIGHT)
        assert calc_materials(lay, waste=0.15).tiles_count == math.ceil(lay.tiles_grid * 1.15)
        assert calc_materials(lay, waste=0.0).tiles_count == lay.tiles_grid

    def test_diagonal_pattern_costs_more_tile(self):
        wall = Surface("стена", 3000, 2500)
        tile = Tile(300, 300)
        straight = calc_materials(build_layout(wall, tile, LayoutPattern.STRAIGHT))
        diagonal = calc_materials(build_layout(wall, tile, LayoutPattern.DIAGONAL))
        assert diagonal.tiles_count > straight.tiles_count


class TestUnits:
    def test_joint_keeps_tenths(self):
        """Шов 1,4 показывался как «1 мм» — Саша решил, что бот проигнорировал ввод."""
        assert fmt_mm(1.4) == "1,4"
        assert fmt_mm(1.5) == "1,5"

    def test_whole_millimetres_stay_whole(self):
        assert fmt_mm(2.0) == "2"
        assert fmt_mm(10) == "10"

    def test_grout_line_shows_the_real_joint(self):
        lay = build_layout(Surface("стена", 2000, 2500), Tile(600, 300, joint_mm=1.4))
        names = [line.name for line in calc_materials(lay).lines]
        assert "Затирка цементная (шов 1,4 мм)" in names


class TestRoom:
    def test_walls_become_surfaces_of_one_height(self):
        """Ванная целиком: стены по кругу + высота — одна плитка, одна закупка."""
        surfaces = room_surfaces([2, 1.8, 2, 1.8], 2.7, with_floor=False)
        assert [s.name for s in surfaces] == ["Стена 1", "Стена 2", "Стена 3", "Стена 4"]
        assert all(s.height_mm == 2700 for s in surfaces)
        assert surfaces[0].width_mm == 2000
        assert sum(s.gross_area_m2 for s in surfaces) == pytest.approx(2 * (2 + 1.8) * 2.7)

    def test_floor_is_taken_from_the_walls(self):
        surfaces = room_surfaces([2, 1.8, 2, 1.8], 2.7, with_floor=True)
        floor = surfaces[-1]
        assert floor.kind is SurfaceKind.FLOOR
        assert floor.gross_area_m2 == pytest.approx(3.6)

    def test_crooked_room_gets_no_floor(self):
        """Пол по кривым стенам не восстановить — врать площадью не будем."""
        assert floor_dims([2, 1.8, 2.5, 1.8]) is None
        assert len(room_surfaces([2, 1.8, 2.5, 1.8], 2.7, with_floor=True)) == 4


class TestPurchaseList:
    """Закупка на комнату: то, с чем мастер поедет в магазин."""

    def _room(self, tile):
        # Ванная 2×1.8×2.7 — стены кладутся одной ориентацией.
        walls = room_surfaces([2, 1.8, 2, 1.8], 2.7, with_floor=False)
        fixed = common_orientation(walls, tile, LayoutPattern.STRAIGHT)
        return [build_layout(w, fixed, LayoutPattern.STRAIGHT) for w in walls]

    def test_rotated_tile_is_one_position_not_two(self):
        """600×300 и 300×600 — одна плитка в магазине, а не две позиции в списке."""
        assert tile_name(Tile(300, 600)) == tile_name(Tile(600, 300)) == "Плитка 600×300"

        mats = [calc_materials(lay) for lay in self._room(Tile(600, 300))]
        tiles = [line for line in merge_materials(mats) if line.name.startswith("Плитка")]
        assert len(tiles) == 1

    def test_merged_packs_count_the_whole_room(self):
        """Упаковки считаем от всей комнаты — иначе «185 шт, ≈6 уп.»."""
        mats = [calc_materials(lay) for lay in self._room(Tile(600, 300, per_pack=8))]
        line = next(x for x in merge_materials(mats) if x.name.startswith("Плитка"))
        assert line.qty == sum(m.tiles_count for m in mats)
        assert f"≈{math.ceil(line.qty / 8)} уп." in line.note

    def test_merged_tile_area_is_summed(self):
        mats = [calc_materials(lay) for lay in self._room(Tile(600, 300, per_pack=8))]
        line = next(x for x in merge_materials(mats) if x.name.startswith("Плитка"))
        total = sum(m.tile_area_with_waste_m2 for m in mats)
        assert f"{total:.1f} м²" in line.note

    def test_walls_share_one_orientation(self):
        """Плитка, повёрнутая на второй стене иначе, — это брак работы."""
        layouts = self._room(Tile(600, 300))
        sizes = {(lay.tile.width_mm, lay.tile.height_mm) for lay in layouts}
        assert len(sizes) == 1


class TestScheme:
    """Схема с фото плитки — «как будет выглядеть», а не только «сколько штук»."""

    def _wall(self, joint=1.4):
        return build_layout(Surface("Стена 1", 2000, 2700), Tile(600, 300, joint_mm=joint))

    def test_photo_changes_the_scheme(self):
        photo = Image.new("RGB", (600, 300), (58, 62, 68))
        plain = render_layout(self._wall())
        with_photo = render_layout(self._wall(), tile_photo=photo, grout="white")
        assert plain != with_photo

    def test_grout_colour_changes_the_scheme(self):
        """Иначе выбор цвета затирки — кнопка, которая ничего не делает."""
        photo = Image.new("RGB", (600, 300), (58, 62, 68))
        white = render_layout(self._wall(), tile_photo=photo, grout="white")
        black = render_layout(self._wall(), tile_photo=photo, grout="black")
        assert white != black

    def test_grout_is_actually_visible_on_a_thin_joint(self):
        """Шов 1,4 мм на схеме тоньше пикселя — цвет затирки было не разглядеть.

        Считаем не «сколько пикселей затирки всего» (их и от округлений набежит),
        а толщину каждого шва: полоска в один пиксель — это не видно.
        """
        photo = Image.new("RGB", (600, 300), (58, 62, 68))  # тёмная плитка
        png = render_layout(self._wall(joint=1.4), tile_photo=photo, grout="white")
        img = Image.open(io.BytesIO(png))
        white = grout_rgb("white")

        # Столбец через середину стены пересекает горизонтальные швы.
        column = [img.getpixel((img.width // 2, y))[:3] for y in range(img.height)]
        runs, current = [], 0
        for pixel in column:
            if pixel == white:
                current += 1
            elif current:
                runs.append(current)
                current = 0

        assert runs, "затирки на схеме не видно вообще"
        assert min(runs) >= 2, f"швы толщиной {min(runs)} px — мастер их не разглядит"

    def test_grout_falls_back_to_default(self):
        assert grout_rgb(None) == grout_rgb("grey")
        assert grout_rgb("нет такого") == grout_rgb("grey")

    def test_portrait_photo_is_turned_for_a_landscape_tile(self):
        """Мастер снимает плитку как придётся — кадр не должен растянуть рисунок."""
        portrait = Image.new("RGB", (300, 600))
        assert _texture(portrait, 600, 300).size == (600, 300)

    def test_photo_is_not_required(self):
        assert len(render_layout(self._wall(), grout="black")) > 0


class TestTilePacks:
    """Цену плитки пишут за м², а продают упаковками — платить придётся за пачки."""

    def _tile_line(self, per_pack):
        lay = build_layout(Surface("стена", 2000, 2700), Tile(600, 300, per_pack=per_pack))
        mats = calc_materials(lay)
        return next(x for x in mats.lines if x.kind == "tile")

    def test_paid_area_is_rounded_up_to_whole_packs(self):
        line = self._tile_line(per_pack=8)
        packs = math.ceil(line.qty / 8)
        # Платим за целые пачки: 8 плиток по 0.18 м² в каждой.
        assert tile_paid_area_m2(line) == pytest.approx(packs * 8 * 0.18)
        assert tile_paid_area_m2(line) >= line.area_m2

    def test_without_packs_we_fall_back_to_area(self):
        line = self._tile_line(per_pack=None)
        assert tile_paid_area_m2(line) == pytest.approx(line.area_m2)

    def test_rough_cost_uses_paid_packs_not_bare_area(self):
        """По голой площади чек занижался — плитку не продают по метру."""
        line = self._tile_line(per_pack=8)
        price = PriceList(mat_tile_m2=1500)
        assert rough_material_cost(line, price) == pytest.approx(tile_paid_area_m2(line) * 1500)
        assert rough_material_cost(line, price) > (line.area_m2 or 0) * 1500

    def test_packs_survive_the_room_summary(self):
        """Смета берёт сведённую закупку: если per_pack там теряется, упаковок нет.

        Ровно так и было — цена считалась по голой площади, а «уп.» не показывались.
        """
        walls = room_surfaces([2, 1.8, 2, 1.8], 2.7, with_floor=False)
        # 9 штук в пачке: нужное количество на пачки нацело не делится, значит
        # часть последней пачки уйдёт в остаток — и заплатить придётся за неё целиком.
        mats = [calc_materials(build_layout(w, Tile(600, 300, per_pack=9))) for w in walls]
        line = next(x for x in merge_materials(mats) if x.kind == "tile")

        assert line.per_pack == 9
        assert line.qty % 9 != 0, "нужен случай, где пачка не делится нацело"
        assert tile_paid_area_m2(line) > (line.area_m2 or 0)


class TestAngled:
    """Диагональ и ёлочка. Раньше обе считались как прямая укладка — цифры врали."""

    def _wall(self, pattern):
        return build_layout(Surface("стена", 2000, 2700), Tile(600, 300, joint_mm=2), pattern)

    def test_angled_covers_the_wall_without_gaps_or_overlaps(self):
        """Замощение: куски обязаны сойтись в площадь стены — без дыр и нахлёстов."""
        for herringbone in (False, True):
            pieces = angled_pieces(
                2000, 2700, 600, 300, 0.0, herringbone=herringbone, keep_scraps=True
            )
            total = sum(p.area_mm2 for p in pieces)
            assert total == pytest.approx(2000 * 2700, rel=1e-3)

    def test_scraps_are_not_bought(self):
        """Огрызок в доли процента плитки — не подрезка, а мусор на краю.

        Он не кладётся, но в закупку попадал целой плиткой — мастер купил бы лишнее.
        """
        for herringbone in (False, True):
            kw = {"herringbone": herringbone}
            kept = angled_pieces(2000, 2700, 600, 300, 2.0, **kw)
            raw = angled_pieces(2000, 2700, 600, 300, 2.0, keep_scraps=True, **kw)

            assert len(kept) < len(raw), "огрызки не отброшены"
            smallest = min(p.area_mm2 for p in kept) / (600 * 300)
            assert smallest >= 0.02, f"в закупку попал огрызок в {smallest:.1%} плитки"

    def test_almost_whole_tile_is_not_called_a_cut(self):
        """Плитка, у которой сняли волос, — целая: у 45° край почти никогда не по сетке."""
        for pattern in (LayoutPattern.DIAGONAL, LayoutPattern.HERRINGBONE):
            lay = self._wall(pattern)
            for cell in lay.cells:
                if not cell.is_cut:
                    continue
                fraction = polygon_area(cell.polygon) / (600 * 300)
                assert fraction < 0.995, "почти целая плитка помечена как резаная"

    def test_angled_cuts_the_whole_perimeter(self):
        """У 45° режется весь периметр — прямая укладка режет только два края."""
        straight = self._wall(LayoutPattern.STRAIGHT)
        for pattern in (LayoutPattern.DIAGONAL, LayoutPattern.HERRINGBONE):
            angled = self._wall(pattern)
            assert angled.cuts_count > straight.cuts_count * 2
            assert angled.tiles_grid > straight.tiles_grid

    def test_angled_tiles_are_polygons(self):
        """Плитка под углом — не прямоугольник: у стены это треугольник или трапеция."""
        lay = self._wall(LayoutPattern.DIAGONAL)
        assert all(c.polygon for c in lay.cells)
        assert any(len(c.polygon) == 3 for c in lay.cells), "нет ни одного треугольника"

    def test_angled_never_claims_the_layout_is_even(self):
        """«Раскладка ровная» для диагонали — враньё: там режется всё."""
        for pattern in (LayoutPattern.DIAGONAL, LayoutPattern.HERRINGBONE):
            advice = " ".join(self._wall(pattern).advice)
            assert "ровная" not in advice
            assert "режется весь периметр" in advice

    def test_advice_is_identical_across_walls(self):
        """В комнате совет сыпался по разу на стену — с разными цифрами.

        Сколько резать, уже сказано строкой «Класть: N шт, резаных M». Совет должен
        быть одинаковым на всех стенах — тогда сводка покажет его один раз.
        """
        tile = Tile(600, 300, joint_mm=2)
        for pattern in (LayoutPattern.DIAGONAL, LayoutPattern.HERRINGBONE):
            a = build_layout(Surface("а", 2000, 2700), tile, pattern).advice
            b = build_layout(Surface("б", 1800, 2700), tile, pattern).advice
            assert a == b

    def test_each_pattern_gives_its_own_scheme(self):
        """Диагональ и ёлочка выдавали схему байт в байт как «шов в шов»."""
        schemes = {p: render_layout(self._wall(p)) for p in LayoutPattern}
        assert len(set(schemes.values())) == len(LayoutPattern)

    def test_herringbone_pairs_lie_and_stand(self):
        """Ёлочка — пары «лёжа + стоя»: если все плитки одинаковы, это не ёлочка."""
        cells = [c for c in self._wall(LayoutPattern.HERRINGBONE).cells if not c.is_cut]
        wide = sum(1 for c in cells if c.w > c.h)
        tall = sum(1 for c in cells if c.h > c.w)
        assert wide > 0 and tall > 0


class TestBrickOffset:
    """Разбежка — сдвиг относительно СОСЕДНЕГО ряда, а не от края стены."""

    def _seams(self, width, start, ratio=0.5):
        """Где стоит сетка каждого ряда — по первой ЦЕЛОЙ плитке.

        По краевому обрезку смещение не измеришь: он обрублен стеной и врёт.
        """
        lay = build_layout(
            Surface("с", width, 2700), Tile(600, 300, joint_mm=2),
            LayoutPattern.BRICK, start, offset_ratio=ratio,
        )
        rows = {}
        for c in lay.cells:
            rows.setdefault(round(c.y), []).append(c)

        step = 600 + 2
        out = []
        for y in sorted(rows)[:3]:
            row = sorted(rows[y], key=lambda c: c.x)
            whole = next(c for c in row if not c.is_cut)
            out.append(whole.x % step)
        return out

    def test_offset_is_half_a_tile_from_any_start(self):
        """Артём: «на 2 и 4 стене явно не в половину разбежка».

        При старте от центра базовый ряд сам начинается с подрезки — и смещение,
        отсчитанное от края стены, давало 97 мм вместо 301.
        """
        step = 600 + 2
        for width in (2000, 1800, 2400):
            for start in (StartFrom.EDGE, StartFrom.CENTER):
                rows = self._seams(width, start)
                shift = abs(rows[0] - rows[1]) % step
                assert shift == pytest.approx(step / 2, abs=2), (
                    f"стена {width}, старт {start.value}: сдвиг {shift:.0f} вместо {step / 2:.0f}"
                )

    def test_rows_alternate_back_to_the_original_line(self):
        """Через ряд сетка обязана вернуться на место — иначе это лесенка, а не кирпич."""
        rows = self._seams(2000, StartFrom.CENTER)
        assert rows[0] == pytest.approx(rows[2], abs=2)

    def test_deck_offset_walks_a_third_each_row(self):
        """Палубная: ряды идут лесенкой 0 → ⅓ → ⅔, а не через один."""
        step = 600 + 2
        rows = self._seams(2000, StartFrom.EDGE, ratio=1 / 3)
        assert abs(rows[0] - rows[1]) == pytest.approx(step / 3, abs=2)
        assert abs(rows[1] - rows[2]) == pytest.approx(step / 3, abs=2)
        assert rows[0] != pytest.approx(rows[2], abs=2), "при 1/3 через ряд возврата нет"
