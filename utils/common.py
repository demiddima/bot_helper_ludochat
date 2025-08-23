# utils/common.py
# Утилиты: глобальный Bot, репорты ошибок, и заявки на вступление (join_requests).

import logging
import asyncio
import time
from typing import Dict
from datetime import datetime

from tenacity import retry, stop_after_delay, wait_fixed, retry_if_exception_type, RetryCallState
from httpx import AsyncClient, RequestError
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram import Bot

from config import ERROR_LOG_CHANNEL_ID, BOT_TOKEN

logger = logging.getLogger(__name__)


def _log_before_sleep(retry_state: RetryCallState) -> None:
    fn_name = retry_state.fn.__qualname__
    exc = retry_state.outcome.exception()
    delay = retry_state.next_action.sleep
    logger.warning(
        "[retry] %s: попытка %s завершилась ошибкой %r, повтор через %s сек",
        fn_name, retry_state.attempt_number, exc, delay, extra={"user_id": "system"}
    )


# ——— Ретраи для httpx и Aiogram ———
AsyncClient.request = retry(
    reraise=True,
    stop=stop_after_delay(600),
    wait=wait_fixed(10),
    retry=retry_if_exception_type(RequestError),
    before_sleep=_log_before_sleep
)(AsyncClient.request)

AiohttpSession.__call__ = retry(
    reraise=True,
    stop=stop_after_delay(600),
    wait=wait_fixed(10),
    retry=retry_if_exception_type(TelegramNetworkError),
    before_sleep=_log_before_sleep
)(AiohttpSession.__call__)


# ——— Глобальный Bot ———
_bot: Bot | None = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=BOT_TOKEN)
    return _bot


async def shutdown_utils() -> None:
    """Аккуратно закрыть глобальную сессию бота, если создавали."""
    global _bot
    try:
        if _bot is not None:
            await _bot.session.close()
    except Exception as e:
        logging.getLogger(__name__).error("Ошибка закрытия глобальной сессии бота: %s", e, extra={"user_id": "system"})
    finally:
        _bot = None


# ——— Репорт ошибок в канал ———
async def log_and_report(error: Exception, context: str) -> None:
    logging.error("Ошибка в %s: %s", context, error, extra={"user_id": "system"})
    try:
        bot = get_bot()
        text = f"Ошибка в {context}: {error}"
        await bot.send_message(ERROR_LOG_CHANNEL_ID, text)
    except Exception as e:
        logging.error("Не удалось отправить сообщение об ошибке: %s", e, extra={"user_id": "system"})


# ——— Заявки на вступление: карта user_id -> unix time постановки ———
join_requests: Dict[int, float] = {}


async def cleanup_join_requests() -> None:
    """
    Удаляет устаревшие записи из join_requests (старше 5 минут).
    Запускается периодически на старте бота в фоне.
    """
    now = time.time()
    try:
        expired = [uid for uid, ts in join_requests.items() if now - ts > 300]
        for uid in expired:
            join_requests.pop(uid, None)
    except Exception as e:
        logging.getLogger(__name__).error("Ошибка очистки join_requests: %s", e, extra={"user_id": "system"})


def dt_to_iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.replace(microsecond=0).isoformat()
