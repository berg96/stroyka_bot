"""Хранилище: объекты, поверхности, прайс мастера.

Смысл хранения — та самая боль из голосового: посчитал стену, записал на бумажку,
посчитал вторую, потом всё это суммируй. Здесь объект живёт, к нему можно
вернуться и досчитать стену завтра.
"""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload

from tilebot.core.estimate import PriceList
from tilebot.core.models import (
    DEFAULT_OFFSET,
    GroutKind,
    LayoutPattern,
    Opening,
    SavedSurface,
    StartFrom,
    Surface,
    SurfaceKind,
    Tile,
)

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    # Telegram id не влезает в INTEGER — только BigInteger.
    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    price_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    projects: Mapped[list["Project"]] = relationship(back_populates="user", lazy="selectin")

    @property
    def price(self) -> PriceList:
        return PriceList(**json.loads(self.price_json or "{}"))

    @price.setter
    def price(self, value: PriceList) -> None:
        self.price_json = json.dumps(value.__dict__)


class Project(Base):
    """Объект: «Ванная на Борзова»."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(128))
    # Сумма, о которой договорились с заказчиком. 0 — не договорились/не записал.
    deal_amount: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="projects")
    surfaces: Mapped[list["SurfaceRow"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )
    photos: Mapped[list["Photo"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def paid(self) -> float:
        return sum(p.amount for p in self.payments)

    @property
    def due(self) -> float:
        """Сколько заказчик ещё должен. Отрицательного долга не бывает — это переплата."""
        return max(0.0, self.deal_amount - self.paid)


class Payment(Base):
    """Приход по объекту: аванс, промежуточный платёж, расчёт.

    Форумы мастеров сходятся в одном: заказчик пропадает или «забывает» доплатить.
    Записанный аванс и остаток — это то, что мастер иначе держит в голове.
    """

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    amount: Mapped[float] = mapped_column(Float)
    comment: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="payments")


class Photo(Base):
    """Фото объекта: основание «до», процесс, результат.

    Храним file_id — файл лежит у Telegram, качать и хранить его самим незачем.
    """

    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    file_id: Mapped[str] = mapped_column(String(256))
    caption: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="photos")


class SurfaceRow(Base):
    """Поверхность с плиткой и параметрами раскладки — всё, чтобы пересчитать заново."""

    __tablename__ = "surfaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    payload_json: Mapped[str] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="surfaces")

    def dump(self) -> dict:
        return json.loads(self.payload_json)


def surface_to_payload(
    surface: Surface,
    tile: Tile,
    pattern: LayoutPattern,
    start_from: StartFrom,
    *,
    waterproofing: bool,
    waste: float | None = None,
    tile_photo_id: str | None = None,
    grout: str | None = None,
    tile_locked: bool = False,
    grout_kind: str = GroutKind.CEMENT.value,
    offset_ratio: float = DEFAULT_OFFSET,
    wrap: bool = False,
) -> str:
    return json.dumps(
        {
            "surface": {
                "name": surface.name,
                "width_mm": surface.width_mm,
                "height_mm": surface.height_mm,
                "kind": surface.kind.value,
                "openings": [
                    {
                        "name": o.name,
                        "width_mm": o.width_mm,
                        "height_mm": o.height_mm,
                        "x_mm": o.x_mm,
                        "y_mm": o.y_mm,
                    }
                    for o in surface.openings
                ],
            },
            "tile": {
                "width_mm": tile.width_mm,
                "height_mm": tile.height_mm,
                "thickness_mm": tile.thickness_mm,
                "joint_mm": tile.joint_mm,
                "per_pack": tile.per_pack,
                "price_per_m2": tile.price_per_m2,
            },
            "pattern": pattern.value,
            "start_from": start_from.value,
            "waterproofing": waterproofing,
            "waste": waste,
            # Фото самой плитки (file_id) и цвет затирки — чтобы схема показывала
            # не серые квадратики, а то, что мастер реально купил.
            "tile_photo_id": tile_photo_id,
            "grout": grout,
            "grout_kind": grout_kind,
            "offset_ratio": offset_ratio,
            # Эконом-раскладка: стены кладутся одной лентой по кругу, остаток
            # плитки заворачивает за угол вместо мусорки.
            "wrap": wrap,
            # Мастер повернул плитку сам — больше её не вертим, как бы ни хотелось
            # ради подрезки: как она лежит, решает он.
            "tile_locked": tile_locked,
        },
        ensure_ascii=False,
    )


def payload_to_surface(data: dict) -> SavedSurface:
    s = data["surface"]
    t = data["tile"]
    surface = Surface(
        name=s["name"],
        width_mm=s["width_mm"],
        height_mm=s["height_mm"],
        kind=SurfaceKind(s["kind"]),
        openings=[Opening(**o) for o in s.get("openings", [])],
    )
    return SavedSurface(
        surface=surface,
        tile=Tile(**t),
        pattern=LayoutPattern(data["pattern"]),
        start_from=StartFrom(data["start_from"]),
        waterproofing=bool(data.get("waterproofing", False)),
        waste=data.get("waste"),
        tile_photo_id=data.get("tile_photo_id"),
        grout=data.get("grout"),
        tile_locked=bool(data.get("tile_locked", False)),
        grout_kind=GroutKind(data.get("grout_kind", GroutKind.CEMENT.value)),
        offset_ratio=float(data.get("offset_ratio") or DEFAULT_OFFSET),
        wrap=bool(data.get("wrap", False)),
    )


class Storage:
    def __init__(self, db_path: str) -> None:
        self._engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
        self._session = async_sessionmaker(self._engine, expire_on_commit=False)

    async def init(self) -> None:
        async with self._engine.begin() as conn:
            # Новые таблицы создаются сами, а вот колонку в уже существующую таблицу
            # create_all не добавит — накатываем такие правки руками.
            await conn.run_sync(Base.metadata.create_all)

            existing = await conn.execute(text("PRAGMA table_info(projects)"))
            columns = {row[1] for row in existing}
            if "deal_amount" not in columns:
                await conn.execute(
                    text("ALTER TABLE projects ADD COLUMN deal_amount FLOAT DEFAULT 0.0")
                )
                logger.info("Миграция: projects.deal_amount добавлена")

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._session() as s:
            yield s

    async def get_or_create_user(self, tg_id: int) -> User:
        async with self.session() as s:
            user = await s.get(User, tg_id)
            if user is None:
                user = User(tg_id=tg_id, price_json=json.dumps(PriceList().__dict__))
                s.add(user)
                await s.commit()
            return user

    async def save_user(self, user: User) -> None:
        async with self.session() as s:
            await s.merge(user)
            await s.commit()

    async def create_project(self, tg_id: int, title: str) -> Project:
        await self.get_or_create_user(tg_id)
        async with self.session() as s:
            project = Project(user_id=tg_id, title=title)
            s.add(project)
            await s.commit()
            await s.refresh(project)
            return project

    async def add_surface(self, project_id: int, tg_id: int, payload: str) -> bool:
        if not await self.owns(project_id, tg_id):
            return False
        async with self.session() as s:
            s.add(SurfaceRow(project_id=project_id, payload_json=payload))
            await s.commit()
        return True

    async def update_project_surfaces(self, project_id: int, tg_id: int, **changes: Any) -> bool:
        """Поправить поле во всех поверхностях объекта разом.

        Плитка, раскладка и затирка — свойства объекта, а не отдельной стены: их
        меняют для всей комнаты сразу.
        """
        if not await self.owns(project_id, tg_id):
            return False
        async with self.session() as s:
            result = await s.execute(select(SurfaceRow).where(SurfaceRow.project_id == project_id))
            for row in result.scalars():
                data = json.loads(row.payload_json)
                data.update(changes)
                row.payload_json = json.dumps(data, ensure_ascii=False)
            await s.commit()
        return True

    async def set_project_pattern(self, project_id: int, tg_id: int, pattern: str) -> bool:
        """Переложить весь объект другой раскладкой.

        Запас сбрасываем в None: под диагональ нужен свой, а прежний выбор был
        сделан под другую раскладку.
        """
        return await self.update_project_surfaces(
            project_id, tg_id, pattern=pattern, waste=None
        )

    async def set_tile_price(self, project_id: int, tg_id: int, price: float | None) -> bool:
        """Цена плитки за м² — только если мастер закупается сам и сам попросил.

        Лежит внутри плитки, поэтому отдельным методом: update_project_surfaces
        правит верхний уровень payload.
        """
        if not await self.owns(project_id, tg_id):
            return False
        async with self.session() as s:
            result = await s.execute(select(SurfaceRow).where(SurfaceRow.project_id == project_id))
            for row in result.scalars():
                data = json.loads(row.payload_json)
                data["tile"]["price_per_m2"] = price
                row.payload_json = json.dumps(data, ensure_ascii=False)
            await s.commit()
        return True

    async def rotate_tile(self, project_id: int, tg_id: int) -> bool:
        """Положить плитку на бок во всём объекте и запомнить, что так решил мастер."""
        if not await self.owns(project_id, tg_id):
            return False
        async with self.session() as s:
            result = await s.execute(select(SurfaceRow).where(SurfaceRow.project_id == project_id))
            for row in result.scalars():
                data = json.loads(row.payload_json)
                tile = data["tile"]
                tile["width_mm"], tile["height_mm"] = tile["height_mm"], tile["width_mm"]
                data["tile_locked"] = True
                row.payload_json = json.dumps(data, ensure_ascii=False)
            await s.commit()
        return True

    async def set_tile_size(
        self, project_id: int, tg_id: int, width_mm: float, height_mm: float, *, kind: str
    ) -> bool:
        """Сменить размер плитки на стенах или на полу и пересчитать по ним.

        Мастеру нужно быстро прикинуть «а если взять другую плитку» — не пересоздавая
        объект и не вводя заново все замеры.
        """
        if not await self.owns(project_id, tg_id):
            return False
        async with self.session() as s:
            result = await s.execute(select(SurfaceRow).where(SurfaceRow.project_id == project_id))
            for row in result.scalars():
                data = json.loads(row.payload_json)
                if data["surface"]["kind"] != kind:
                    continue
                data["tile"]["width_mm"] = width_mm
                data["tile"]["height_mm"] = height_mm
                # Размер сменили — прежний ручной поворот к новой плитке отношения
                # не имеет, пусть бот снова подберёт ориентацию.
                data["tile_locked"] = False
                row.payload_json = json.dumps(data, ensure_ascii=False)
            await s.commit()
        return True

    async def set_tile_joint(self, project_id: int, tg_id: int, joint_mm: float) -> bool:
        """Сменить ширину шва во всём объекте и пересчитать.

        Шов — свойство объекта, а не отдельной стены: его меняют для всей комнаты
        сразу, как раскладку. Внутри плитки, поэтому отдельным методом.
        """
        if not await self.owns(project_id, tg_id):
            return False
        async with self.session() as s:
            result = await s.execute(select(SurfaceRow).where(SurfaceRow.project_id == project_id))
            for row in result.scalars():
                data = json.loads(row.payload_json)
                data["tile"]["joint_mm"] = joint_mm
                row.payload_json = json.dumps(data, ensure_ascii=False)
            await s.commit()
        return True

    async def get_surface(self, surface_id: int, tg_id: int) -> SurfaceRow | None:
        """Поверхность по id — только внутри объекта этого мастера."""
        async with self.session() as s:
            result = await s.execute(
                select(SurfaceRow)
                .join(Project, SurfaceRow.project_id == Project.id)
                .where(SurfaceRow.id == surface_id, Project.user_id == tg_id)
            )
            return result.scalar_one_or_none()

    async def update_surface(self, surface_id: int, tg_id: int, payload: str) -> bool:
        async with self.session() as s:
            result = await s.execute(
                select(SurfaceRow)
                .join(Project, SurfaceRow.project_id == Project.id)
                .where(SurfaceRow.id == surface_id, Project.user_id == tg_id)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return False
            row.payload_json = payload
            await s.commit()
        return True

    _LOADED = (
        selectinload(Project.surfaces),
        selectinload(Project.payments),
        selectinload(Project.photos),
    )

    async def get_project(self, project_id: int, tg_id: int) -> Project | None:
        """Объект по id — только если он принадлежит этому мастеру.

        project_id приходит из callback_data, то есть из клиента: чужой номер
        подставить ничего не стоит. Поэтому владельца проверяем в самом запросе, а
        не полагаемся на то, что кнопку с чужим объектом никому не присылали.
        """
        async with self.session() as s:
            result = await s.execute(
                select(Project)
                .where(Project.id == project_id, Project.user_id == tg_id)
                .options(*self._LOADED)
            )
            return result.scalar_one_or_none()

    async def owns(self, project_id: int, tg_id: int) -> bool:
        async with self.session() as s:
            result = await s.execute(
                select(Project.id).where(Project.id == project_id, Project.user_id == tg_id)
            )
            return result.scalar_one_or_none() is not None

    async def list_projects(self, tg_id: int, limit: int = 10) -> list[Project]:
        async with self.session() as s:
            result = await s.execute(
                select(Project)
                .where(Project.user_id == tg_id)
                # id вторым ключом: created_at в sqlite с точностью до секунды, и
                # два объекта, заведённых подряд, иначе встают в случайном порядке.
                .order_by(Project.created_at.desc(), Project.id.desc())
                .limit(limit)
                .options(*self._LOADED)
            )
            return list(result.scalars())

    async def set_deal_amount(self, project_id: int, tg_id: int, amount: float) -> bool:
        async with self.session() as s:
            project = await s.get(Project, project_id)
            if project is None or project.user_id != tg_id:
                return False
            project.deal_amount = amount
            await s.commit()
        return True

    async def add_payment(
        self, project_id: int, tg_id: int, amount: float, comment: str = ""
    ) -> bool:
        if not await self.owns(project_id, tg_id):
            return False
        async with self.session() as s:
            s.add(Payment(project_id=project_id, amount=amount, comment=comment[:128]))
            await s.commit()
        return True

    async def add_photo(
        self, project_id: int, tg_id: int, file_id: str, caption: str = ""
    ) -> bool:
        if not await self.owns(project_id, tg_id):
            return False
        async with self.session() as s:
            s.add(Photo(project_id=project_id, file_id=file_id, caption=caption[:200]))
            await s.commit()
        return True

    async def delete_project(self, project_id: int, tg_id: int) -> bool:
        async with self.session() as s:
            project = await s.get(Project, project_id)
            if project is None or project.user_id != tg_id:
                return False
            await s.delete(project)
            await s.commit()
        return True
