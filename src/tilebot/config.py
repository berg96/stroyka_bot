from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    db_path: str = "data/tilebot.sqlite3"
    # Фото чеков закупок — файлами рядом с базой (в контейнере это bind-mount).
    receipts_dir: str = "data/receipts"
    admin_id: int = 0  # кому слать ошибки; 0 — никому

    # Мини-апп. Наружу его выставляет nginx, uvicorn слушает только локально.
    web_host: str = "127.0.0.1"
    web_port: int = 8110
    # Публичный адрес мини-аппа. Пусто — кнопки в боте не будет: Telegram примет
    # только https, и подсовывать заведомо битую ссылку хуже, чем не показывать.
    webapp_url: str = ""


def get_settings() -> Settings:
    return Settings()
