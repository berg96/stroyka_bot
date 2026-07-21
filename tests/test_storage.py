"""Изоляция данных между мастерами.

База одна на всех, поэтому владельца проверяет каждый запрос. Номер объекта
приходит из callback_data — то есть с клиента, и подставить туда чужой ничего не
стоит. Эти тесты держат ту границу.
"""

import json

import pytest

from tilebot.core.estimate import PriceList
from tilebot.storage import Storage, User

SASHA = 383853880
FRIEND = 111222333


@pytest.fixture
async def storage(tmp_path):
    s = Storage(str(tmp_path / "test.sqlite3"))
    await s.init()
    return s


class TestProjectIsolation:
    async def test_each_master_sees_only_his_own_projects(self, storage):
        await storage.create_project(SASHA, "Ванная, Борзова")
        await storage.create_project(FRIEND, "Кухня друга")

        sasha_titles = [p.title for p in await storage.list_projects(SASHA)]
        friend_titles = [p.title for p in await storage.list_projects(FRIEND)]

        assert sasha_titles == ["Ванная, Борзова"]
        assert friend_titles == ["Кухня друга"]

    async def test_a_stranger_cannot_open_someone_elses_project(self, storage):
        project = await storage.create_project(SASHA, "Ванная, Борзова")

        assert await storage.get_project(project.id, SASHA) is not None
        # Тот же номер объекта, но чужой мастер — как будто объекта нет.
        assert await storage.get_project(project.id, FRIEND) is None

    async def test_a_stranger_cannot_write_into_someone_elses_project(self, storage):
        project = await storage.create_project(SASHA, "Ванная, Борзова")

        assert await storage.add_payment(project.id, FRIEND, 30000, "аванс") is False
        assert await storage.add_photo(project.id, FRIEND, "file-id") is False
        assert await storage.set_deal_amount(project.id, FRIEND, 60000) is False
        assert await storage.add_surface(project.id, FRIEND, "{}") is False

        mine = await storage.get_project(project.id, SASHA)
        assert mine.payments == []
        assert mine.photos == []
        assert mine.surfaces == []
        assert mine.deal_amount == 0

    async def test_a_stranger_cannot_delete_someone_elses_project(self, storage):
        project = await storage.create_project(SASHA, "Ванная, Борзова")

        assert await storage.delete_project(project.id, FRIEND) is False
        assert await storage.get_project(project.id, SASHA) is not None

        assert await storage.delete_project(project.id, SASHA) is True
        assert await storage.get_project(project.id, SASHA) is None


class TestMoney:
    async def test_payments_add_up_and_leave_a_balance(self, storage):
        project = await storage.create_project(SASHA, "Ванная")
        await storage.set_deal_amount(project.id, SASHA, 60000)
        await storage.add_payment(project.id, SASHA, 30000, "аванс")
        await storage.add_payment(project.id, SASHA, 5000, "")

        project = await storage.get_project(project.id, SASHA)
        assert project.paid == 35000
        assert project.due == 25000

    async def test_overpayment_is_not_a_negative_debt(self, storage):
        project = await storage.create_project(SASHA, "Ванная")
        await storage.set_deal_amount(project.id, SASHA, 10000)
        await storage.add_payment(project.id, SASHA, 12000, "с запасом")

        project = await storage.get_project(project.id, SASHA)
        assert project.due == 0


class TestPriceSchemaTolerance:
    """Прайс мастера и поверхности лежат в БД как JSON. Версии бота и мини-аппа
    гуляют по набору полей — запись НОВЕЕ (лишний ключ) или СТАРЕЕ (нет ключа) не
    должна ронять смету. Так у Сани 20.07 упала смета: бот на коде без `plastering`
    читал price_json из веба, где `plastering` уже был → TypeError → «что-то пошло
    не так». Защита — общий `from_dict` (см. [[core/models.py]])."""

    def test_unknown_field_from_a_newer_version_is_ignored(self):
        raw = PriceList().__dict__ | {"plastering": 350.0, "totally_new_field": 99}
        user = User(price_json=json.dumps(raw))
        price = user.price  # раньше падало TypeError на unexpected keyword
        assert price.wall_tiling == PriceList().wall_tiling

    def test_missing_field_falls_back_to_default(self):
        user = User(price_json=json.dumps({"wall_tiling": 1500.0}))
        price = user.price
        assert price.wall_tiling == 1500.0
        assert price.floor_tiling == PriceList().floor_tiling

    def test_surface_tile_survives_an_unknown_field_from_a_newer_app(self):
        # Тот же риск для плитки: веб дописал плитке поле, бот на старом коде читает.
        from tilebot.core.models import Tile, from_dict

        stored = Tile(width_mm=600, height_mm=1200).__dict__ | {"future_flag": True}
        tile = from_dict(Tile, stored)
        assert tile.width_mm == 600 and tile.height_mm == 1200
