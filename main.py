# main.py
# commit: changed added_at to use .isoformat() for JSON serialization

import os
import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, BaseMiddleware
from aiohttp import web

from config import (
    BOT_TOKEN,
    LOG_CHANNEL_ID,
    ERROR_LOG_CHANNEL_ID,
    ADMIN_CHAT_IDS,
    PRIVATE_DESTINATIONS,
    INVITE_LINK_MODE,
)
from storage import upsert_chat
from handlers.join import router as join_router
from handlers.commands import router as commands_router
from handlers.membership import router as membership_router
import services.invite_service  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GlobalErrorMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            return await handler(event, data)
        except Exception as exc:
            bot = data.get("bot")
            if bot:
                await bot.send_message(
                    ERROR_LOG_CHANNEL_ID,
                    f"❗️Глобальная ошибка:\n<pre>{exc}</pre>",
                    parse_mode="HTML"
                )
            logger.exception(f"Global error: {exc}")
            raise

async def main():
    # 1) Initialize bot
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # --- Регистрируем глобальный middleware для ошибок ---
    dp.update.middleware(GlobalErrorMiddleware())

    # 2) Register bot in chats table via API
    bot_info = await bot.get_me()
    await upsert_chat({
        "id": bot_info.id,
        "title": bot_info.username or "",
        "type": "private",  
        "added_at": datetime.utcnow().isoformat()  # ← теперь строка ISO
    })

    # 3) Register routers
    dp.include_router(join_router)
    dp.include_router(commands_router)
    dp.include_router(membership_router)

    # 4) Start aiohttp server for health-check
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
        logger.warning("Shutting down...")
