# services/subscriptions.py
# Инициализация дефолтов подписок пользователя (OFF/ON/ON) через DB API

import logging
from .db_api_client import db_api_client


DEFAULT_SUBS = {
    "news_enabled": False,
    "meetings_enabled": True,
    "important_enabled": True,
}

async def ensure_user_subscriptions_defaults(user_id: int) -> None:
    """
    Идемпотентная инициализация подписок пользователя дефолтами.
    Любые ошибки логируем и не пробрасываем — первый запуск не должен падать.
    """
    try:
        await db_api_client.put_user_subscriptions(
            user_id=user_id,
            news_enabled=DEFAULT_SUBS["news_enabled"],
            meetings_enabled=DEFAULT_SUBS["meetings_enabled"],
            important_enabled=DEFAULT_SUBS["important_enabled"],
        )
        logging.info(
            "[ensure_user_subscriptions_defaults] – user_id=%s – OK",
            user_id, extra={"user_id": user_id}
        )
    except Exception as exc:
        logging.error(
            "[ensure_user_subscriptions_defaults] – user_id=%s – Ошибка: %s",
            user_id, exc, extra={"user_id": user_id}
        )
