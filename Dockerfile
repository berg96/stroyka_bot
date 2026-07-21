# Один образ на оба сервиса (бот и мини-апп) — чтобы `up --build` поднимал их из
# ОДНОГО кода. Именно рассинхрон версий бот↔веб (деплоились врозь) ронял смету у Сани.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH="/app/.venv/bin:$PATH"

# Слой зависимостей кэшируется: пересобирается только при смене pyproject/uv.lock.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Код. tilebot не ставим в venv — запускаем через PYTHONPATH=/app/src, как systemd.
COPY src ./src

# По умолчанию — бот; веб переопределяет command в compose.
CMD ["python", "-m", "tilebot.main"]
