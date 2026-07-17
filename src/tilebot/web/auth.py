"""Кто пришёл в miniapp: проверка Telegram initData.

Мини-апп присылает строку initData, подписанную Telegram нашим токеном бота.
Проверяем подпись и достаём id мастера. Верить `user.id` из тела запроса нельзя:
подставить чужой номер ничего не стоит — по нему открылись бы чужие объекты.

Протокол: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class InitDataError(Exception):
    """initData нет, он битый, подписан не нами или протух."""


def verify_init_data(init_data: str, bot_token: str, *, max_age_seconds: int = 86400) -> int:
    """Проверить initData и вернуть telegram id мастера.

    max_age_seconds отсекает переигранный старый запрос: сутки — столько живёт
    открытая вкладка мини-аппа.
    """
    if not init_data:
        raise InitDataError("пустой initData")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataError("в initData нет подписи")

    # Строка проверки: все оставшиеся поля key=value, отсортированные по ключу.
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    # compare_digest, а не ==: обычное сравнение строк выходит из цикла на первом
    # несовпавшем символе и по времени ответа подсказывает подпись по байту.
    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError("подпись не сходится")

    auth_date = pairs.get("auth_date")
    if auth_date and auth_date.isdigit() and time.time() - int(auth_date) > max_age_seconds:
        raise InitDataError("initData протух")

    user_raw = pairs.get("user")
    if not user_raw:
        raise InitDataError("в initData нет пользователя")
    try:
        return int(json.loads(user_raw)["id"])
    except (ValueError, KeyError, TypeError) as e:
        raise InitDataError("битый пользователь в initData") from e
