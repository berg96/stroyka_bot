from functools import wraps

from loguru import logger
import sys


LOG_WITH_USER = 'Пользователь {} (ID: {}, username: @{}): {}'


def setup_logging():
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time} | {level} | {message}")
    logger.add(
        "bot_actions.log", rotation="1 week", retention="1 month",
        encoding="utf-8"
    )


def log_user_action(action_description: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(event, *args, **kwargs):
            user = event.from_user
            logger.info(
                LOG_WITH_USER.format(
                    user.full_name, user.id, user.username,
                    f'выполнил действие: {action_description}'
                )
            )
            return await func(event, *args, **kwargs)
        return wrapper
    return decorator
