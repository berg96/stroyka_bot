"""Мини-апп: вход по initData, чужое не отдаём, цифры те же, что у бота.

Главный тест здесь — паритет. Мини-апп делается, чтобы Саня сравнил его с ботом
и сказал, где ему удобнее. Если на одних и тех же замерах бот и мини-апп покажут
разную закупку, сравнивать будет нечего: мастер решит, что бот врёт.
"""

import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlencode

import pytest
from conftest import _room_flow, _tile_qty, sample_tile_photo
from httpx import ASGITransport, AsyncClient

from tilebot import receipts
from tilebot.config import Settings
from tilebot.web.app import create_app

TOKEN = "42:TEST"
SASHA = 383853880


def init_data(user_id: int = SASHA, *, token: str = TOKEN, auth_date: int | None = None) -> str:
    """Подписать initData так, как это делает Telegram."""
    pairs = {
        "user": json.dumps({"id": user_id, "first_name": "Саня"}, ensure_ascii=False),
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAA",
    }
    check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


@pytest.fixture
async def api(storage):
    settings = Settings(bot_token=TOKEN, db_path=":memory:")
    app = create_app(storage=storage, settings=settings)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://miniapp",
        headers={"X-Init-Data": init_data()},
    ) as client:
        yield client


ROOM = {
    "walls_m": [2, 1.8, 2, 1.8],
    "height_m": 2.7,
    "with_floor": True,
    "tile": {"width_mm": 600, "height_mm": 300, "joint_mm": 1.4, "per_pack": 8},
    "floor_tile": {"width_mm": 600, "height_mm": 600, "joint_mm": 1.4, "per_pack": 4},
    "pattern": "brick",
    "start_from": "auto",
    "waste": 0.07,
    "waterproofing": True,
}


async def _room_via_api(api) -> dict:
    """Та же ванная, что `_room_flow` в тестах бота, только через HTTP."""
    created = await api.post("/api/projects", json={"title": "Ванная, Борзова"})
    project_id = created.json()["id"]
    r = await api.post(f"/api/projects/{project_id}/room", json=ROOM)
    assert r.status_code == 201, r.text
    return {"id": project_id, "result": r.json()}


class TestAuth:
    """Номер мастера берём из подписи Telegram, а не из тела запроса."""

    async def test_without_init_data_is_refused(self, api):
        r = await api.get("/api/projects", headers={"X-Init-Data": ""})
        assert r.status_code == 401

    async def test_forged_signature_is_refused(self, api):
        forged = init_data(user_id=1, token="666:NOT-OUR-BOT")
        r = await api.get("/api/projects", headers={"X-Init-Data": forged})
        assert r.status_code == 401

    async def test_tampered_user_is_refused(self, api):
        """Подменить id в подписанной строке — самый очевидный способ влезть к чужому."""
        good = init_data()
        tampered = good.replace("383853880", "111111111")
        r = await api.get("/api/projects", headers={"X-Init-Data": tampered})
        assert r.status_code == 401

    async def test_stale_init_data_is_refused(self, api):
        old = init_data(auth_date=int(time.time()) - 90000)  # сутки с лишним
        r = await api.get("/api/projects", headers={"X-Init-Data": old})
        assert r.status_code == 401

    async def test_someone_elses_project_is_not_found(self, api):
        mine = await _room_via_api(api)
        stranger = init_data(user_id=999)

        r = await api.get(f"/api/projects/{mine['id']}", headers={"X-Init-Data": stranger})

        assert r.status_code == 404
        assert "Ванная" not in r.text, "чужому видно название объекта"


class TestParityWithBot:
    """Ради этого всё и затевалось: бот и мини-апп считают одним ядром."""

    async def test_same_room_gives_the_same_purchase(self, api, app):
        # Бот: те же замеры теми же кнопками.
        await _room_flow(app)
        bot_summary = next(t for t in app.texts if "Купить:" in t)
        bot_tile = re.search(r"Плитка 600×300: <b>(\d+) шт", bot_summary)
        assert bot_tile, bot_summary

        via_api = (await _room_via_api(api))["result"]
        api_tile = next(line for line in via_api["purchase"] if line["name"] == "Плитка 600×300")

        assert api_tile["qty_text"] == bot_tile.group(1), (
            f"мини-апп велит купить {api_tile['qty_text']}, бот — {bot_tile.group(1)}"
        )
        assert f"{via_api['area_m2']:.2f}" in bot_summary, "площадь разошлась"

    async def test_economy_saves_the_same_tiles_as_in_the_bot(self, api, app):
        await _room_flow(app)
        await app.click("Эконом: по кругу")
        bot_after = _tile_qty(app.last_text)

        room = await _room_via_api(api)
        r = await api.patch(f"/api/projects/{room['id']}", json={"wrap": True})
        api_after = next(
            line for line in r.json()["purchase"] if line["name"] == "Плитка 600×300"
        )

        assert r.json()["wrap"] is True
        assert int(api_after["qty_text"]) == bot_after, (
            f"эконом в мини-аппе {api_after['qty_text']}, в боте {bot_after}"
        )
        assert r.json()["savings"]["tiles"] > 0


class TestRoom:
    async def test_room_returns_a_scheme_per_surface(self, api):
        room = await _room_via_api(api)
        assert len(room["result"]["surfaces"]) == 5  # 4 стены + пол
        assert room["result"]["walls"] == 4
        assert room["result"]["has_floor"] is True

    async def test_floor_tile_is_a_separate_line(self, api):
        room = await _room_via_api(api)
        names = [line["name"] for line in room["result"]["purchase"]]
        assert "Плитка 600×300" in names  # стены
        assert "Плитка 600×600" in names  # пол

    async def test_crooked_room_is_refused_a_floor_not_invented(self, api):
        """У кривой комнаты пол по стенам не восстановить — врать нельзя."""
        created = await api.post("/api/projects", json={"title": "Кривая"})
        r = await api.post(
            f"/api/projects/{created.json()['id']}/room",
            json={**ROOM, "walls_m": [2, 1.8, 2.5, 1.8]},
        )
        assert r.status_code == 422
        assert "кривая" in r.json()["error"]

    async def test_scheme_is_a_png(self, api):
        room = await _room_via_api(api)
        r = await api.get(f"/api/projects/{room['id']}/scheme/0.png")

        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"

    async def test_scheme_of_a_missing_surface_is_404(self, api):
        room = await _room_via_api(api)
        r = await api.get(f"/api/projects/{room['id']}/scheme/99.png")
        assert r.status_code == 404


class TestPatch:
    async def test_pattern_switch_recounts(self, api):
        room = await _room_via_api(api)
        before = room["result"]["cuts_count"]

        r = await api.patch(f"/api/projects/{room['id']}", json={"pattern": "diagonal"})

        assert r.json()["pattern"] == "diagonal"
        assert r.json()["cuts_count"] > before, "диагональ режется не больше прямой"

    async def test_economy_on_diagonal_is_explained_not_silently_ignored(self, api):
        room = await _room_via_api(api)
        await api.patch(f"/api/projects/{room['id']}", json={"pattern": "diagonal"})

        r = await api.patch(f"/api/projects/{room['id']}", json={"wrap": True})

        assert r.status_code == 409
        assert "45" in r.json()["error"]

    async def test_rotate_sticks(self, api):
        """Повернул сам — бот не имеет права перевернуть обратно «как лучше»."""
        room = await _room_via_api(api)
        tile = room["result"]["tile"]

        r = await api.patch(f"/api/projects/{room['id']}", json={"rotate": True})
        turned = r.json()["tile"]

        assert (turned["width_mm"], turned["height_mm"]) == (tile["height_mm"], tile["width_mm"])
        assert r.json()["tile_locked"] is True

        # Пересчёт не должен вернуть «как лучше».
        again = await api.get(f"/api/projects/{room['id']}")
        assert again.json()["result"]["tile"]["width_mm"] == turned["width_mm"]

    async def test_tile_size_change_recounts_walls_only(self, api):
        room = await _room_via_api(api)
        r = await api.patch(
            f"/api/projects/{room['id']}",
            json={"tile_size": {"width_mm": 1200, "height_mm": 600, "kind": "wall"}},
        )
        names = [line["name"] for line in r.json()["purchase"]]

        assert "Плитка 1200×600" in names
        assert "Плитка 600×600" in names, "пол пересчитали заодно, хотя просили стены"

    async def test_grout_kind_changes_the_work_not_the_bag(self, api):
        room = await _room_via_api(api)
        cement = (await api.get(f"/api/projects/{room['id']}/estimate")).json()

        await api.patch(f"/api/projects/{room['id']}", json={"grout_kind": "epoxy"})
        epoxy = (await api.get(f"/api/projects/{room['id']}/estimate")).json()

        assert epoxy["works_total"] > cement["works_total"], "эпоксидную дольше затирать"


class TestPapers:
    async def test_estimate_sells_work_not_materials(self, api):
        """Мастер продаёт работу; плитку заказчик покупает сам."""
        room = await _room_via_api(api)
        est = (await api.get(f"/api/projects/{room['id']}/estimate")).json()

        assert est["works_total"] > 0
        assert est["materials_total"] == 0, "смета продаёт материалы"
        assert est["materials"], "в смете нет списка покупок"

    async def test_estimate_matches_the_scheme(self, api):
        """Документ заказчику обязан считать ту же раскладку, что схема."""
        room = await _room_via_api(api)
        await api.patch(f"/api/projects/{room['id']}", json={"wrap": True})

        result = (await api.get(f"/api/projects/{room['id']}")).json()["result"]
        est = (await api.get(f"/api/projects/{room['id']}/estimate")).json()

        on_scheme = next(m for m in result["purchase"] if m["name"] == "Плитка 600×300")
        in_paper = next(m for m in est["materials"] if m["name"] == "Плитка 600×300")
        assert in_paper["qty_text"] == on_scheme["qty_text"]

    async def test_act_totals_what_the_customer_pays(self, api):
        room = await _room_via_api(api)
        await api.patch(f"/api/projects/{room['id']}", json={"tile_price": 1450})

        act = (await api.get(f"/api/projects/{room['id']}/act")).json()

        assert act["materials_total"] > 0, "мастер закупался сам — это в акт"
        assert act["grand_total"] == pytest.approx(act["works_total"] + act["materials_total"])

    async def test_empty_project_has_nothing_to_count(self, api):
        created = await api.post("/api/projects", json={"title": "Пустой"})
        r = await api.get(f"/api/projects/{created.json()['id']}/estimate")
        assert r.status_code == 409


class TestPriceAndMoney:
    async def test_price_is_editable_and_reaches_the_estimate(self, api):
        room = await _room_via_api(api)
        before = (await api.get(f"/api/projects/{room['id']}/estimate")).json()["works_total"]

        await api.put("/api/price", json={"wall_tiling": 2400})
        after = (await api.get(f"/api/projects/{room['id']}/estimate")).json()["works_total"]

        assert after > before

    async def test_unknown_price_line_is_refused(self, api):
        r = await api.put("/api/price", json={"откат": 100})
        assert r.status_code == 422

    async def test_payments_track_what_the_customer_still_owes(self, api):
        room = await _room_via_api(api)
        await api.put(f"/api/projects/{room['id']}/deal", json={"amount": 50000})
        r = await api.post(f"/api/projects/{room['id']}/payments", json={"amount": 20000})

        assert r.json()["paid"] == 20000
        assert r.json()["due"] == 30000

    async def test_overpayment_is_not_a_negative_debt(self, api):
        room = await _room_via_api(api)
        await api.put(f"/api/projects/{room['id']}/deal", json={"amount": 10000})
        r = await api.post(f"/api/projects/{room['id']}/payments", json={"amount": 15000})
        assert r.json()["due"] == 0


class TestProjects:
    async def test_projects_are_listed_newest_first(self, api):
        await api.post("/api/projects", json={"title": "Первый"})
        await api.post("/api/projects", json={"title": "Второй"})

        titles = [p["title"] for p in (await api.get("/api/projects")).json()]
        assert titles[0] == "Второй"

    async def test_project_can_be_deleted(self, api):
        room = await _room_via_api(api)
        assert (await api.delete(f"/api/projects/{room['id']}")).status_code == 200
        assert (await api.get(f"/api/projects/{room['id']}")).status_code == 404


class TestWorks:
    """Объект = замеры + несколько работ (расширение 18.07)."""

    async def test_object_has_measures_and_tile_work(self, api):
        room = await _room_via_api(api)
        obj = (await api.get(f"/api/objects/{room['id']}")).json()
        assert obj["measures"]["walls"]  # замеры сохранились из комнаты
        assert any(w["kind"] == "tile" for w in obj["works"])  # плитка как работа

    async def test_add_edit_delete_work(self, api):
        room = await _room_via_api(api)
        w = (await api.post(f"/api/objects/{room['id']}/works", json={"kind": "laminate"})).json()
        assert w["kind"] == "laminate" and w["work_sum"] > 0  # взял пол из замеров
        assert any(m["name"] == "Подложка" for m in w["materials"])

        obj = (await api.get(f"/api/objects/{room['id']}")).json()
        assert len(obj["works"]) == 2 and obj["total"] > 0

        w2 = (await api.patch(f"/api/objects/{room['id']}/works/{w['id']}",
                              json={"input": {"underlay": False}})).json()
        assert not any(m["name"] == "Подложка" for m in w2["materials"])

        assert (await api.delete(f"/api/objects/{room['id']}/works/{w['id']}")).status_code == 200
        obj2 = (await api.get(f"/api/objects/{room['id']}")).json()
        assert len(obj2["works"]) == 1  # снова только плитка

    async def test_plumbing_points_sum(self, api):
        room = await _room_via_api(api)
        w = (await api.post(f"/api/objects/{room['id']}/works", json={"kind": "plumbing"})).json()
        assert w["work_sum"] == 0  # по умолчанию ничего не выбрано
        pts = w["input"]["points"]
        pts[0]["on"] = True
        w2 = (await api.patch(f"/api/objects/{room['id']}/works/{w['id']}",
                              json={"input": {"points": pts}})).json()
        assert w2["work_sum"] == pts[0]["price"]

    async def test_unknown_kind_rejected(self, api):
        room = await _room_via_api(api)
        r = await api.post(f"/api/objects/{room['id']}/works", json={"kind": "магия"})
        assert r.status_code == 422

    async def test_estimate_merges_duplicate_works_and_materials(self, api):
        """Две одинаковые работы → одна строка работы и одна строка закупки
        (мастер покупает материал разом). Мутационно: без сведения строк было бы 2."""
        room = await _room_via_api(api)
        w1 = (await api.post(f"/api/objects/{room['id']}/works", json={"kind": "plaster"})).json()
        single_qty = w1["work_lines"][0]["qty"]  # площадь одной штукатурки (из замеров)
        await api.post(f"/api/objects/{room['id']}/works", json={"kind": "plaster"})
        est = (await api.get(f"/api/objects/{room['id']}/estimate")).json()
        plaster_work = [w for w in est["works"] if w["name"] == "Штукатурка/шпаклёвка"]
        plaster_mat = [m for m in est["materials"] if m["name"] == "Смесь штукатурная"]
        assert len(plaster_work) == 1, "две штукатурки не свелись в одну строку работы"
        assert len(plaster_mat) == 1, "смесь двух работ не свелась в одну строку закупки"
        # Свелись, а не потерялись: количество — сумма двух работ.
        assert plaster_work[0]["qty"] == round(single_qty * 2, 2)

    async def test_someone_elses_work_not_found(self, api):
        room = await _room_via_api(api)
        w = (await api.post(f"/api/objects/{room['id']}/works", json={"kind": "laminate"})).json()
        stranger = init_data(user_id=999)
        r = await api.patch(f"/api/objects/{room['id']}/works/{w['id']}",
                            json={"input": {}}, headers={"X-Init-Data": stranger})
        assert r.status_code == 404


class TestObjectEstimate:
    """Общая смета/акт по объекту — все работы (плитка + другие) в один документ."""

    async def test_estimate_combines_all_works(self, api):
        room = await _room_via_api(api)
        await api.post(f"/api/objects/{room['id']}/works", json={"kind": "laminate"})
        est = (await api.get(f"/api/objects/{room['id']}/estimate")).json()
        assert any("ламинат" in w["name"].lower() for w in est["works"])  # работа ламината
        assert est["works_total"] > 0  # плитка + ламинат
        assert any("Ламинат" in m["name"] for m in est["materials"])  # материалы обоих
        # Стоимости материалов в смете нет — ни по строкам, ни в итоге.
        assert all(m["cost"] is None for m in est["materials"])
        assert est["grand_total"] == pytest.approx(est["works_total"])

    async def test_act_totals_work_plus_materials(self, api):
        room = await _room_via_api(api)
        await api.patch(f"/api/projects/{room['id']}", json={"tile_price": 1450})
        await api.post(f"/api/objects/{room['id']}/works", json={"kind": "plaster"})
        act = (await api.get(f"/api/objects/{room['id']}/act")).json()
        assert act["materials_total"] > 0, "иначе равенство ниже выполняется само собой"
        assert act["grand_total"] == pytest.approx(act["works_total"] + act["materials_total"])

    async def test_act_prices_only_what_the_master_paid(self, api):
        """Всё, кроме плитки, в счёт по выдуманной цене не ставим — цен на них нет.

        Клей, затирку, штукатурную смесь мастер то покупает, то нет; цена бралась
        из справочника прайса и молча уезжала заказчику в «ИТОГО К ОПЛАТЕ».
        """
        room = await _room_via_api(api)
        await api.patch(f"/api/projects/{room['id']}", json={"tile_price": 1450})
        await api.post(f"/api/objects/{room['id']}/works", json={"kind": "plaster"})
        act = (await api.get(f"/api/objects/{room['id']}/act")).json()

        tiles = [m for m in act["materials"] if "Плитка" in m["name"]]
        assert tiles and all(m["cost"] for m in tiles), "цену плитки мастер вбил — она в акте"
        others = [m for m in act["materials"] if "Плитка" not in m["name"]]
        assert len(others) >= 2, "нужны материалы и плитки, и штукатурки"
        assert all(m["cost"] is None for m in others), [m["name"] for m in others]


class TestTileDecoupled:
    """Плитка расцеплена с созданием: Саню могут позвать не на плитку.

    «Замерь комнату» сохраняет геометрию без обязательной плитки; плитка —
    добавляемая работа поверх готовых замеров.
    """

    MEASURE_ONLY = {"walls_m": [2, 1.8, 2, 1.8], "height_m": 2.7}

    async def _measured_room(self, api) -> int:
        created = await api.post("/api/projects", json={"title": "Ламинат, Борзова"})
        pid = created.json()["id"]
        r = await api.post(f"/api/projects/{pid}/room", json=self.MEASURE_ONLY)
        assert r.status_code == 201, r.text
        return pid

    async def test_room_without_tile_saves_measures_no_surfaces(self, api):
        pid = await self._measured_room(api)
        obj = (await api.get(f"/api/objects/{pid}")).json()
        assert obj["measures"]["walls"] == [2, 1.8, 2, 1.8]
        assert obj["measures"]["floor_m2"] > 0  # пол восстановлен и БЕЗ плитки
        assert obj["has_tile"] is False
        assert not any(w["kind"] == "tile" for w in obj["works"])

    async def test_laminate_works_on_measure_only_room(self, api):
        """Замерили под ламинат — пол из замеров есть, работа считается."""
        pid = await self._measured_room(api)
        w = (await api.post(f"/api/objects/{pid}/works", json={"kind": "laminate"})).json()
        assert w["work_sum"] > 0  # взял пол из замеров, хотя плитки нет

    async def test_add_tile_as_work_builds_surfaces(self, api):
        pid = await self._measured_room(api)
        r = await api.post(f"/api/projects/{pid}/tile", json={"tile": ROOM["tile"]})
        assert r.status_code == 201, r.text
        assert r.json()["walls"] == 4  # 4 стены разложены
        obj = (await api.get(f"/api/objects/{pid}")).json()
        assert obj["has_tile"] is True
        assert any(w["kind"] == "tile" for w in obj["works"])

    async def test_tile_twice_is_refused(self, api):
        pid = await self._measured_room(api)
        first = await api.post(f"/api/projects/{pid}/tile", json={"tile": ROOM["tile"]})
        assert first.status_code == 201
        r = await api.post(f"/api/projects/{pid}/tile", json={"tile": ROOM["tile"]})
        assert r.status_code == 409  # плитка на объекте одна

    async def test_tile_without_measures_is_refused(self, api):
        created = await api.post("/api/projects", json={"title": "Пустой"})
        pid = created.json()["id"]
        r = await api.post(f"/api/projects/{pid}/tile", json={"tile": ROOM["tile"]})
        assert r.status_code == 422  # сначала замерь комнату

    async def test_quick_path_room_with_tile_still_works(self, api):
        """Быстрый путь (частый кейс Сани): замеры + плитка одним запросом."""
        room = await _room_via_api(api)
        obj = (await api.get(f"/api/objects/{room['id']}")).json()
        assert obj["has_tile"] is True
        assert any(w["kind"] == "tile" for w in obj["works"])


class TestActParityWithBot:
    """Акт бота и мини-аппа обязаны сойтись до рубля.

    Раньше не сходились: мини-апп добирал материалы справочными ценами прайса,
    бот печатал только факт. Один объект — два разных «ИТОГО К ОПЛАТЕ»; заказчику
    ушёл бы тот, который мастер открыл последним. Справочные цены выпилены 01.08.
    """

    async def test_same_object_same_total(self, api, app):
        await _room_flow(app)
        await app.click("Акт выполненных работ")
        await app.send("1450")  # почём вышла плитка
        bot_act = next(t for t in app.texts if "ИТОГО К ОПЛАТЕ" in t)
        bot_total = re.search(r"ИТОГО К ОПЛАТЕ: ([\d\s\xa0]+₽)", bot_act)
        assert bot_total, bot_act

        project_id = (await api.get("/api/projects")).json()[0]["id"]
        web_act = (await api.get(f"/api/projects/{project_id}/act")).json()
        # И объектный акт (у него своя сборка со сведением строк) — та же цифра.
        object_act = (await api.get(f"/api/objects/{project_id}/act")).json()

        assert web_act["grand_total_text"] == bot_total.group(1)
        assert object_act["grand_total_text"] == bot_total.group(1)


class TestExpensesApi:
    """Закупки мастера через мини-апп: сумма, приписка, фото чека."""

    async def test_expense_lands_in_the_debt_and_comes_back(self, api):
        room = await _room_via_api(api)
        await api.put(f"/api/projects/{room['id']}/deal", json={"amount": 120000})

        r = await api.post(
            f"/api/projects/{room['id']}/expenses",
            data={"amount": "12400", "comment": "клей, затирка"},
        )

        assert r.status_code == 201, r.text
        brief = r.json()
        assert brief["spent"] == 12400
        assert brief["due"] == 132400  # работа + закупка
        assert brief["expenses"][0]["comment"] == "клей, затирка"
        assert brief["expenses"][0]["receipt"] is False

    async def test_receipt_is_stored_and_served_back(self, api):
        room = await _room_via_api(api)
        photo = sample_tile_photo()  # любая картинка — важно, что вернётся та же

        r = await api.post(
            f"/api/projects/{room['id']}/expenses",
            data={"amount": "6000", "comment": "грунтовка"},
            files={"receipt": ("cheque.jpg", photo, "image/jpeg")},
        )
        expense_id = r.json()["expenses"][0]["id"]
        got = await api.get(f"/api/expenses/{expense_id}/receipt")

        assert r.json()["expenses"][0]["receipt"] is True
        assert got.status_code == 200
        assert got.content == photo

    async def test_someone_elses_receipt_is_not_served(self, api):
        room = await _room_via_api(api)
        r = await api.post(
            f"/api/projects/{room['id']}/expenses",
            data={"amount": "6000"},
            files={"receipt": ("cheque.jpg", sample_tile_photo(), "image/jpeg")},
        )
        expense_id = r.json()["expenses"][0]["id"]

        stranger = init_data(user_id=999)
        got = await api.get(
            f"/api/expenses/{expense_id}/receipt", headers={"X-Init-Data": stranger}
        )

        assert got.status_code == 404

    async def test_pdf_receipt_is_refused(self, api):
        """Показать pdf в мини-аппе нечем — молча положить его хуже, чем отказать."""
        room = await _room_via_api(api)
        r = await api.post(
            f"/api/projects/{room['id']}/expenses",
            data={"amount": "6000"},
            files={"receipt": ("cheque.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert r.status_code == 422

    async def test_act_with_receipts_matches_the_bot(self, api, app):
        """Чеки в акте — одна строка и один итог во всех трёх путях (бот + 2 веб)."""
        await _room_flow(app)
        project_id = (await api.get("/api/projects")).json()[0]["id"]
        await api.post(f"/api/projects/{project_id}/expenses", data={"amount": "50000"})

        await app.click("Акт выполненных работ")  # цену плитки не спросит — есть чеки
        bot_act = next(t for t in app.texts if "ИТОГО К ОПЛАТЕ" in t)
        bot_total = re.search(r"ИТОГО К ОПЛАТЕ: ([\d\s\xa0]+₽)", bot_act)
        web_act = (await api.get(f"/api/projects/{project_id}/act")).json()
        object_act = (await api.get(f"/api/objects/{project_id}/act")).json()

        assert "Материалы по чекам" in bot_act
        assert web_act["receipts_total"] == 50000
        assert web_act["grand_total"] == pytest.approx(web_act["works_total"] + 50000)
        assert web_act["grand_total_text"] == bot_total.group(1)
        assert object_act["grand_total_text"] == bot_total.group(1)


class TestExpenseEditing:
    """Опечатку в сумме надо уметь убрать: она уезжает прямо в долг заказчика."""

    async def test_expense_is_deleted_with_its_receipt(self, api):
        room = await _room_via_api(api)
        r = await api.post(
            f"/api/projects/{room['id']}/expenses",
            data={"amount": "124000"},  # промах по нулю
            files={"receipt": ("cheque.jpg", sample_tile_photo(), "image/jpeg")},
        )
        expense_id = r.json()["expenses"][0]["id"]
        name = f"{expense_id}.jpg"
        assert receipts.path(name) is not None

        brief = (await api.delete(f"/api/expenses/{expense_id}")).json()

        assert brief["spent"] == 0
        assert brief["expenses"] == []
        assert receipts.path(name) is None, "файл чека остался на диске"

    async def test_someone_elses_expense_is_not_deleted(self, api):
        room = await _room_via_api(api)
        r = await api.post(f"/api/projects/{room['id']}/expenses", data={"amount": "6000"})
        expense_id = r.json()["expenses"][0]["id"]

        stranger = init_data(user_id=999)
        got = await api.delete(
            f"/api/expenses/{expense_id}", headers={"X-Init-Data": stranger}
        )

        assert got.status_code == 404
        assert (await api.get(f"/api/projects/{room['id']}")).json()["spent"] == 6000

    async def test_heavy_receipt_is_refused(self, api):
        room = await _room_via_api(api)
        heavy = b"x" * (receipts.MAX_BYTES + 1)

        r = await api.post(
            f"/api/projects/{room['id']}/expenses",
            data={"amount": "6000"},
            files={"receipt": ("cheque.jpg", heavy, "image/jpeg")},
        )

        assert r.status_code == 422
        assert (await api.get(f"/api/projects/{room['id']}")).json()["spent"] == 0
