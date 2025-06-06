import logging
import asyncio
import traceback
from aiogram import Bot
from typing import Any, Dict

from config import ERROR_LOG_CHANNEL_ID, BOT_TOKEN

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

async def log_and_report(error: Exception, context: str) -> None:
    """
    Логирует ошибку в логи и отправляет текст ошибки в канал ошибок.
    """
    logging.error(f"[{context}] {error}")
    tb = traceback.format_exc()
    message = f"Ошибка в {context}: {error}\n<pre>{tb}</pre>"
    try:
        bot = get_bot()
        await bot.send_message(ERROR_LOG_CHANNEL_ID, message, parse_mode="HTML")
    except Exception as e:
        logging.error(f"[log_and_report] Не удалось отправить сообщение об ошибке: {e}")

# Словарь для хранения временных меток запросов на вступление
join_requests: Dict[int, float] = {}

async def cleanup_join_requests() -> None:
    """
    Удаляет устаревшие записи из join_requests (старше 5 минут).
    Запускается как background-задача.
    """
    while True:
        now = asyncio.get_event_loop().time()
        expired = [uid for uid, ts in join_requests.items() if now - ts > 300]
        for uid in expired:
            join_requests.pop(uid, None)
        await asyncio.sleep(60)
