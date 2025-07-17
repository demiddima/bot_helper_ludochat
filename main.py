import os
import sys
import asyncio
import logging
import html                    # для html.escape
from utils import get_bot

from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums.parse_mode import ParseMode

import config
from storage import upsert_chat
from handlers.join import router as join_router         # :contentReference[oaicite:0]{index=0}
from handlers.commands import router as commands_router # :contentReference[oaicite:1]{index=1}

# Флаг для проверки повторных логов
already_logged = set()

# 1) ловим uncaught исключения в sync-коде
def _excepthook(exc_type, exc_value, tb):
    logging.getLogger(__name__).exception(
        "Uncaught exception", exc_info=(exc_type, exc_value, tb)
    )
sys.excepthook = _excepthook

# 2) ловим исключения в asyncio-тасках
def _async_exception_handler(loop, context):
    logging.getLogger(__name__).error(
        "Unhandled asyncio error", exc_info=context.get("exception")
    )
asyncio.get_event_loop().set_exception_handler(_async_exception_handler)

async def global_error_handler(*args) -> bool:
    """
    Универсальный обработчик ошибок:
    - Поддерживает старую (exception) и новую (update, exception) сигнатуры.
    - Делит слишком длинные сообщения на части ≤4096 символов.
    """
    # Разбираем аргументы
    if len(args) == 2:
        update, exception = args
    elif len(args) == 1:
        update = None
        exception = args[0]
    else:
        return True

    log = logging.getLogger(__name__)
    log.exception(f"Unhandled exception: {exception}", exc_info=True)

    # Текст для Telegram-канала
    error_text = f"❗️<b>Ошибка:</b>\n<pre>{html.escape(str(exception))}</pre>"
    bot = get_bot()
    max_len = 4096

    # Отправляем частями
    for start in range(0, len(error_text), max_len):
        chunk = error_text[start:start + max_len]
        try:
            await bot.send_message(
                config.ERROR_LOG_CHANNEL_ID,
                chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
        except Exception as send_exc:
            log.error(f"Failed to send error chunk: {send_exc}")

    # Оповестить пользователя (если возможно)
    if update and hasattr(update, "message") and update.message:
        try:
            await update.message.answer("Произошла внутренняя ошибка, попробуйте позже.")
        except Exception as user_exc:
            log.error(f"Failed to notify user: {user_exc}")

    return True

async def main():
    log = logging.getLogger(__name__)

    # Логируем только один раз
    if "Запускаем бота" not in already_logged:
        log.info("Запускаем бота")
        already_logged.add("Запускаем бота")

    # Инициализация бота и других компонентов
    bot = Bot(token=config.BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher()

    # Регистрируем обработчики
    dp.errors.register(global_error_handler)

    # Подключаем роутеры
    dp.include_router(join_router)
    dp.include_router(commands_router)

    # Регистрация бота в БД
    me = await bot.get_me()
    config.BOT_ID = me.id
    await upsert_chat({
        "id": me.id,
        "title": me.username or "",
        "type": "private",
        "added_at": datetime.utcnow().isoformat()
    })
    
    if f"Registered bot chat: {me.id}" not in already_logged:
        log.info(f"Registered bot chat: {me.id}")
        already_logged.add(f"Registered bot chat: {me.id}")

    # Инициализация порта для сервера
    port = int(os.getenv("PORT", "8080"))  # Если порт не задан, по умолчанию 8080

    # Запуск сервера
    log.info(f"HTTP health-check server started on port {port}")

    # Создание и запуск HTTP-сервера
    app = web.Application()
    async def health(request):
        return web.Response(text="OK")
    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    # Запуск polling
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.getLogger(__name__).warning("Shutting down...")
