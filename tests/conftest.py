"""Бот без Telegram: диспетчер, поддельная сессия и хелперы «нажать кнопку».

Ядро считает плитку правильно и покрыто отдельно, а ломается обычно проводка:
FSM-переход, callback_data, не та клавиатура. Гонять ради этого живой Telegram
долго и завязано на прод, поэтому сессию бота подменяем и кормим диспетчер
апдейтами напрямую — те же хендлеры, тот же роутинг, только без сети.
"""

import io
import re
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, File, InlineKeyboardMarkup, PhotoSize, Update
from aiogram.types import Message as TgMessage
from aiogram.types import User as TgUser
from PIL import Image, ImageDraw

from tilebot.bot.handlers import area, price, projects, start, tiling
from tilebot.storage import Storage

SASHA = 383853880
CHAT = Chat(id=SASHA, type="private")
USER = TgUser(id=SASHA, is_bot=False, first_name="Саня")


def sample_tile_photo() -> bytes:
    """«Фото плитки», которое мастер прислал из магазина."""
    image = Image.new("RGB", (600, 300), (58, 62, 68))
    draw = ImageDraw.Draw(image)
    for x in range(0, 600, 40):
        draw.line([(x, 0), (x - 100, 300)], fill=(96, 102, 110), width=3)
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


class FakeSession(BaseSession):
    """Ничего не отправляет — просто записывает, что бот хотел послать."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[TelegramMethod[Any]] = []
        self._counter = 1000
        self.file_bytes = sample_tile_photo()

    async def close(self) -> None:
        pass

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes, None]:
        # Отдаём картинку: иначе фото плитки не проверить — рендер молча
        # откатится на серые квадратики, и тест этого не заметит.
        yield self.file_bytes

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int = 60) -> Any:
        self.sent.append(method)
        name = type(method).__name__

        if name == "GetFile":
            return File(file_id=method.file_id, file_unique_id="u", file_path="tile.jpg")
        if name == "SendMediaGroup":
            return [self._message() for _ in method.media]
        if name.startswith("Send") or name.startswith("Edit"):
            return self._message(
                text=getattr(method, "text", None) or getattr(method, "caption", None),
                markup=getattr(method, "reply_markup", None),
            )
        return True

    def _message(
        self, text: str | None = None, markup: InlineKeyboardMarkup | None = None
    ) -> TgMessage:
        self._counter += 1
        return TgMessage(
            message_id=self._counter,
            date=datetime(2026, 7, 16, 12, 0),
            chat=CHAT,
            text=text,
            reply_markup=markup if isinstance(markup, InlineKeyboardMarkup) else None,
        )


class BotHarness:
    """Диалог с ботом: пишем текст, жмём кнопки, читаем, что он ответил."""

    def __init__(self, bot: Bot, dp: Dispatcher, session: FakeSession) -> None:
        self.bot = bot
        self.dp = dp
        self.session = session
        self._update_id = 0
        self._message_id = 0
        # Клавиатуры, отправленные до forget(): в чате они никуда не делись, и
        # мастер может нажать их и позже.
        self._offscreen: list[TelegramMethod[Any]] = []

    def _next_update(self) -> int:
        self._update_id += 1
        return self._update_id

    async def send(self, text: str) -> None:
        """Мастер написал сообщение."""
        self._message_id += 1
        message = TgMessage(
            message_id=self._message_id,
            date=datetime(2026, 7, 16, 12, 0),
            chat=CHAT,
            from_user=USER,
            text=text,
        )
        await self.dp.feed_update(
            self.bot, Update(update_id=self._next_update(), message=message)
        )

    async def send_photo(self) -> None:
        """Мастер прислал фото плитки."""
        self._message_id += 1
        photo = PhotoSize(file_id="tilephoto1", file_unique_id="u1", width=600, height=300)
        message = TgMessage(
            message_id=self._message_id,
            date=datetime(2026, 7, 16, 12, 0),
            chat=CHAT,
            from_user=USER,
            photo=[photo],
        )
        await self.dp.feed_update(
            self.bot, Update(update_id=self._next_update(), message=message)
        )

    async def click(self, title: str) -> None:
        """Мастер нажал кнопку с таким текстом на последней клавиатуре."""
        data = self.find_button(title)
        assert data is not None, f"кнопки «{title}» нет. Последнее: {self.last_markup_titles()}"
        await self.click_data(data)

    async def click_data(self, callback_data: str) -> None:
        from aiogram.types import CallbackQuery

        self._message_id += 1
        carrier = TgMessage(
            message_id=self._message_id,
            date=datetime(2026, 7, 16, 12, 0),
            chat=CHAT,
            from_user=USER,
        )
        call = CallbackQuery(
            id=f"cb{self._update_id}",
            from_user=USER,
            chat_instance="1",
            message=carrier,
            data=callback_data,
        )
        await self.dp.feed_update(
            self.bot, Update(update_id=self._next_update(), callback_query=call)
        )

    # --- что бот ответил ---

    @property
    def texts(self) -> list[str]:
        out = []
        for method in self.session.sent:
            text = getattr(method, "text", None) or getattr(method, "caption", None)
            if text:
                out.append(text)
        return out

    @property
    def last_text(self) -> str:
        assert self.texts, "бот ничего не написал"
        return self.texts[-1]

    def said(self, fragment: str) -> bool:
        return any(fragment in t for t in self.texts)

    def find_button(self, title: str) -> str | None:
        """callback_data кнопки — ищем с конца, по всем клавиатурам, что бот прислал."""
        for method in reversed([*self._offscreen, *self.session.sent]):
            markup = getattr(method, "reply_markup", None)
            if not isinstance(markup, InlineKeyboardMarkup):
                continue
            for row in markup.inline_keyboard:
                for button in row:
                    if title in button.text:
                        return button.callback_data
        return None

    def last_markup_titles(self) -> list[str]:
        for method in reversed(self.session.sent):
            markup = getattr(method, "reply_markup", None)
            if isinstance(markup, InlineKeyboardMarkup):
                return [b.text for row in markup.inline_keyboard for b in row]
        return []

    def photos_sent(self) -> int:
        count = 0
        for method in self.session.sent:
            name = type(method).__name__
            if name == "SendPhoto":
                count += 1
            elif name == "SendMediaGroup":
                count += len(method.media)
        return count

    def downloaded_files(self) -> list[str]:
        """Какие файлы бот забирал из Telegram — доказательство, что фото пошло в схему."""
        return [
            m.file_id for m in self.session.sent if type(m).__name__ == "GetFile"
        ]

    def forget(self) -> None:
        """Забыть сказанное — чтобы проверять только то, что бот ответил дальше.

        Кнопки при этом остаются доступными: в чате они на экране и после.
        """
        self._offscreen.extend(self.session.sent)
        self.session.sent.clear()


@pytest.fixture
async def storage(tmp_path):
    s = Storage(str(tmp_path / "bot.sqlite3"))
    await s.init()
    return s


@pytest.fixture
async def app(storage) -> BotHarness:
    session = FakeSession()
    bot = Bot(token="42:TEST", session=session)

    dp = Dispatcher()
    # Роутеры живут в модулях, то есть одни и те же на весь прогон, а Dispatcher
    # у каждого теста свой — отвязываем от прошлого, иначе include_router ругнётся.
    for router in (start.router, tiling.router, area.router, projects.router, price.router):
        router._parent_router = None
        dp.include_router(router)

    @dp.update.middleware()
    async def inject_storage(handler, event, data):
        data["storage"] = storage
        return await handler(event, data)

    return BotHarness(bot, dp, session)


# --- сценарии и разбор ответов, общие для тестов бота и мини-аппа ---------


async def _room_flow(app, *, floor_tile: str | None = "60 60") -> None:
    """Ванная целиком: 4 стены 60×30, на полу свой керамогранит 60×60."""
    await app.send("🧱 Плитка")
    await app.click("Комната целиком")
    await app.send("Ванная, Борзова")
    await app.send("2 1.8 2 1.8")
    await app.send("2.7")
    await app.click("Да, и пол")
    await app.send("60 30")
    await app.send("1,4")
    await app.click("9 мм")
    await app.send("8")  # штук в упаковке

    if floor_tile:
        await app.send(floor_tile)  # плитка на пол — своя
        await app.send("4")  # штук в упаковке напольной
    else:
        await app.click("Такая же, как на стены")

    await app.click("Вразбежку")
    await app.click("Как лучше")
    await app.click("7%")
    await app.click("Да, мокрая зона")


def _tile_qty(text: str) -> int:
    """Сколько плитки бот велел купить — из строки «• Плитка 600×300: 44 шт».

    Сводка выделяет количество жирным, а смета печатает его голым и с упаковками —
    строка одна и та же, оформление разное.
    """
    m = re.search(r"Плитка \d+×\d+: (?:<b>)?(\d+) шт", text)
    assert m, f"в сводке нет строки плитки:\n{text}"
    return int(m.group(1))


def _tile_qty_anywhere(texts: list[str]) -> int:
    """То же, но по всему, что бот наговорил: за сметой следом летит подпись к PDF."""
    for text in reversed(texts):
        if re.search(r"Плитка \d+×\d+: (?:<b>)?\d+ шт", text):
            return _tile_qty(text)
    raise AssertionError(f"строки плитки нет ни в одном сообщении:\n{texts}")
