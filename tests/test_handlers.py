"""Сценарии бота целиком — от «🧱 Плитка» до списка закупки.

Здесь ловится то, что не видно ядру: потерянный шаг FSM, кнопка с чужим
callback_data, ввод, который бот молча понял не так. Все числа — Сашины, из его
замечаний по первой версии.

Сценарий комнаты и разбор сводки живут в conftest: ими пользуются и тесты
мини-аппа — он обязан считать ту же комнату теми же числами.
"""

from conftest import _room_flow, _tile_qty, _tile_qty_anywhere


class TestJoint:
    async def test_fractional_joint_survives_the_whole_flow(self, app):
        """Саша ввёл «1,4» — бот показывал «шов 1 мм», как будто ввод проигнорирован."""
        await _tile_flow(app, joint="1,4")
        assert app.said("шов 1,4 мм")
        assert not app.said("шов 1 мм")

    async def test_joint_buttons_cover_the_usual_sizes(self, app):
        await app.send("🧱 Плитка")
        await app.click("Одна стена или пол")
        await app.send("Ванная")
        await app.click("Стена")
        await app.send("2 2.7")
        await app.send("60 30")

        assert app.said("Какой шов")
        assert app.find_button("1,5 мм") is not None
        assert app.find_button("2 мм") is not None

    async def test_joint_from_button_is_used(self, app):
        await _tile_flow(app, joint_button="1,5 мм")
        assert app.said("шов 1,5 мм")


class TestWaste:
    async def test_waste_is_asked_and_defaults_to_seven(self, app):
        """Саша: «как правило 7% делается запасом», а не магазинные 10%."""
        await _tile_flow(app, stop_after="waste")
        assert app.said("Запас плитки")
        assert app.said("советую 7%")
        assert app.find_button("7% ✓") is not None

    async def test_chosen_waste_lands_in_the_purchase_list(self, app):
        await _tile_flow(app, waste="15%")
        assert app.said("с запасом 15%")


class TestOpenings:
    async def test_openings_are_not_asked_by_default(self, app):
        """Саша: «проём не обязательно высчитывать» — плитки у двери всё равно режутся."""
        await _tile_flow(app)
        assert not app.said("Есть что вычесть")
        assert app.find_button("Учесть проём") is not None


class TestPrice:
    async def test_tile_price_is_not_asked_in_the_flow(self, app):
        """Мастер продаёт работу; плитку заказчик покупает сам по списку.

        Цена плитки в потоке — лишний шаг ради строки, которой в смете быть не должно.
        """
        await _room_flow(app)
        assert not app.said("Цена плитки")
        assert not app.said("Плитка на ")


class TestRoom:
    async def test_whole_room_gives_one_purchase_list(self, app):
        """Главное замечание: бот считал по одной стене, на ванную выходило 4 сметы."""
        await _room_flow(app)

        assert app.said("Комната целиком")
        assert app.said("4 стены + пол")
        # Одна сводка на всю комнату, а не отдельная на каждую стену.
        assert len([t for t in app.texts if "Купить:" in t]) == 1
        assert app.photos_sent() == 5  # схема на каждую стену и на пол

    async def test_wall_tile_is_one_position_in_the_purchase_list(self, app):
        """600×300 и 300×600 — одна плитка в магазине, а не две позиции."""
        await _room_flow(app, floor_tile=None)  # везде одна плитка
        summary = next(t for t in app.texts if "Купить:" in t)
        assert summary.count("• Плитка") == 1

    async def test_floor_tile_is_bought_separately(self, app):
        """На пол своя плитка — значит в списке покупок это отдельная позиция."""
        await _room_flow(app, floor_tile="60 60")
        summary = next(t for t in app.texts if "Купить:" in t)

        assert "• Плитка 600×300" in summary  # стены
        assert "• Плитка 600×600" in summary  # пол
        assert summary.count("• Плитка") == 2

    async def test_room_asks_walls_then_height_separately(self, app):
        await app.send("🧱 Плитка")
        await app.click("Комната целиком")
        await app.send("Ванная, Борзова")
        await app.send("2 1.8 2 1.8")

        assert app.said("Стен: <b>4</b>")
        assert app.said("периметр 7.60 м")
        assert app.said("высота")

    async def test_height_in_centimetres_is_refused_not_guessed(self, app):
        """«270» по общему правилу — 27 см. Молча посчитать такую комнату нельзя."""
        await app.send("🧱 Плитка")
        await app.click("Комната целиком")
        await app.send("Ванная")
        await app.send("2 1.8 2 1.8")
        await app.send("270")

        assert app.said("единицы перепутаны")
        assert not app.said("Размер плитки")

    async def test_crooked_room_is_not_offered_a_floor(self, app):
        await app.send("🧱 Плитка")
        await app.click("Комната целиком")
        await app.send("Кривая")
        await app.send("2 1.8 2.5 1.8")
        await app.send("2.7")

        assert app.find_button("Да, и пол") is None
        assert app.said("Размер плитки")


class TestRepattern:
    async def test_pattern_can_be_switched_after_the_result(self, app):
        """Артём: посмотреть и так, и так — с пересчётом."""
        await _room_flow(app)
        await app.click("Сменить раскладку")
        diagonal = app.find_button("Диагональ")
        assert diagonal is not None

        app.forget()  # дальше смотрим только на то, что бот прислал после нажатия
        await app.click_data(diagonal)

        assert app.said("Купить:")
        assert app.photos_sent() == 5


class TestArea:
    async def test_right_angles_do_not_ask_for_a_diagonal(self, app):
        """Артём: если углы прямые, диагональ спрашивать незачем."""
        await app.send("📐 Площадь")
        await app.click("Четырёхугольник")
        await app.click("Углы прямые")
        assert not app.said("диагональ и")

        await app.send("2 1.8 2 1.8")
        assert app.said("Площадь: 3.60 м²")

    async def test_skew_angles_still_ask_for_the_diagonal(self, app):
        await app.send("📐 Площадь")
        await app.click("Четырёхугольник")
        await app.click("Есть косой угол")
        await app.send("4 3 4 3 5")
        assert app.said("Площадь: 12.00 м²")

    async def test_degenerate_quad_explains_itself(self, app):
        """Сашин случай: 2 2 2 2 и диагональ 4 — бот сказал только «перемерь»."""
        await app.send("📐 Площадь")
        await app.click("Четырёхугольник")
        await app.click("Есть косой угол")
        await app.send("2 2 2 2 4")

        assert app.said("2.83")
        assert app.said("Углы прямые")


# --- сценарии-хелперы --------------------------------------------------------


async def _tile_flow(
    app,
    *,
    joint: str = "2",
    joint_button: str | None = None,
    waste: str = "7%",
    stop_after: str | None = None,
) -> None:
    """Одна стена от начала до списка закупки."""
    await app.send("🧱 Плитка")
    await app.click("Одна стена или пол")
    await app.send("Ванная, Борзова")
    await app.click("Стена")
    await app.send("2 2.7")
    await app.send("60 30")

    if joint_button:
        await app.click(joint_button)
    else:
        await app.send(joint)

    await app.click("9 мм")
    await app.click("Пропустить")  # штук в упаковке
    await app.click("Шов в шов")
    await app.click("От угла")

    if stop_after == "waste":
        return

    await app.click(waste)
    await app.click("Не нужна")


class TestTilePhoto:
    """Артём: после покупки плитки прислать фото — и на схеме будет она."""

    async def test_photo_is_asked_and_redraws_the_room(self, app):
        await _room_flow(app)
        await app.click("Фото плитки")
        assert app.said("Пришли <b>фото плитки</b>")

        app.forget()
        await app.send_photo()

        assert app.said("Взял твою плитку")
        # Замеры мастер вводил один раз — комнату перерисовываем, а не спрашиваем заново.
        assert not app.said("Обмерь комнату")
        assert app.photos_sent() == 5
        assert app.said("Купить:")
        # Фото реально ушло в схему, а не просто осело в базе.
        assert app.downloaded_files() == ["tilephoto1"]

    async def test_photo_survives_a_pattern_switch(self, app):
        """Сменил раскладку — плитка должна остаться его, а не сброситься в серую."""
        await _room_flow(app)
        await app.click("Фото плитки")
        await app.send_photo()

        await app.click("Сменить раскладку")
        herringbone = app.find_button("Ёлочка")

        app.forget()
        await app.click_data(herringbone)

        assert app.photos_sent() == 5
        assert app.said("Купить:")
        assert app.downloaded_files() == ["tilephoto1"]

    async def test_non_photo_is_refused(self, app):
        await _room_flow(app)
        await app.click("Фото плитки")
        await app.send("60 30")
        assert app.said("Жду фото плитки")


class TestGrout:
    async def test_grout_colour_can_be_picked_and_redraws(self, app):
        await _room_flow(app)
        await app.click("Цвет затирки")
        assert app.find_button("Белая") is not None
        assert app.find_button("Графит") is not None
        black = app.find_button("Чёрная")

        app.forget()
        await app.click_data(black)

        assert app.photos_sent() == 5
        assert app.said("Купить:")

    async def test_picked_grout_is_marked(self, app):
        await _room_flow(app)
        await app.click("Цвет затирки")
        await app.click("Бежевая")
        await app.click("Цвет затирки")
        assert app.find_button("Бежевая ✓") is not None


class TestEstimateAndAct:
    """Смета — до работ и по прайсу. Акт — после, по факту."""

    async def test_estimate_hides_material_cost(self, app):
        """Артём: в смете стоимость материалов не показывать — заказчик покупает сам."""
        await _room_flow(app)
        app.forget()
        await app.click("Смета заказчику")

        assert app.said("РАБОТА:")
        assert app.said("Материалы — купить")  # список покупок остаётся
        assert not app.said("ВСЁ ВМЕСТЕ")  # итог сметы — только работа
        assert not app.said("≈ ")  # у строк закупки нет прикидки в рублях

    async def test_estimate_does_not_sell_materials(self, app):
        """Материалы — не заработок мастера: в стоимость работы они не входят."""
        await _room_flow(app)
        app.forget()
        await app.click("Смета заказчику")
        assert app.said("в стоимость работы они не входят")

    async def test_act_asks_the_real_price_then_totals(self, app):
        await _room_flow(app)
        app.forget()
        await app.click("Акт выполненных работ")
        assert app.said("Почём вышла плитка")

        await app.send("1450")
        assert app.said("Акт выполненных работ —")
        assert app.said("ИТОГО К ОПЛАТЕ:")

    async def test_act_without_own_purchase_is_work_only(self, app):
        """Плитку купил заказчик — в акте только работа."""
        await _room_flow(app)
        await app.click("Акт выполненных работ")
        app.forget()
        await app.send("0")

        assert app.said("ИТОГО К ОПЛАТЕ:")
        assert app.said("куплено заказчиком")


class TestRotate:
    """Артём: «указал 70 20, а хочу 20 70». Как плитка лежит — решает мастер."""

    def _tile_line(self, app):
        summary = [t for t in app.texts if "Купить:" in t][-1]
        return next(x for x in summary.splitlines() if x.startswith("Плитка "))

    async def test_tile_can_be_turned_on_its_side(self, app):
        await _room_flow(app)
        before = self._tile_line(app)

        app.forget()
        await app.click("Повернуть плитку")
        after = self._tile_line(app)

        assert before != after, "плитка не повернулась"
        assert ("лёжа" in before) != ("лёжа" in after)

    async def test_rotation_survives_a_pattern_switch(self, app):
        """Иначе бот тут же перевернёт плитку обратно «как лучше» — кнопка бесполезна."""
        await _room_flow(app)
        await app.click("Повернуть плитку")
        rotated = self._tile_line(app)

        await app.click("Сменить раскладку")
        await app.click("Ёлочка")

        assert self._tile_line(app) == rotated

    async def test_rotation_survives_an_opening(self, app):
        """Проём пересохраняет поверхность — поворот при этом терять нельзя.

        Проверяем не сразу, а после следующего пересчёта: сброшенный флаг всплывает
        именно там, а в ответе на сам проём ещё не виден.
        """
        await _tile_flow(app)
        await app.click("Повернуть плитку")
        rotated = self._tile_line(app)

        await app.click("Учесть проём")
        await app.send("дверь 0.8 2.1")
        assert self._tile_line(app) == rotated

        await app.click("Сменить раскладку")
        await app.click("Ёлочка")
        assert self._tile_line(app) == rotated


class TestAdviceInRoom:
    async def test_angled_advice_is_not_repeated_per_wall(self, app):
        """Артём: в комнате один и тот же совет прилетал 4 раза с разными цифрами."""
        await _room_flow(app)
        await app.click("Сменить раскладку")
        await app.click("Диагональ")

        summary = [t for t in app.texts if "Купить:" in t][-1]
        tips = [line for line in summary.splitlines() if line.startswith("💡")]
        assert len(tips) == len(set(tips)), f"советы дублируются: {tips}"
        assert sum(1 for t in tips if "Диагональ" in t) == 1


class TestFloorTile:
    """Артём: «у пола может быть другая плитка, другой размер»."""

    async def test_floor_tile_is_asked_only_when_there_is_a_floor(self, app):
        await _room_flow(app, floor_tile=None)
        assert app.said("Плитка <b>на пол</b>")

    async def test_walls_only_room_is_not_asked_about_floor_tile(self, app):
        await app.send("🧱 Плитка")
        await app.click("Комната целиком")
        await app.send("Только стены")
        await app.send("2 1.8 2 1.8")
        await app.send("2.7")
        await app.click("Только стены")
        await app.send("60 30")
        await app.send("2")
        await app.click("9 мм")
        await app.click("Пропустить")

        assert not app.said("Плитка <b>на пол</b>")
        assert app.said("Как кладём")

    async def test_same_tile_button_keeps_one_position(self, app):
        await _room_flow(app, floor_tile=None)
        summary = next(t for t in app.texts if "Купить:" in t)
        assert summary.count("• Плитка") == 1


class TestResize:
    """Артём: «надо оперативно менять размер плитки, чтобы считать быстрее»."""

    def _tiles(self, app):
        summary = [t for t in app.texts if "Купить:" in t][-1]
        return [x for x in summary.splitlines() if x.startswith("• Плитка")]

    async def test_wall_tile_size_can_be_changed(self, app):
        await _room_flow(app, floor_tile="60 60")
        before = self._tiles(app)

        await app.click("Размер плитки")
        await app.click("Стены")
        await app.send("20 20")  # мелкая плитка — и штук станет заметно больше
        after = self._tiles(app)

        assert before != after
        assert any("200×200" in x for x in after), after
        assert not any("600×300" in x for x in after), "старая плитка осталась"
        # Пол не трогали — он остался своим.
        assert any("600×600" in x for x in after), after

    async def test_floor_tile_size_can_be_changed_separately(self, app):
        await _room_flow(app, floor_tile="60 60")

        await app.click("Размер плитки")
        await app.click("Пол")
        await app.send("30 30")

        tiles = self._tiles(app)
        assert any("300×300" in x for x in tiles), tiles
        assert any("600×300" in x for x in tiles), "стены не должны были поменяться"

    async def test_single_surface_is_not_asked_where(self, app):
        """Если поверхность одна, спрашивать «стены или пол» незачем."""
        await _tile_flow(app)
        await app.click("Размер плитки")
        assert app.said("Новый размер плитки")


class TestGroutKind:
    """Артём согласовал: затирка двух видов. Эпоксидная бьёт по работе, не по мешку."""

    async def test_grout_kind_can_be_switched(self, app):
        await _room_flow(app)
        await app.click("Вид затирки")
        assert app.find_button("Цементная ✓") is not None

        await app.click("Эпоксидная")
        summary = [t for t in app.texts if "Купить:" in t][-1]
        assert "Затирка эпоксидная" in summary

    async def test_epoxy_costs_more_in_work_not_in_the_bag(self, app):
        await _room_flow(app)
        await app.click("Смета заказчику")
        cement = [t for t in app.texts if "РАБОТА:" in t][-1]

        await app.click("Вид затирки")
        await app.click("Эпоксидная")
        await app.click("Смета заказчику")
        epoxy = [t for t in app.texts if "РАБОТА:" in t][-1]

        assert "Затирка швов эпоксидной" in epoxy
        assert cement != epoxy


class TestCutting:
    """Артём: «работа плиточника должна зависеть от раскладки и количества подрезки»."""

    async def test_cutting_is_a_separate_work_line(self, app):
        await _room_flow(app)
        await app.click("Смета заказчику")
        assert app.said("Подрезка плитки")

    async def test_diagonal_costs_more_than_straight(self, app):
        await _room_flow(app)
        await app.click("Сменить раскладку")
        await app.click("Шов в шов")
        await app.click("Смета заказчику")
        straight = _work_total(app)

        await app.click("Сменить раскладку")
        await app.click("Диагональ")
        await app.click("Смета заказчику")
        diagonal = _work_total(app)

        # И надбавка за раскладку, и рез: на диагонали режется весь периметр.
        assert diagonal > straight
        assert app.said("Надбавка за раскладку (диагональ)")


def _work_total(app) -> int:
    line = [t for t in app.texts if "РАБОТА:" in t][-1]
    row = next(x for x in line.splitlines() if "РАБОТА:" in x)
    return int("".join(ch for ch in row if ch.isdigit()))


class TestEconomyWrap:
    """Саня, голосовое 16.07: «от угла ведёт целую плитку и подрезку — огромный
    расход… можно ли, чтобы от целой отрезал 798 и от неё от угла прошло
    продолжение дальше — это безотходный вариант».
    """

    async def test_button_switches_room_to_the_band(self, app):
        await _room_flow(app)
        app.forget()

        await app.click("Эконом: по кругу")

        assert app.said("эконом по кругу"), "режим не показан в сводке"
        assert app.said("Эконом сберёг"), "не сказал, сколько плиток сэкономил"
        assert app.said("остатки плиток с прошлой стены"), "не объяснил, что за куски"
        # Замеры вводили один раз — комната перерисовывается целиком.
        assert app.photos_sent() == 5

    async def test_economy_actually_buys_less_tile(self, app):
        """Главное для мастера: закупка обязана уменьшиться, а не просто «режим включён»."""
        await _room_flow(app)
        before = _tile_qty(app.last_text)

        app.forget()
        await app.click("Эконом: по кругу")
        after = _tile_qty(app.last_text)

        assert after < before, f"плитки {before} → {after}: эконом не сэкономил"

    async def test_economy_reaches_the_papers_the_customer_gets(self, app):
        """Смета и итог обязаны считать ТУ ЖЕ раскладку, что мастер видит на схеме.

        Здесь у бота был свой, более бедный расчёт для документов: эконом-лента до
        сметы не доезжала, и схема обещала 39 плиток, пока смета заказчику требовала
        44. Мастер отдаёт заказчику бумагу, которая спорит с его же схемой.
        """
        await _room_flow(app)
        await app.click("Эконом: по кругу")
        on_scheme = _tile_qty(app.last_text)

        app.forget()
        await app.click("Итог по объекту")
        assert _tile_qty(app.last_text) == on_scheme, (
            f"итог по объекту считает не то, что схема: {on_scheme} на схеме"
        )

        app.forget()
        await app.click("Смета заказчику")
        assert _tile_qty_anywhere(app.texts) == on_scheme, (
            f"смета заказчику считает не то, что схема: {on_scheme} на схеме"
        )

    async def test_switching_back_restores_the_normal_layout(self, app):
        """Кнопка-обманка — худшее: обещали вернуть обычную, значит вернули."""
        await _room_flow(app)
        normal = _tile_qty(app.last_text)

        await app.click("Эконом: по кругу")
        app.forget()
        await app.click("Вернуть обычную")

        assert _tile_qty(app.last_text) == normal
        assert not app.said("эконом по кругу")

    async def test_single_wall_has_no_economy_button(self, app):
        """На одной стене заворачивать за угол нечего — кнопки быть не должно."""
        await app.send("🧱 Плитка")
        await app.click("Одна стена или пол")
        await app.send("Стена")
        await app.click("Стена")
        await app.send("2 2.7")
        await app.send("60 30")
        await app.send("2")
        await app.click("9 мм")
        await app.click("Пропустить")
        await app.click("Шов в шов")
        await app.click("От угла")
        await app.click("7%")
        await app.click("Не нужна")

        assert app.find_button("Эконом") is None, "эконом предложен там, где он невозможен"

    async def test_diagonal_drops_the_economy_button(self, app):
        """Под 45° лента не считается — кнопку предлагать нельзя."""
        await _room_flow(app)
        await app.click("Сменить раскладку")
        app.forget()
        await app.click("Диагональ")

        assert not any("Эконом" in t for t in app.last_markup_titles()), (
            f"эконом предложен на диагонали: {app.last_markup_titles()}"
        )

    async def test_old_economy_button_on_diagonal_explains_itself(self, app):
        """Кнопка из старой сводки в чате остаётся — нажатие не должно молча падать.

        Мастер переключил комнату на диагональ, пролистал вверх и нажал «Эконом»
        из прошлого сообщения: бот обязан объяснить, а не сломаться.
        """
        await _room_flow(app)
        wrap_button = app.find_button("Эконом: по кругу")
        assert wrap_button, "кнопки эконома нет — тест бессмысленен"

        await app.click("Сменить раскладку")
        await app.click("Диагональ")
        app.forget()

        await app.click_data(wrap_button)

        assert app.said("Под 45° так не выйдет"), f"нет объяснения: {app.texts}"
        assert not app.said("Эконом сберёг"), "посчитал ленту на диагонали"


class TestAppMenuButton:
    """Мини-апп открывается кнопкой слева от поля ввода (chat menu button).

    Reply-кнопки снизу нет: initData Telegram передаёт и так, но она дублировала
    бы вход и путалась с кнопками расчёта. FSM при этом на месте — главное меню не
    тронуто.
    """

    def test_menu_button_points_at_the_app(self):
        from aiogram.types import MenuButtonWebApp

        from tilebot.bot.keyboards import app_menu_button

        btn = app_menu_button("https://plitka.example/app")
        assert isinstance(btn, MenuButtonWebApp)
        assert btn.text == "Приложение"
        # URL несёт cache-bust ?v=<mtime app.js>: Telegram кэширует по полному
        # адресу, новый ?v заставляет открыть свежую страницу, а не залипшую.
        assert btn.web_app.url.startswith("https://plitka.example/app?v=")

    def test_no_url_falls_back_to_the_commands_button(self):
        """Пустой адрес Telegram не примет — возвращаем дефолтную кнопку команд."""
        from aiogram.types import MenuButtonCommands

        from tilebot.bot.keyboards import app_menu_button

        assert isinstance(app_menu_button(""), MenuButtonCommands)

    def test_plain_http_is_not_offered(self):
        from aiogram.types import MenuButtonCommands

        from tilebot.bot.keyboards import app_menu_button

        assert isinstance(app_menu_button("http://plitka.example"), MenuButtonCommands)

    def test_main_menu_has_no_app_button(self):
        """Ряд с мини-аппом убран из reply-меню — вход теперь слева."""
        from tilebot.bot.keyboards import MAIN_MENU

        titles = [b.text for row in MAIN_MENU.keyboard for b in row]
        assert "📱 Приложение" not in titles
        assert {"🧱 Плитка", "📐 Площадь", "📋 Мои объекты", "💰 Прайс"} <= set(titles)

    async def test_start_installs_the_menu_button_for_the_chat(self, app):
        """Кнопку слева ставим per-chat на /start: глобальную дефолтную Telegram
        держит на «commands», web_app туда не встаёт, а per-chat приживается."""
        from conftest import SASHA

        await app.send("/start")

        sent = [m for m in app.session.sent if type(m).__name__ == "SetChatMenuButton"]
        assert sent, "на /start кнопку меню не поставили"
        assert sent[0].chat_id == SASHA
