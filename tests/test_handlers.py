"""Сценарии бота целиком — от «🧱 Плитка» до списка закупки.

Здесь ловится то, что не видно ядру: потерянный шаг FSM, кнопка с чужим
callback_data, ввод, который бот молча понял не так. Все числа — Сашины, из его
замечаний по первой версии.
"""


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


class TestRoom:
    async def test_whole_room_gives_one_purchase_list(self, app):
        """Главное замечание: бот считал по одной стене, на ванную выходило 4 сметы."""
        await _room_flow(app)

        assert app.said("Комната целиком")
        assert app.said("4 стены + пол")
        # Одна сводка на всю комнату, а не отдельная на каждую стену.
        assert len([t for t in app.texts if "Купить:" in t]) == 1
        assert app.photos_sent() == 5  # схема на каждую стену и на пол

    async def test_tile_is_one_position_in_the_purchase_list(self, app):
        """600×300 и 300×600 — одна плитка в магазине."""
        await _room_flow(app)
        summary = next(t for t in app.texts if "Купить:" in t)
        assert summary.count("• Плитка") == 1

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
    await app.click("Пропустить")  # цена
    await app.click("Пропустить")  # упаковка
    await app.click("Шов в шов")
    await app.click("От угла")

    if stop_after == "waste":
        return

    await app.click(waste)
    await app.click("Не нужна")


async def _room_flow(app) -> None:
    """Ванная целиком: 4 стены, пол, плитка 60×30."""
    await app.send("🧱 Плитка")
    await app.click("Комната целиком")
    await app.send("Ванная, Борзова")
    await app.send("2 1.8 2 1.8")
    await app.send("2.7")
    await app.click("Да, и пол")
    await app.send("60 30")
    await app.send("1,4")
    await app.click("9 мм")
    await app.send("1450")
    await app.send("8")
    await app.click("Вразбежку")
    await app.click("Как лучше")
    await app.click("7%")
    await app.click("Да, мокрая зона")


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
