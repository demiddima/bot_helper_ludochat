import logging
import asyncio
import time
from aiogram import Bot
from config import BOT_TOKEN, ERROR_LOG_CHANNEL_ID

bot = Bot(token=BOT_TOKEN)

async def log_and_report(exc: Exception, context: str):
    text = f"[{context}] {str(exc).replace('`', '')}"
    logging.error(text)
    try:
        await bot.send_message(ERROR_LOG_CHANNEL_ID, text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"[FAIL] Не удалось отправить лог об ошибке: {e}")

# join_requests store with timestamp
join_requests: dict[int, float] = {}
REQUEST_TIMEOUT = 300  # seconds

async def cleanup_join_requests():
    while True:
        now = time.time()
        expired = [uid for uid, ts in join_requests.items() if now - ts > REQUEST_TIMEOUT]
        for uid in expired:
            del join_requests[uid]
        await asyncio.sleep(60)  # Проверяем каждые 60 секунд
