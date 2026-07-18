"""HTTP-обвязка мини-аппа: те же объекты, тот же расчёт, другой экран.

Здесь нет ни одной формулы. Считает `core.project.compute_project` — тот же
вызов, что и у бота, поэтому цифры на схеме, в смете и в мини-аппе разойтись не
могут. Этот модуль только достаёт объект из базы, зовёт ядро и раскладывает
результат в JSON.

Бот при этом живёт как жил: мини-апп — ещё одна дверь к тем же данным, а не
замена FSM. Мастер сравнивает и выбирает, где ему удобнее.
"""

import io
import logging
import math
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

from tilebot.config import Settings, get_settings
from tilebot.core.estimate import Estimate, PriceList, build_estimate, money
from tilebot.core.materials import MaterialLine
from tilebot.core.models import (
    BRICK_OFFSETS,
    WASTE_BY_PATTERN,
    GroutKind,
    LayoutPattern,
    Opening,
    SavedSurface,
    StartFrom,
    Surface,
    SurfaceKind,
    Tile,
)
from tilebot.core.parse import ParseError, dimensions, meters, tile_dimensions
from tilebot.core.project import ProjectResult, compute_project
from tilebot.core.room import MAX_HEIGHT_M, MIN_HEIGHT_M, floor_dims, room_surfaces
from tilebot.core.units import fmt_mm
from tilebot.core.works import (
    WORK_NAME,
    WorkKind,
    compute_work,
    default_input,
)
from tilebot.core.wrap import supports_wrap
from tilebot.render.scheme import render_layout
from tilebot.storage import Project, Storage, payload_to_surface, surface_to_payload
from tilebot.web.auth import InitDataError, verify_init_data

logger = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"

NOT_FOUND = "Объект не найден."


# --- вход ---------------------------------------------------------------------


def _tg_id(init_data: str, settings: Settings) -> int:
    try:
        return verify_init_data(init_data, settings.bot_token)
    except InitDataError as e:
        # Наружу — без подробностей: чем именно не понравился initData, знать
        # незачем, а в логе разберёмся.
        logger.warning("miniapp: отказ по initData — %s", e)
        raise HTTPException(
            status_code=401, detail="Не удалось опознать. Открой через бота."
        ) from e


def create_app(storage: Storage | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = storage or Storage(settings.db_path)

    app = FastAPI(title="Помощник плиточника", docs_url=None, redoc_url=None)

    async def current_user(
        x_init_data: Annotated[str, Header(alias="X-Init-Data")] = "",
    ) -> int:
        return _tg_id(x_init_data, settings)

    User = Annotated[int, Depends(current_user)]

    async def owned(project_id: int, user_id: int) -> Project:
        project = await store.get_project(project_id, user_id)
        if project is None:
            # Чужой объект и несуществующий — одно и то же: не подсказываем, что
            # объект с таким номером вообще есть.
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return project

    async def computed(project_id: int, user_id: int) -> tuple[Project, ProjectResult]:
        project = await owned(project_id, user_id)
        if not project.surfaces:
            raise HTTPException(status_code=409, detail="В объекте пока нет поверхностей.")
        return project, compute_project(
            [payload_to_surface(row.dump()) for row in project.surfaces]
        )

    # --- объекты --------------------------------------------------------------

    @app.get("/api/me")
    async def me(user: User) -> dict:
        record = await store.get_or_create_user(user)
        return {
            "id": record.tg_id,
            "name": record.name,
            "phone": record.phone,
            "price": asdict(record.price),
        }

    @app.get("/api/projects")
    async def list_projects(user: User) -> list[dict]:
        projects = await store.list_projects(user, limit=50)
        return [_project_brief(p) for p in projects]

    @app.post("/api/projects", status_code=201)
    async def create_project(body: TitleIn, user: User) -> dict:
        project = await store.create_project(user, body.title)
        return {"id": project.id, "title": project.title}

    @app.delete("/api/projects/{project_id}")
    async def delete_project(project_id: int, user: User) -> dict:
        if not await store.delete_project(project_id, user):
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return {"ok": True}

    @app.get("/api/projects/{project_id}")
    async def get_project(project_id: int, user: User) -> dict:
        project = await owned(project_id, user)
        out = _project_brief(project)
        if project.surfaces:
            result = compute_project(
                [payload_to_surface(row.dump()) for row in project.surfaces]
            )
            out["result"] = _result_json(result)
        return out

    # --- замеры ---------------------------------------------------------------

    @app.post("/api/measure")
    async def measure(body: MeasureIn) -> dict:
        """Разобрать то, что мастер набрал руками: «2 1.8 2 1.8», «60х30», «2,7».

        Тем же парсером, что и бот: Санин ввод — источник реальных граблей
        («27» вместо 2.7, шов «1,4»), и заводить второй разбор на JS значит
        завести второй набор этих граблей.
        """
        try:
            if body.kind == "walls":
                values = meters(body.text)
                if not 2 <= len(values) <= 12:
                    raise ParseError("Стен должно быть от 2 до 12.")
            elif body.kind == "height":
                (value,) = meters(body.text, count=1)
                if not MIN_HEIGHT_M <= value <= MAX_HEIGHT_M:
                    raise ParseError(
                        f"Высота {value:.2f} м — это точно так? Похоже, единицы перепутаны. "
                        "Напиши в метрах (2.7) или в миллиметрах (2700)."
                    )
                values = [value]
            elif body.kind == "tile":
                values = tile_dimensions(body.text)
            else:  # size — стена или пол: ширина и высота
                values = [v / 1000 for v in dimensions(body.text, count=2)]
        except ParseError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return {"values": values}

    @app.post("/api/projects/{project_id}/room", status_code=201)
    async def add_room(project_id: int, body: RoomIn, user: User) -> dict:
        await owned(project_id, user)
        if body.with_floor and floor_dims(body.walls_m) is None:
            raise HTTPException(
                status_code=422,
                detail="По таким стенам пол не восстановить — комната кривая. "
                "Померь пол отдельной поверхностью.",
            )
        surfaces = room_surfaces(body.walls_m, body.height_m, with_floor=body.with_floor)
        # Замеры комнаты — на уровень объекта: их переиспользуют другие виды работ
        # (ламинат берёт пол, штукатурка — стены, плинтус — периметр).
        dims = floor_dims(body.walls_m) if body.with_floor else None
        floor_m2 = round(dims[0] * dims[1], 2) if dims else 0.0
        await store.set_measures(
            project_id, user,
            {"walls": body.walls_m, "height_m": body.height_m, "floor_m2": floor_m2},
        )
        return await _save_and_compute(project_id, user, surfaces, body)

    @app.post("/api/projects/{project_id}/surface", status_code=201)
    async def add_surface(project_id: int, body: SurfaceIn, user: User) -> dict:
        project = await owned(project_id, user)
        kind = SurfaceKind(body.kind)
        surface = Surface(
            name=("Стена" if kind is SurfaceKind.WALL else "Пол")
            + f" {len(project.surfaces) + 1}",
            width_mm=body.width_m * 1000,
            height_mm=body.height_m * 1000,
            kind=kind,
        )
        return await _save_and_compute(project_id, user, [surface], body)

    async def _save_and_compute(
        project_id: int, user_id: int, surfaces: list[Surface], body: "TilingIn"
    ) -> dict:
        """Посчитать новые поверхности ядром и сохранить ровно то, что посчитано."""
        resolve_start = body.start_from == "auto"
        wall_tile = body.tile.to_tile()
        floor_tile = body.floor_tile.to_tile() if body.floor_tile else wall_tile

        saved_all = [
            SavedSurface(
                surface=surface,
                tile=wall_tile if surface.kind is SurfaceKind.WALL else floor_tile,
                pattern=LayoutPattern(body.pattern),
                start_from=StartFrom.EDGE if resolve_start else StartFrom(body.start_from),
                waterproofing=body.waterproofing,
                waste=body.waste,
            )
            for surface in surfaces
        ]
        result = compute_project(saved_all, resolve_start=resolve_start)

        for layout in result.layouts:
            ok = await store.add_surface(
                project_id,
                user_id,
                surface_to_payload(
                    layout.surface,
                    layout.tile,
                    layout.pattern,
                    layout.start_from,
                    waterproofing=body.waterproofing,
                    waste=body.waste,
                ),
            )
            if not ok:
                raise HTTPException(status_code=404, detail=NOT_FOUND)

        _, fresh = await computed(project_id, user_id)
        return _result_json(fresh)

    @app.post("/api/projects/{project_id}/opening")
    async def add_opening(project_id: int, body: OpeningIn, user: User) -> dict:
        project = await owned(project_id, user)
        row = next((r for r in project.surfaces if r.id == body.surface_id), None)
        if row is None:
            raise HTTPException(status_code=404, detail="Поверхность не найдена.")

        saved = payload_to_surface(row.dump())
        opening = Opening(
            name=body.name or "проём",
            width_mm=body.width_m * 1000,
            height_mm=body.height_m * 1000,
        )
        # Пересохраняем поверхность целиком: проём — не повод забыть фото плитки,
        # затирку и поворот.
        ok = await store.update_surface(
            body.surface_id,
            user,
            surface_to_payload(
                Surface(
                    name=saved.surface.name,
                    width_mm=saved.surface.width_mm,
                    height_mm=saved.surface.height_mm,
                    kind=saved.surface.kind,
                    openings=[*saved.surface.openings, opening],
                ),
                saved.tile,
                saved.pattern,
                saved.start_from,
                waterproofing=saved.waterproofing,
                waste=saved.waste,
                tile_photo_id=saved.tile_photo_id,
                grout=saved.grout,
                tile_locked=saved.tile_locked,
                grout_kind=saved.grout_kind.value,
                offset_ratio=saved.offset_ratio,
                wrap=saved.wrap,
            ),
        )
        if not ok:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        _, result = await computed(project_id, user)
        return _result_json(result)

    # --- правка посчитанного --------------------------------------------------

    @app.patch("/api/projects/{project_id}")
    async def patch_project(project_id: int, body: PatchIn, user: User) -> dict:
        """Всё «покажи иначе» одним эндпоинтом — как одна кнопка в боте.

        Замеры мастер вводил один раз; здесь меняются только решения поверх них.
        """
        _, before = await computed(project_id, user)
        changes: dict[str, Any] = {}

        if body.pattern is not None:
            # Запас сбрасываем: прежний выбирали под другую раскладку.
            changes["pattern"] = LayoutPattern(body.pattern).value
            changes["waste"] = None
        if body.start_from is not None:
            changes["start_from"] = StartFrom(body.start_from).value
        if body.offset_label is not None:
            changes["offset_ratio"] = BRICK_OFFSETS[body.offset_label]
        if body.grout is not None:
            changes["grout"] = body.grout
        if body.grout_kind is not None:
            changes["grout_kind"] = GroutKind(body.grout_kind).value
        if body.waste is not None:
            changes["waste"] = body.waste
        if body.waterproofing is not None:
            changes["waterproofing"] = body.waterproofing

        if body.wrap is not None:
            pattern = LayoutPattern(body.pattern) if body.pattern else before.head.pattern
            if body.wrap and not _wrap_ok(before, pattern):
                raise HTTPException(
                    status_code=409,
                    detail="Под 45° так не выйдет: там и так режется весь периметр. "
                    "Эконом работает на «шов в шов» и «вразбежку».",
                )
            changes["wrap"] = body.wrap

        if changes and not await store.update_project_surfaces(project_id, user, **changes):
            raise HTTPException(status_code=404, detail=NOT_FOUND)

        if body.rotate:
            await store.rotate_tile(project_id, user)
        if body.tile_size is not None:
            await store.set_tile_size(
                project_id,
                user,
                body.tile_size.width_mm,
                body.tile_size.height_mm,
                kind=body.tile_size.kind,
            )
        if body.tile_price is not None:
            await store.set_tile_price(project_id, user, body.tile_price or None)
        if body.joint_mm is not None:
            await store.set_tile_joint(project_id, user, body.joint_mm)

        _, result = await computed(project_id, user)
        return _result_json(result)

    # --- виды работ (объект = замеры + несколько работ) -----------------------

    async def _object_measures(project: Project) -> dict:
        """Замеры объекта; для старых объектов (до колонки) — вывести из плитки."""
        m = project.measures
        if m.get("walls") or m.get("floor_m2"):
            return m
        if not project.surfaces:
            return {}
        walls, height, floor = [], 0.0, 0.0
        for row in project.surfaces:
            s = payload_to_surface(row.dump()).surface
            if s.kind is SurfaceKind.WALL:
                walls.append(round(s.width_mm / 1000, 3))
                height = round(s.height_mm / 1000, 3)
            else:
                floor = round(s.gross_area_m2, 2)
        return {"walls": walls, "height_m": height, "floor_m2": floor}

    async def _object_json(project: Project, user_id: int) -> dict:
        measures = await _object_measures(project)
        record = await store.get_or_create_user(user_id)
        works = []
        # Плитка — синтетическая работа из существующих поверхностей (ядро плитки).
        if project.surfaces:
            res = compute_project([payload_to_surface(r.dump()) for r in project.surfaces])
            est = build_estimate(
                project.title, res.layouts, res.materials, record.price,
                include_materials_cost=False,
            )
            works.append({
                "id": "tile", "kind": "tile", "name": "Плитка", "input": {},
                "hero_value": f"{res.area_m2:.2f} м²", "hero_note": f"{res.tiles_grid} плиток",
                "work_sum": est.works_total,
            })
        # Остальные работы — из WorkRow.
        for w in project.works:
            r = compute_work(w.kind, w.dump(), measures, record.price)
            works.append({
                "id": w.id, "kind": w.kind, "name": WORK_NAME.get(w.kind, w.kind),
                "input": w.dump(), "hero_value": r.hero_value, "hero_note": r.hero_note,
                "work_sum": r.work_sum,
            })
        return {
            **_project_brief(project),
            "measures": measures,
            "works": works,
            "total": sum(w["work_sum"] for w in works),
        }

    def _work_detail(w, measures: dict, price: PriceList) -> dict:
        r = compute_work(w.kind, w.dump(), measures, price)
        return {
            "id": w.id, "kind": w.kind, "name": WORK_NAME.get(w.kind, w.kind),
            "input": w.dump(), "hero_value": r.hero_value, "hero_note": r.hero_note,
            "work_sum": r.work_sum,
            "work_lines": [
                {"name": ln.name, "qty": ln.qty, "unit": ln.unit,
                 "total": ln.total, "total_text": money(ln.total)}
                for ln in r.work_lines
            ],
            "materials": [
                {"name": m.name, "qty_text": m.format_qty(), "unit": m.unit, "note": m.note}
                for m in r.materials
            ],
        }

    @app.get("/api/objects/{project_id}")
    async def get_object(project_id: int, user: User) -> dict:
        return await _object_json(await owned(project_id, user), user)

    @app.post("/api/objects/{project_id}/works", status_code=201)
    async def add_work(project_id: int, body: WorkCreateIn, user: User) -> dict:
        project = await owned(project_id, user)
        if body.kind not in {k.value for k in WorkKind} or body.kind == "tile":
            raise HTTPException(status_code=422, detail="Неизвестный вид работ.")
        measures = await _object_measures(project)
        wid = await store.add_work(project_id, user, body.kind, default_input(body.kind, measures))
        if wid is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        work = await store.get_work(wid, user)
        return _work_detail(work, measures, (await store.get_or_create_user(user)).price)

    @app.patch("/api/objects/{project_id}/works/{work_id}")
    async def patch_work(project_id: int, work_id: int, body: WorkPatchIn, user: User) -> dict:
        work = await store.get_work(work_id, user)
        if work is None or work.project_id != project_id:
            raise HTTPException(status_code=404, detail="Работа не найдена.")
        merged = {**work.dump(), **body.input}
        await store.update_work(work_id, user, merged)
        project = await owned(project_id, user)
        fresh = await store.get_work(work_id, user)
        return _work_detail(fresh, await _object_measures(project),
                            (await store.get_or_create_user(user)).price)

    @app.delete("/api/objects/{project_id}/works/{work_id}")
    async def delete_work(project_id: int, work_id: int, user: User) -> dict:
        if not await store.delete_work(work_id, user):
            raise HTTPException(status_code=404, detail="Работа не найдена.")
        return {"ok": True}

    # --- схемы ----------------------------------------------------------------

    @app.get("/api/projects/{project_id}/scheme/{index}.png")
    async def scheme(project_id: int, index: int, user: User) -> Response:
        project, result = await computed(project_id, user)
        if not 0 <= index < len(result.layouts):
            raise HTTPException(status_code=404, detail="Такой поверхности нет.")

        layout = result.layouts[index]
        png = render_layout(
            layout,
            title=f"{layout.surface.name} — {project.title}".strip(" —"),
            tile_photo=await _tile_photo(result.head.tile_photo_id),
            grout=result.head.grout,
        )
        # Схема пересчитывается на каждый чих (сменил раскладку — другая картинка),
        # поэтому кэшировать её нельзя: мастер увидит прошлую.
        return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})

    async def _tile_photo(file_id: str | None) -> Image.Image | None:
        """Фото плитки из Telegram. Не отдалось — рисуем как раньше, серыми."""
        if not file_id:
            return None
        from aiogram import Bot

        bot = Bot(token=settings.bot_token)
        try:
            buf = io.BytesIO()
            await bot.download(file_id, destination=buf)
            buf.seek(0)
            return Image.open(buf).convert("RGB")
        except Exception:
            logger.exception("miniapp: не смог скачать фото плитки %s", file_id)
            return None
        finally:
            await bot.session.close()

    # --- смета и акт ----------------------------------------------------------

    @app.get("/api/projects/{project_id}/estimate")
    async def estimate(project_id: int, user: User) -> dict:
        return await _paper(project_id, user, include_materials_cost=False)

    @app.get("/api/projects/{project_id}/act")
    async def act(project_id: int, user: User) -> dict:
        return await _paper(project_id, user, include_materials_cost=True)

    async def _paper(project_id: int, user_id: int, *, include_materials_cost: bool) -> dict:
        project, result = await computed(project_id, user_id)
        record = await store.get_or_create_user(user_id)
        saved_all = [payload_to_surface(r.dump()) for r in project.surfaces]

        est = build_estimate(
            project.title,
            result.layouts,
            result.materials,
            record.price,
            waterproofing=any(s.waterproofing for s in saved_all),
            grout_kind=saved_all[-1].grout_kind,
            include_materials_cost=include_materials_cost,
        )
        return _estimate_json(est, price=record.price)

    # --- прайс, деньги --------------------------------------------------------

    @app.put("/api/price")
    async def set_price(body: dict, user: User) -> dict:
        record = await store.get_or_create_user(user)
        current = asdict(record.price)
        unknown = set(body) - set(current)
        if unknown:
            raise HTTPException(status_code=422, detail=f"Нет таких строк прайса: {unknown}")
        record.price = PriceList(**{**current, **{k: float(v) for k, v in body.items()}})
        await store.save_user(record)
        return asdict(record.price)

    @app.put("/api/me")
    async def set_me(body: MasterIn, user: User) -> dict:
        record = await store.get_or_create_user(user)
        record.name = body.name[:128]
        record.phone = body.phone[:32]
        await store.save_user(record)
        return {"name": record.name, "phone": record.phone}

    @app.put("/api/projects/{project_id}/title")
    async def rename(project_id: int, body: TitleIn, user: User) -> dict:
        if not await store.rename_project(project_id, user, body.title):
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return _project_brief(await owned(project_id, user))

    @app.put("/api/projects/{project_id}/deal")
    async def set_deal(project_id: int, body: AmountIn, user: User) -> dict:
        if not await store.set_deal_amount(project_id, user, body.amount):
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return _project_brief(await owned(project_id, user))

    @app.post("/api/projects/{project_id}/payments", status_code=201)
    async def add_payment(project_id: int, body: PaymentIn, user: User) -> dict:
        if not await store.add_payment(project_id, user, body.amount, body.comment):
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return _project_brief(await owned(project_id, user))

    # --- статика --------------------------------------------------------------

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        # Фронт показывает detail как есть — там человеческий текст, а не код.
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    if STATIC.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC), name="static")

        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(STATIC / "index.html")

    return app


def _wrap_ok(result: ProjectResult, pattern: LayoutPattern) -> bool:
    """Лента бывает только у комнаты и только на прямых раскладках."""
    return len(result.walls) >= 2 and supports_wrap(pattern)


# --- сериализация -------------------------------------------------------------


def _project_brief(project: Project) -> dict:
    return {
        "id": project.id,
        "title": project.title,
        "surfaces": len(project.surfaces),
        "photos": len(project.photos),
        "deal_amount": project.deal_amount,
        "paid": project.paid,
        "due": project.due,
        "payments": [
            {"amount": p.amount, "comment": p.comment, "at": p.created_at.isoformat()}
            for p in sorted(project.payments, key=lambda p: p.created_at)
        ],
    }


def _line_json(line: MaterialLine) -> dict:
    return {
        "name": line.name,
        "qty": line.qty,
        "qty_text": line.format_qty(),
        "unit": line.unit,
        "note": line.note,
        "kind": line.kind,
    }


def _result_json(result: ProjectResult) -> dict:
    """Ровно те числа, которые бот пишет в сводку — только без HTML вокруг них."""
    tile = result.tile
    savings = result.savings
    return {
        "area_m2": round(result.area_m2, 2),
        "tiles_grid": result.tiles_grid,
        "cuts_count": result.cuts_count,
        "walls": len(result.walls),
        "has_floor": result.has_floor,
        "can_wrap": result.can_wrap,
        "wrap": result.head.wrap,
        "pattern": result.head.pattern.value,
        "start_from": result.head.start_from.value,
        "offset_ratio": result.head.offset_ratio,
        "grout": result.head.grout,
        "grout_kind": result.head.grout_kind.value,
        "waste": result.head.waste if result.head.waste is not None else WASTE_BY_PATTERN[
            result.head.pattern
        ],
        "waterproofing": result.head.waterproofing,
        "tile_locked": result.head.tile_locked,
        "tile_photo": bool(result.head.tile_photo_id),
        "tile": {
            "width_mm": tile.width_mm,
            "height_mm": tile.height_mm,
            "joint_mm": tile.joint_mm,
            "joint_text": fmt_mm(tile.joint_mm),
            "thickness_mm": tile.thickness_mm,
            "per_pack": tile.per_pack,
            "price_per_m2": tile.price_per_m2,
            # Как плитка легла — не то же, что мастер ввёл: ориентацию подбирает бот.
            "lying": tile.width_mm >= tile.height_mm,
        },
        "tile_cost": result.tile_cost,
        "surfaces": [
            {
                "index": i,
                "name": lay.surface.name,
                "kind": lay.surface.kind.value,
                "area_m2": round(lay.surface.net_area_m2, 2),
                "tiles": lay.tiles_grid,
                "cuts": lay.cuts_count,
                "tile_w": lay.tile.width_mm,
                "tile_h": lay.tile.height_mm,
                "openings": [o.name for o in lay.surface.openings],
            }
            for i, lay in enumerate(result.layouts)
        ],
        "purchase": [_line_json(line) for line in result.purchase],
        "advice": result.advice,
        "savings": {"tiles": savings.tiles, "packs": savings.packs} if savings else None,
    }


def _estimate_json(est: Estimate, *, price: PriceList) -> dict:
    materials = []
    for m in est.materials:
        line = _line_json(m)
        line["cost"] = est.rough_costs.get(m.name) or est.material_costs.get(m.name)
        # Плитку продают пачками, хотя цену пишут за м²: нужна 21.5 пачки — берёшь
        # 22 и платишь за все.
        line["packs"] = (
            math.ceil(m.qty / m.per_pack) if m.kind == "tile" and m.per_pack else None
        )
        materials.append(line)

    return {
        "title": est.title,
        "works": [
            {
                "name": w.name,
                "qty": round(w.qty, 2),
                "unit": w.unit,
                "price": w.price,
                "total": w.total,
                "total_text": money(w.total),
            }
            for w in est.works
        ],
        "works_total": est.works_total,
        "works_total_text": money(est.works_total),
        "materials": materials,
        "materials_total": est.materials_total,
        "rough_materials_total": est.rough_materials_total,
        "rough_total": est.rough_total,
        "rough_total_text": money(est.rough_total),
        "grand_total": est.grand_total,
        "grand_total_text": money(est.grand_total),
        "note": est.note,
        "price": asdict(price),
    }


# --- то, что присылает фронт --------------------------------------------------


class TitleIn(BaseModel):
    title: str = Field(min_length=1, max_length=128)


class TileIn(BaseModel):
    width_mm: float = Field(gt=0, le=3000)
    height_mm: float = Field(gt=0, le=3000)
    joint_mm: float = Field(default=2.0, ge=0, le=20)
    thickness_mm: float = Field(default=9.0, gt=0, le=40)
    per_pack: int | None = Field(default=None, gt=0, le=500)

    def to_tile(self) -> Tile:
        return Tile(
            width_mm=self.width_mm,
            height_mm=self.height_mm,
            joint_mm=self.joint_mm,
            thickness_mm=self.thickness_mm,
            per_pack=self.per_pack,
        )


class TilingIn(BaseModel):
    """Общее для «комнаты» и «одной поверхности»: чем и как кладём."""

    tile: TileIn
    floor_tile: TileIn | None = None
    pattern: str = LayoutPattern.STRAIGHT.value
    start_from: str = "auto"
    waste: float | None = Field(default=None, ge=0, le=1)
    waterproofing: bool = False


class RoomIn(TilingIn):
    walls_m: list[float] = Field(min_length=2, max_length=12)
    height_m: float = Field(gt=0, le=10)
    with_floor: bool = False


class SurfaceIn(TilingIn):
    kind: str = SurfaceKind.WALL.value
    width_m: float = Field(gt=0, le=50)
    height_m: float = Field(gt=0, le=10)


class OpeningIn(BaseModel):
    surface_id: int
    name: str = "проём"
    width_m: float = Field(gt=0, le=10)
    height_m: float = Field(gt=0, le=10)


class TileSizeIn(BaseModel):
    width_mm: float = Field(gt=0, le=3000)
    height_mm: float = Field(gt=0, le=3000)
    kind: str = SurfaceKind.WALL.value


class PatchIn(BaseModel):
    pattern: str | None = None
    start_from: str | None = None
    offset_label: str | None = None
    wrap: bool | None = None
    grout: str | None = None
    grout_kind: str | None = None
    waste: float | None = Field(default=None, ge=0, le=1)
    waterproofing: bool | None = None
    rotate: bool = False
    tile_size: TileSizeIn | None = None
    tile_price: float | None = Field(default=None, ge=0)
    joint_mm: float | None = Field(default=None, ge=0, le=20)


class WorkCreateIn(BaseModel):
    kind: str  # plaster/laminate/baseboard/reveals/plumbing


class WorkPatchIn(BaseModel):
    # Правка полей ввода работы — сливается в существующий input и пересчитывается.
    input: dict = Field(default_factory=dict)


class MeasureIn(BaseModel):
    """Сырой ввод мастера — разбирает его сервер, тем же парсером, что у бота."""

    kind: str = Field(pattern="^(walls|height|tile|size)$")
    text: str = Field(min_length=1, max_length=200)


class MasterIn(BaseModel):
    name: str = ""
    phone: str = ""


class AmountIn(BaseModel):
    amount: float = Field(ge=0)


class PaymentIn(BaseModel):
    amount: float = Field(gt=0)
    comment: str = ""
