"""Хранилище: объекты, поверхности, прайс мастера.

Смысл хранения — та самая боль из голосового: посчитал стену, записал на бумажку,
посчитал вторую, потом всё это суммируй. Здесь объект живёт, к нему можно
вернуться и досчитать стену завтра.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload

from tilebot.core.estimate import PriceList
from tilebot.core.models import LayoutPattern, Opening, StartFrom, Surface, SurfaceKind, Tile


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="projects")
    surfaces: Mapped[list["SurfaceRow"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )


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
        },
        ensure_ascii=False,
    )


def payload_to_surface(data: dict) -> tuple[Surface, Tile, LayoutPattern, StartFrom, bool]:
    s = data["surface"]
    t = data["tile"]
    surface = Surface(
        name=s["name"],
        width_mm=s["width_mm"],
        height_mm=s["height_mm"],
        kind=SurfaceKind(s["kind"]),
        openings=[Opening(**o) for o in s.get("openings", [])],
    )
    tile = Tile(**t)
    return (
        surface,
        tile,
        LayoutPattern(data["pattern"]),
        StartFrom(data["start_from"]),
        bool(data.get("waterproofing", False)),
    )


class Storage:
    def __init__(self, db_path: str) -> None:
        self._engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
        self._session = async_sessionmaker(self._engine, expire_on_commit=False)

    async def init(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

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

    async def add_surface(self, project_id: int, payload: str) -> None:
        async with self.session() as s:
            s.add(SurfaceRow(project_id=project_id, payload_json=payload))
            await s.commit()

    async def get_project(self, project_id: int) -> Project | None:
        async with self.session() as s:
            result = await s.execute(
                select(Project)
                .where(Project.id == project_id)
                .options(selectinload(Project.surfaces))
            )
            return result.scalar_one_or_none()

    async def list_projects(self, tg_id: int, limit: int = 10) -> list[Project]:
        async with self.session() as s:
            result = await s.execute(
                select(Project)
                .where(Project.user_id == tg_id)
                .order_by(Project.created_at.desc())
                .limit(limit)
                .options(selectinload(Project.surfaces))
            )
            return list(result.scalars())

    async def delete_project(self, project_id: int) -> None:
        async with self.session() as s:
            project = await s.get(Project, project_id)
            if project:
                await s.delete(project)
                await s.commit()
