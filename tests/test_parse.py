import pytest

from tilebot.bot.handlers.tiling import _parse_openings
from tilebot.bot.parse import (
    ParseError,
    amount_and_comment,
    dimensions,
    meters,
    name_and_numbers,
    numbers,
    to_mm,
)


class TestNumbers:
    def test_zero_is_a_valid_number(self):
        # Ноль — это координата у пола и «не знаю» в необязательных полях.
        # Запрет на ноль здесь ломал ввод «дверь 0.8 2.1 от 1.9 0».
        assert numbers("1.9 0") == [1.9, 0.0]

    def test_comma_is_a_decimal_separator(self):
        assert numbers("2,7 2,5") == [2.7, 2.5]

    @pytest.mark.parametrize("text", ["2.7x2.5", "2.7х2.5", "2.7*2.5", "2.7, 2.5", "2.7  2.5"])
    def test_separators_people_actually_type(self, text):
        assert numbers(text) == [2.7, 2.5]

    def test_not_a_number(self):
        with pytest.raises(ParseError, match="не число"):
            numbers("два метра")


class TestUnits:
    def test_small_values_are_meters(self):
        assert to_mm(2.7) == 2700

    def test_large_values_are_millimeters(self):
        assert to_mm(2700) == 2700

    def test_dimensions_accept_both(self):
        assert dimensions("2.7 2.5") == [2700, 2500]
        assert dimensions("2700 2500") == [2700, 2500]

    def test_dimensions_reject_zero(self):
        with pytest.raises(ParseError, match="больше нуля"):
            dimensions("0 2.5")

    def test_meters_normalize_millimeters(self):
        assert meters("4000 3000") == [4.0, 3.0]


class TestNameAndNumbers:
    def test_splits_name_from_sizes(self):
        assert name_and_numbers("минус короб 0.4 0.6") == ("минус короб", [0.4, 0.6])

    def test_bare_numbers_have_no_name(self):
        assert name_and_numbers("0.8 2.1") == ("", [0.8, 2.1])

    def test_no_sizes_at_all(self):
        with pytest.raises(ParseError):
            name_and_numbers("просто дверь")


class TestOpenings:
    def test_door_standing_on_the_floor(self):
        # Регрессия: y=0 раньше падало с «размер должен быть больше нуля».
        [door] = _parse_openings("дверь 0.8 2.1 от 1.9 0")
        assert door.name == "дверь"
        assert (door.width_mm, door.height_mm) == (800, 2100)
        assert (door.x_mm, door.y_mm) == (1900, 0)

    def test_opening_without_position(self):
        [window] = _parse_openings("окно 1.2 1.4")
        assert (window.x_mm, window.y_mm) == (None, None)

    def test_several_openings(self):
        items = _parse_openings("дверь 0.8 2.1\nокно 1.2 1.4 от 0.5 1.0")
        assert [o.name for o in items] == ["дверь", "окно"]

    def test_zero_sized_opening_is_rejected(self):
        with pytest.raises(ParseError, match="больше нуля"):
            _parse_openings("дверь 0 2.1")

    def test_negative_offset_is_rejected(self):
        with pytest.raises(ParseError, match="отрицательным"):
            _parse_openings("дверь 0.8 2.1 от -1 0")


class TestPayments:
    def test_amount_first(self):
        assert amount_and_comment("30000 аванс") == (30000.0, "аванс")

    def test_comment_first(self):
        assert amount_and_comment("аванс 30000") == (30000.0, "аванс")

    def test_bare_amount(self):
        assert amount_and_comment("25000") == (25000.0, "")

    def test_comment_on_both_sides(self):
        assert amount_and_comment("получил 15000 наличкой") == (15000.0, "получил наличкой")

    def test_decimal_comma(self):
        assert amount_and_comment("1500,50 остаток") == (1500.5, "остаток")

    def test_no_amount(self):
        with pytest.raises(ParseError, match="суммы"):
            amount_and_comment("аванс")

    def test_zero_payment_is_rejected(self):
        with pytest.raises(ParseError, match="больше нуля"):
            amount_and_comment("0 аванс")
