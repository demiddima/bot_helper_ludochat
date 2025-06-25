# main.py
import logger                  # настраивает консоль INFO+ и Telegram ERROR+
import os                      # для getenv
import sys
import asyncio
import logging
import html                    # для html.escape

from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums.parse_mode import ParseMode

import config
from storage import upsert_chat
from handlers.join import router as join_router
from handlers.commands import router as commands_router
from handlers.membership import router as membership_router
import services.invite_service  # noqa: F401


# 1) ловим uncaught исключения в sync-коде
def _excepthook(exc_type, exc_value, tb):
    logging.getLogger(__name__).exception(
        "Uncaught exception", exc_info=(exc_type, exc_value, tb)
    )
sys.excepthook = _excepthook

# 2) ловим исключения в asyncio-тасках
def _async_exception_handler(loop, context):
    logging.getLogger(__name__).error(
        "Unhandled asyncio error",
        exc_info=context.get("exception")
    )
asyncio.get_event_loop().set_exception_handler(_async_exception_handler)

# 3) глобальный error handler для апдейтов
async def global_error_handler(update, exception):
    log = logging.getLogger(__name__)
    log.exception(f"Error handling update: {exception}")

    # коротко отправляем в Telegram-канал ошибок
    try:
        bot = Bot.get_current()
        text = f"❗️<b>Ошибка:</b>\n<pre>{html.escape(str(exception))}</pre>"
        await bot.send_message(
            config.ERROR_LOG_CHANNEL_ID,
            text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except Exception:
        log.error("Failed to send error message to ERROR_LOG_CHANNEL_ID")

    # уведомляем пользователя, если это сообщение
    if getattr(update, "message", None):
        try:
            await update.message.answer("Произошла ошибка, попробуйте позже.")
        except Exception:
            log.error("Failed to notify user about error")

    return True  # отмечаем, что ошибка обработана


async def main():
    log = logging.getLogger(__name__)
    log.info("Запускаем бота")

    # инициализация бота и диспетчера
    bot = Bot(token=config.BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher()

    # регистрируем глобальный error handler
    dp.errors.register(global_error_handler)

    # регистрируем роутеры
    dp.include_router(join_router)
    dp.include_router(commands_router)
    dp.include_router(membership_router)

    # регистрируем бота в БД
    me = await bot.get_me()
    await upsert_chat({
        "id": me.id,
        "title": me.username or "",
        "type": "private",
        "added_at": datetime.utcnow().isoformat()
    })
    log.info(f"Registered bot chat: {me.id}")

    # запускаем HTTP-сервер для health-check
    app = web.Application()
    async def health(request):
        return web.Response(text="OK")
    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"HTTP health-check server started on port {port}")

    # старт polling
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.getLogger(__name__).warning("Shutting down...")
    # все прочие ошибки уйдут в sys.excepthook
