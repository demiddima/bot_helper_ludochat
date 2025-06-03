import os
import sys
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.types import Message

from aiohttp import web
from dotenv import load_dotenv
from storage import init_db_pool
from handlers.join import router as join_router
import handlers.commands  # noqa: F401
import services.invite_service as invite_service  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()  # подгружаем переменные из .env
BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_CHAT_ID = int(os.getenv("PUBLIC_CHAT_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
ERROR_LOG_CHANNEL_ID = int(os.getenv("ERROR_LOG_CHANNEL_ID", "0"))

# Parse comma-separated list of admin IDs into a Python list of ints
ADMIN_CHAT_IDS_RAW = os.getenv("ADMIN_CHAT_IDS", "")
if not ADMIN_CHAT_IDS_RAW:
    ADMIN_CHAT_IDS = []
else:
    ADMIN_CHAT_IDS = [int(x.strip()) for x in ADMIN_CHAT_IDS_RAW.split(",") if x.strip()]

# PRIVATE_DESTINATIONS: split "Title:id:Desc" items by comma, then by colon
PRIVATE_DESTINATIONS_RAW = os.getenv("PRIVATE_DESTINATIONS", "")
if PRIVATE_DESTINATIONS_RAW:
    PRIVATE_DESTINATIONS = []
    for item in PRIVATE_DESTINATIONS_RAW.split(","):
        parts = item.split(":", 2)
        if len(parts) != 3:
            continue
        title, chat_id, description = parts
        PRIVATE_DESTINATIONS.append({
            "title": title,
            "chat_id": int(chat_id),
            "description": description
        })
else:
    PRIVATE_DESTINATIONS = []


async def main():
    # 1) Инициализация бота (убираем DefaultBotProperties, передаём parse_mode напрямую)
    bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
    dp = Dispatcher()

    # 2) Инициализация connection pool к БД
    await init_db_pool()

    # 3) Регистрируем роутеры (join, команды и т. д.)
    dp.include_router(join_router)

    # 4) Запускаем aiohttp-сервер параллельно с polling
    app = web.Application()
    # Пример простого health-check-эндпоинта:
    async def health(request):
        return web.Response(text="OK")
    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    # 5) Запуск polling
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.warning("Shutting down...")
