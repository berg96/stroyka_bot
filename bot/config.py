from pydantic_settings import BaseSettings

class BotConfig(BaseSettings):
    token: str

    class Config:
        env_file = ".env"
        extra = 'ignore'


config = BotConfig()
