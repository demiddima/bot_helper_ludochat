import os
import sys
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import (
    BOT_TOKEN, PUBLIC_CHAT_ID, LOG_CHANNEL_ID,
    ERROR_LOG_CHANNEL_ID, ADMIN_CHAT_IDS, PRIVATE_DESTINATIONS
)
from handlers.join import router as join_router

logging.basicConfig(level=logging.INFO)

async def main():
    # 1) Инициализация бота
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    dp = Dispatcher()

    # Регистрируем роутеры
    dp.include_router(join_router)

    # 2) Запускаем polling Telegram в фоне
    polling_task = asyncio.create_task(dp.start_polling(bot))

    # 3) Поднимаем HTTP-сервер для health-check
    from aiohttp import web

    async def handle_health(request):
        return web.Response(text="OK")

    app = web.Application()
    app.router.add_get('/', handle_health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()

    logging.info("HTTP server started on port 8080")

    # 4) Ожидаем, пока polling_task не завершится
    await polling_task

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped")
        sys.exit(0)
