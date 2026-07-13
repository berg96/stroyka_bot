from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    db_path: str = "data/tilebot.sqlite3"
    admin_id: int = 0  # кому слать ошибки; 0 — никому


def get_settings() -> Settings:
    return Settings()
