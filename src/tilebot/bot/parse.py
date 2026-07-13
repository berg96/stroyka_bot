"""Разбор того, что мастер набирает одной рукой, стоя на объекте.

Он пишет «2.7 2.5», «2700x2500», «60х30» — и всё это должно просто работать.
Правило: число меньше 20 — это метры, иначе миллиметры. Стен по 20 метров и
плиток по 19 мм не бывает, так что двусмысленности нет.
"""

import re

METERS_THRESHOLD = 20.0
_SPLIT = re.compile(r"[\s,;xх*×/]+", re.IGNORECASE)
# Запятая работает и как десятичный знак («2,7»), и как разделитель («2.7, 2.5»).
# Отличаем по контексту: зажатая между цифрами — десятичная.
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")


class ParseError(ValueError):
    """Не разобрали ввод — надо переспросить."""


def _one(token: str) -> float:
    """Одно число. Ноль здесь допустим: это и координата у пола, и «не знаю»."""
    token = token.replace(",", ".").strip()
    try:
        return float(token)
    except ValueError as exc:
        raise ParseError(f"«{token}» — это не число.") from exc


def _positive(values: list[float]) -> list[float]:
    if any(v <= 0 for v in values):
        raise ParseError("Размер должен быть больше нуля.")
    return values


def to_mm(value: float) -> float:
    """Метры или миллиметры → миллиметры."""
    return value * 1000 if value < METERS_THRESHOLD else value


def numbers(text: str) -> list[float]:
    """Все числа из строки, как есть."""
    normalized = _DECIMAL_COMMA.sub(".", text.strip())
    tokens = [t for t in _SPLIT.split(normalized) if t]
    if not tokens:
        raise ParseError("Не вижу чисел.")
    return [_one(t) for t in tokens]


def dimensions(text: str, count: int = 2) -> list[float]:
    """Ровно count размеров в миллиметрах: «2.7 2.5» → [2700, 2500]."""
    values = numbers(text)
    if len(values) != count:
        raise ParseError(
            f"Нужно {count} числ{'о' if count == 1 else 'а'} через пробел, а вижу {len(values)}."
        )
    return [to_mm(v) for v in _positive(values)]


def meters(text: str, count: int | None = None) -> list[float]:
    """Длины в метрах — для замеров комнаты рулеткой."""
    values = numbers(text)
    if count is not None and len(values) != count:
        raise ParseError(f"Нужно {count} числа через пробел, а вижу {len(values)}.")
    return [to_mm(v) / 1000 for v in _positive(values)]


_LEADING_NAME = re.compile(r"^[^\d]*")


def name_and_numbers(line: str) -> tuple[str, list[float]]:
    """«минус короб 0.4 0.6» → ("минус короб", [0.4, 0.6]).

    Имя — всё до первого числа; дальше идут только размеры.
    """
    line = line.strip()
    head = _LEADING_NAME.match(line).group()
    rest = line[len(head) :]
    if not rest:
        raise ParseError(f"В строке «{line}» нет размеров.")
    return head.strip(" -−:"), numbers(rest)


def single_number(text: str, *, minimum: float = 0.0, maximum: float | None = None) -> float:
    """Одно число без пересчёта единиц: шов, толщина, процент, цена."""
    values = numbers(text)
    if len(values) != 1:
        raise ParseError("Нужно одно число.")
    value = values[0]
    if value < minimum:
        raise ParseError(f"Не меньше {minimum:g}.")
    if maximum is not None and value > maximum:
        raise ParseError(f"Не больше {maximum:g}.")
    return value
