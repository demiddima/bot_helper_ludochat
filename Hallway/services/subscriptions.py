# services/subscriptions.py
# Инициализация дефолтов подписок пользователя (OFF/ON/ON) через DB API

from __future__ import annotations

import logging
from common.db_api_client import db_api_client
from common.utils.common import log_and_report  # отправка в ERROR_LOG_CHANNEL_ID

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
            "Подписки инициализированы: user_id=%s, news=%s, meetings=%s, important=%s",
            user_id,
            DEFAULT_SUBS["news_enabled"],
            DEFAULT_SUBS["meetings_enabled"],
            DEFAULT_SUBS["important_enabled"],
            extra={"user_id": user_id},
        )
    except Exception as exc:
        logging.error(
            "Не удалось инициализировать подписки: user_id=%s, ошибка=%s",
            user_id,
            exc,
            extra={"user_id": user_id},
        )
        # Сообщаем в лог-канал, но не валим поток
        try:
            await log_and_report(exc, f"инициализация подписок, user_id={user_id}")
        except Exception:
            pass
