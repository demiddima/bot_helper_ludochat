# main.py
# Подключение админ-команд для рассылок и фонового воркера run_broadcast_worker.

import logger
logger.configure_logging()

import os
import sys
import asyncio
import logging
import html                    # для html.escape
from utils import get_bot
from typing import Any
import traceback

from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode

# Безопасный импорт для разных версий aiogram
try:
    from aiogram.client.default import DefaultBotProperties  # aiogram 3.7+
except Exception:
    DefaultBotProperties = None

import config
from storage import upsert_chat, get_chats as storage_get_chats
from services.broadcasts import run_broadcast_worker
from handlers import router as handlers_router   # единый агрегатор
from config import ERROR_LOG_CHANNEL_ID, ID_ADMIN_USER

# Флаг для проверки повторных логов
already_logged = set()

# Глобальная переменная для отслеживания чатов
tracked_chats: set = set()


# 1) ловим uncaught исключения в sync-коде
def _excepthook(exc_type, exc_value, tb):
    logging.getLogger(__name__).exception("Необработанное исключение", exc_info=(exc_type, exc_value, tb))
sys.excepthook = _excepthook


# 2) ловим исключения в asyncio-тасках
def _async_exception_handler(loop, context):
    logging.getLogger(__name__).error("Необработанная ошибка asyncio", exc_info=context.get("exception"))
asyncio.get_event_loop().set_exception_handler(_async_exception_handler)

def _chunk_text(text: str, limit: int = 4096):
    """Режет текст на части длиной ≤ limit, стараясь резать по границам строк."""
    if not text:
        return
    start = 0
    n = len(text)
    while start < n:
        end = min(start + limit, n)
        # попробуем отмотать до ближайшего перевода строки
        cut = text.rfind("\n", start, end)
        if cut == -1 or cut <= start + limit // 2:
            cut = end
        yield text[start:cut]
        start = cut
        
# замени существующую функцию на эту версию
async def global_error_handler(*args: Any) -> bool:
    """
    Универсальный обработчик ошибок:
    - Поддерживает сигнатуры (exception) и (update, exception).
    - Экранирует HTML и режет текст на куски ≤4096 символов.
    - Шлёт в ERROR_LOG_CHANNEL_ID (если задан), иначе первому ID из ID_ADMIN_USER.
    Возвращает True, чтобы не прерывать пайплайн aiogram.
    """
    if len(args) == 2:
        update, exception = args
    elif len(args) == 1:
        update = None
        exception = args[0]
    else:
        return True

    log = logging.getLogger(__name__)
    log.exception("Необработанное исключение: %s", exception, exc_info=True)

    # целевой чат для алертов
    target_chat_id = None
    try:
        target_chat_id = int(ERROR_LOG_CHANNEL_ID)
    except Exception:
        pass
    if not target_chat_id:
        try:
            target_chat_id = next(iter(ID_ADMIN_USER)) if ID_ADMIN_USER else None
        except Exception:
            target_chat_id = None
    if not target_chat_id:
        return True  # Некуда слать — выходим.

    bot = get_bot()

    # 1) стек
    try:
        tb = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
    except Exception:
        tb = str(exception)
    import html as _html
    err_html = f"❗️<b>Ошибка</b>\n<pre>{_html.escape(tb)}</pre>"
    for part in _chunk_text(err_html):
        try:
            await bot.send_message(target_chat_id, part, disable_web_page_preview=True)
        except Exception as e:
            log.error("Не удалось отправить часть сообщения об ошибке: %s", e)

    # 2) сам update (если был)
    if update is not None:
        try:
            try:
                upd_str = update.model_dump_json(indent=2, ensure_ascii=False)  # pydantic v2
            except Exception:
                upd_str = str(update)
            upd_html = f"<b>Update</b>\n<pre>{_html.escape(upd_str)}</pre>"
            for part in _chunk_text(upd_html):
                await bot.send_message(target_chat_id, part, disable_web_page_preview=True)
        except Exception as e:
            log.error("Не удалось отправить часть сообщения об ошибке: %s", e)

    return True


async def _warmup_tracked_chats(log: logging.Logger):
    """Неблокирующий прогрев списка чатов: если БД недоступна — просто пишем лог и не падаем."""
    global tracked_chats
    try:
        data = await storage_get_chats()
        tracked_chats = set(data)
        log.info(f"tracked_chats (warmup): {tracked_chats}")
    except Exception as e:
        log.error("Не удалось получить список чатов (warmup), продолжим без него", exc_info=True)


async def main():
    log = logging.getLogger(__name__)

    if "Запускаем бота" not in already_logged:
        log.info("Запускаем бота")
        already_logged.add("Запускаем бота")

    # Инициализация бота (совместимость 3.6/3.7+)
    if DefaultBotProperties is not None:
        bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        log.info("Инициализация Bot: aiogram>=3.7 (DefaultBotProperties)")
    else:
        bot = Bot(token=config.BOT_TOKEN, parse_mode=ParseMode.HTML)
        log.info("Инициализация Bot: aiogram<=3.6 (parse_mode в конструкторе)")

    dp = Dispatcher()
    dp.errors.register(global_error_handler)

    # Подключаем все роутеры из handlers
    dp.include_router(handlers_router)

    # Стартуем фоновые задачи (не блокируем запуск)
    asyncio.create_task(_warmup_tracked_chats(log))

    # ⬇️ Фоновый воркер рассылок (интервал задаётся в .env через BROADCAST_WORKER_INTERVAL, если есть)
    interval = getattr(config, "BROADCAST_WORKER_INTERVAL", 20)
    asyncio.create_task(run_broadcast_worker(bot, interval_seconds=interval))

    me = await bot.get_me()
    config.BOT_ID = me.id
    await upsert_chat({
        "id": me.id,
        "title": me.username or "",
        "type": "private",
        "added_at": datetime.utcnow().isoformat()
    })

    if f"Registered bot chat: {me.id}" not in already_logged:
        log.info(f"Зарегистрирован чат бота: {me.id}")
        already_logged.add(f"Registered bot chat: {me.id}")

    port = int(os.getenv("PORT", "8080"))
    log.info(f"HTTP health-check сервер запущен на порту {port}")

    app = web.Application()
    async def health(request):
        return web.Response(text="OK")
    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.getLogger(__name__).warning("Завершение работы...")
