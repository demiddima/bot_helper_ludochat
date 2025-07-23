# Commit: utils.py – полный файл с глобальными retry-патчами и логированием
# файл: utils.py

import logging
import asyncio
import traceback
from typing import Dict

from tenacity import retry, stop_after_delay, wait_fixed, retry_if_exception_type, RetryCallState
from httpx import AsyncClient, RequestError
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram import Bot

from config import ERROR_LOG_CHANNEL_ID, BOT_TOKEN

logger = logging.getLogger(__name__)

def _log_before_sleep(retry_state: RetryCallState) -> None:
    """
    Логирует информацию перед следующим слипом retry:
    какая функция, номер попытки, ошибка и время до следующей попытки.
    """
    fn_name = retry_state.fn.__qualname__
    exc = retry_state.outcome.exception()
    delay = retry_state.next_action.sleep
    logger.warning(
        f"[retry] {fn_name}: попытка {retry_state.attempt_number} "
        f"завершилась ошибкой {exc!r}, повтор через {delay} сек"
    )

# ── Патч для HTTPX ──
# при RequestError повторять каждые 10 секунд в течение 10 минут с логированием
AsyncClient.request = retry(
    reraise=True,
    stop=stop_after_delay(600),
    wait=wait_fixed(10),
    retry=retry_if_exception_type(RequestError),
    before_sleep=_log_before_sleep
)(AsyncClient.request)

# ── Патч для Aiogram ──
# при TelegramNetworkError повторять каждые 10 секунд в течение 10 минут с логированием
AiohttpSession.__call__ = retry(
    reraise=True,
    stop=stop_after_delay(600),
    wait=wait_fixed(10),
    retry=retry_if_exception_type(TelegramNetworkError),
    before_sleep=_log_before_sleep
)(AiohttpSession.__call__)


# Lazy Bot initialization
_bot: Bot | None = None

def get_bot() -> Bot:
    """
    Возвращает глобальный экземпляр Bot. Если ещё не создан, создаёт его.
    """
    global _bot
    if _bot is None:
        _bot = Bot(token=BOT_TOKEN)
    return _bot

# Словарь для хранения временных меток запросов на вступление
join_requests: Dict[int, float] = {}

async def cleanup_join_requests() -> None:
    """
    Удаляет устаревшие записи из join_requests (старше 5 минут).
    Запускается как background-задача.
    """
    while True:
        try:
            now = asyncio.get_event_loop().time()
            expired = [uid for uid, ts in join_requests.items() if now - ts > 300]
            for uid in expired:
                join_requests.pop(uid, None)
        except Exception as e:
            logging.error(f"[log_and_report] - Ошибка очистки устаревших запросов: {e}\n{traceback.format_exc()}")
        await asyncio.sleep(60)

async def log_and_report(error: Exception, context: str) -> None:
    """
    Логирует ошибку и отправляет сообщение в канал логирования.
    """
    logging.error(f"[log_and_report] - Ошибка в {context}: {error}\n{traceback.format_exc()}")
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(ERROR_LOG_CHANNEL_ID, f"Ошибка в {context}: {error}")
    except Exception as e:
        logging.error(f"[log_and_report] - Не удалось отправить сообщение об ошибке: {e}\n{traceback.format_exc()}")
