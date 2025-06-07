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
            logging.error(f"[ERROR] cleanup_join_requests: {e}\n{traceback.format_exc()}")
        await asyncio.sleep(60)

async def log_and_report(error: Exception, context: str) -> None:
    """
    Логирует ошибку и отправляет сообщение в канал логирования.
    """
    logging.error(f"[ERROR] {context}: {error}\n{traceback.format_exc()}")
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(ERROR_LOG_CHANNEL_ID, f"Error in {context}: {error}")
    except Exception as e:
        logging.error(f"[ERROR] log_and_report failed: {e}\n{traceback.format_exc()}")
