# services/subscriptions.py
# Инициализация дефолтов подписок пользователя (OFF/ON/ON) через DB API

from __future__ import annotations

import logging
from httpx import HTTPStatusError
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
    На 422 (нет user в БД) — не ругаемся: welcome-флоу может опережать апсёрт user.
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
    except HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 422:
            # Пользователь ещё не создан на бэке — ок, попробуем позже/в другом флоу
            logging.info("Пропускаем init подписок: user_id=%s (422: нет user)", user_id, extra={"user_id": user_id})
            return
        logging.error("Не удалось инициализировать подписки: user_id=%s, HTTP %s",
                      user_id, exc.response.status_code if exc.response else "???",
                      extra={"user_id": user_id})
        try:
            await log_and_report(exc, f"инициализация подписок, user_id={user_id}")
        except Exception:
            pass
    except Exception as exc:
        logging.error("Не удалось инициализировать подписки: user_id=%s, ошибка=%s",
                      user_id, exc, extra={"user_id": user_id})
        try:
            await log_and_report(exc, f"инициализация подписок, user_id={user_id}")
        except Exception:
            pass