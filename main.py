import os
import sys
import asyncio
import logging
import re

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.types import Message

from aiohttp import web
from dotenv import load_dotenv
from storage import init_db_pool
from handlers.join import router as join_router
from handlers.commands import router as commands_router
import services.invite_service as invite_service  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()  # Load variables from .env
BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_CHAT_ID = int(os.getenv("PUBLIC_CHAT_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
ERROR_LOG_CHANNEL_ID = int(os.getenv("ERROR_LOG_CHANNEL_ID", "0"))

# Parse comma or semicolon-separated list of admin IDs into a list of ints
ADMIN_CHAT_IDS_RAW = os.getenv("ADMIN_CHAT_IDS", "")
if not ADMIN_CHAT_IDS_RAW:
    ADMIN_CHAT_IDS = []
else:
    ADMIN_CHAT_IDS = [int(x.strip()) for x in re.split(r"[,;]", ADMIN_CHAT_IDS_RAW) if x.strip()]

# PRIVATE_DESTINATIONS: split "Title:id:Desc" items by comma, then colon
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
    # 1) Initialize bot
    bot = Bot(token=BOT_TOKEN, default=None)
    dp = Dispatcher()

    # 2) Initialize DB pool
    await init_db_pool()

    # 3) Register routers
    dp.include_router(join_router)
    dp.include_router(commands_router)

    # 4) Start aiohttp server alongside polling
    app = web.Application()
    async def health(request):
        return web.Response(text="OK")
    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"HTTP health-check server started on port {port}")

    # 5) Start polling
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.warning("Shutting down...")
