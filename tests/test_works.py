"""Калькуляторы видов работ — чистая арифметика, проверяется мутацией."""

from tilebot.core.estimate import PriceList
from tilebot.core.works import (
    Opening,
    WorkKind,
    baseboard,
    laminate,
    plaster,
    plumbing,
    reveals,
)

P = PriceList()


class TestPlaster:
    def test_labor_by_area_and_mix_in_bags(self):
        r = plaster(20.0, layers=2, kg_per_m2=1.2, price=P)
        assert r.kind is WorkKind.PLASTER
        assert r.work_lines[0].qty == 20.0
        assert r.work_sum == 20.0 * P.plastering
        # 20 × 1.2 × 2 = 48 кг → 2 мешка по 25
        bag = next(m for m in r.materials if m.kind == "plaster")
        assert bag.qty == 2

    def test_zero_area_no_bags(self):
        assert plaster(0, layers=1, kg_per_m2=1.2, price=P).materials[0].qty == 0


class TestLaminate:
    def test_packs_include_waste(self):
        # 2.9 м², пачка 2.1, запас 5% → ceil(2.9×1.05/2.1)=ceil(1.45)=2
        r = laminate(2.9, pack_m2=2.1, waste=0.05, underlay=True, price=P)
        packs = next(m for m in r.materials if m.kind == "laminate")
        assert packs.qty == 2
        assert any(m.kind == "underlay" for m in r.materials)
        assert r.work_sum == round(2.9, 2) * P.laminate_laying

    def test_no_underlay(self):
        r = laminate(10, pack_m2=2.0, waste=0.1, underlay=False, price=P)
        assert not any(m.kind == "underlay" for m in r.materials)
        assert next(m for m in r.materials if m.kind == "laminate").qty == 6  # ceil(11/2)


class TestBaseboard:
    def test_planks_and_fittings_separate(self):
        # периметр 7.6, планка 2.5 → 4 планки; соединители = планок−1 = 3 (авто)
        r = baseboard(7.6, plank_m=2.5, inner_corners=4, outer_corners=1, end_caps=2, price=P)
        by = {m.name: m.qty for m in r.materials}
        assert by["Плинтус (планка)"] == 4
        assert by["Соединитель"] == 3  # авто из числа планок
        assert by["Уголок внутренний"] == 4
        assert by["Уголок внешний"] == 1
        assert by["Заглушка"] == 2
        assert r.work_sum == round(7.6, 2) * P.baseboard_mount

    def test_no_fittings_when_zero(self):
        r = baseboard(2.0, plank_m=2.5, inner_corners=0, outer_corners=0, end_caps=0, price=P)
        # одна планка → 0 соединителей; уголков/заглушек нет
        names = {m.name for m in r.materials}
        assert "Соединитель" not in names and "Уголок внутренний" not in names


class TestReveals:
    def test_area_per_opening(self):
        # окно 1.2×1.4, откос 25 см: (2×1.4 + 1.2)×0.25 = 4.0×0.25 = 1.0 м²
        r = reveals([Opening("Окно", 1.2, 1.4)], reveal_width_cm=25, price=P)
        assert r.work_lines[0].qty == 1.0
        assert r.work_sum == 1.0 * P.reveals

    def test_no_openings(self):
        assert reveals([], reveal_width_cm=25, price=P).work_sum == 0


class TestPlumbing:
    def test_sum_of_checked_points(self):
        r = plumbing([
            {"name": "Раковина", "price": 3500, "on": True},
            {"name": "Унитаз", "price": 3000, "on": True},
            {"name": "Ванна", "price": 5000, "on": False},
        ])
        assert r.work_sum == 6500
        assert "2 точ" in r.hero_value

    def test_nothing_checked(self):
        assert plumbing([{"name": "Раковина", "price": 3500, "on": False}]).work_sum == 0


class TestComputeWork:
    """Диспетчер: замеры комнаты → результат нужного вида работ."""

    M = {"walls": [2, 1.8, 2, 1.8], "height_m": 2.7, "floor_m2": 2.9}

    def test_plaster_uses_wall_area(self):
        from tilebot.core.works import compute_work, wall_area_m2
        r = compute_work("plaster", {"surface": "walls", "layers": 1, "kg_per_m2": 1.2}, self.M, P)
        assert r.work_lines[0].qty == round(wall_area_m2(self.M), 2)  # 7.6×2.7=20.52

    def test_laminate_uses_floor(self):
        from tilebot.core.works import compute_work
        r = compute_work("laminate", {"pack_m2": 2.1, "waste": 0.05, "underlay": True}, self.M, P)
        assert r.work_lines[0].qty == 2.9

    def test_baseboard_perimeter_from_measures(self):
        from tilebot.core.works import compute_work
        # без perimeter_m — берёт периметр из замеров (сумма стен = 7.6)
        r = compute_work("baseboard", {"plank_m": 2.5, "corners": 4}, self.M, P)
        assert r.work_lines[0].qty == 7.6

    def test_baseboard_manual_perimeter(self):
        from tilebot.core.works import compute_work
        r = compute_work("baseboard", {"perimeter_m": 6.8, "plank_m": 2.5, "corners": 4}, self.M, P)
        assert r.work_lines[0].qty == 6.8

    def test_manual_area_overrides_measures(self):
        from tilebot.core.works import compute_work
        r = compute_work("laminate", {"area_m2": 10, "pack_m2": 2.0, "waste": 0.1}, self.M, P)
        assert r.work_lines[0].qty == 10

    def test_default_input_prefilled(self):
        from tilebot.core.works import default_input
        assert default_input("laminate", self.M)["underlay"] is True
        assert len(default_input("plumbing", self.M)["points"]) >= 6
        assert default_input("baseboard", self.M)["inner_corners"] == 4  # по числу стен
