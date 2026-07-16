"""Бот без Telegram: диспетчер, поддельная сессия и хелперы «нажать кнопку».

Ядро считает плитку правильно и покрыто отдельно, а ломается обычно проводка:
FSM-переход, callback_data, не та клавиатура. Гонять ради этого живой Telegram
долго и завязано на прод, поэтому сессию бота подменяем и кормим диспетчер
апдейтами напрямую — те же хендлеры, тот же роутинг, только без сети.
"""

from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, InlineKeyboardMarkup, Update
from aiogram.types import Message as TgMessage
from aiogram.types import User as TgUser

from tilebot.bot.handlers import area, tiling
from tilebot.storage import Storage

SASHA = 383853880
CHAT = Chat(id=SASHA, type="private")
USER = TgUser(id=SASHA, is_bot=False, first_name="Саня")


class FakeSession(BaseSession):
    """Ничего не отправляет — просто записывает, что бот хотел послать."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[TelegramMethod[Any]] = []
        self._counter = 1000

    async def close(self) -> None:
        pass

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes, None]:
        yield b""

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int = 60) -> Any:
        self.sent.append(method)
        name = type(method).__name__

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
        """callback_data кнопки — ищем с конца, по последним клавиатурам."""
        for method in reversed(self.session.sent):
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

    def forget(self) -> None:
        """Забыть переписку — чтобы проверять только то, что после этой точки."""
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
    for router in (tiling.router, area.router):
        router._parent_router = None
        dp.include_router(router)

    @dp.update.middleware()
    async def inject_storage(handler, event, data):
        data["storage"] = storage
        return await handler(event, data)

    return BotHarness(bot, dp, session)
