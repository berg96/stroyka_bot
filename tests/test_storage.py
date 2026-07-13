"""Изоляция данных между мастерами.

База одна на всех, поэтому владельца проверяет каждый запрос. Номер объекта
приходит из callback_data — то есть с клиента, и подставить туда чужой ничего не
стоит. Эти тесты держат ту границу.
"""

import pytest

from tilebot.storage import Storage

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
