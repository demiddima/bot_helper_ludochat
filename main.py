# main.py — чистая версия под новую архитектуру (Hallway/Mailing), с мягкой обработкой TelegramForbiddenError

from __future__ import annotations

import os
import sys
import asyncio
import logging
import traceback
from typing import Any

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError  # ← добавлено

import logger
logger.configure_logging()

import config
from config import ERROR_LOG_CHANNEL_ID, ID_ADMIN_USER

# Новые агрегаторы роутеров
from Hallway.routers import router as hallway_router
from Mailing.routers import router as mailing_router

# Утилиты/время/DB API — общий слой
from common.utils import get_bot, shutdown_utils
from common.utils.time_msk import now_msk_naive
from common.db_api_client import db_api_client
from common.utils.tg_safe import _cleanup_blocked  # ← добавлено

# Хранилище
from storage import upsert_chat, get_chats as storage_get_chats

# Фоновый воркер рассылок
from Mailing.services.broadcasts import run_broadcast_worker

# Совместимость aiogram 3.7+
try:
    from aiogram.client.default import DefaultBotProperties  # aiogram 3.7+
except Exception:
    DefaultBotProperties = None

log = logging.getLogger(__name__)
already_logged: set[str] = set()
tracked_chats: set[int] = set()


# --- глобальные ловушки исключений ---

def _excepthook(exc_type, exc_value, tb):
    logging.getLogger(__name__).exception(
        "Необработанное исключение", exc_info=(exc_type, exc_value, tb)
    )

sys.excepthook = _excepthook


def _async_exception_handler(loop, context):
    logging.getLogger(__name__).error(
        "Необработанная ошибка asyncio", exc_info=context.get("exception")
    )

asyncio.get_event_loop().set_exception_handler(_async_exception_handler)


def _chunk_text(text: str, limit: int = 4096):
    """Режет текст на части длиной ≤ limit, стараясь резать по границам строк."""
    if not text:
        return
    start = 0
    n = len(text)
    while start < n:
        end = min(start + limit, n)
        cut = text.rfind("\n", start, end)
        if cut == -1 or cut <= start + limit // 2:
            cut = end
        yield text[start:cut]
        start = cut


def _extract_user_id_from_update(update) -> int | None:
    try:
        # CallbackQuery
        cb = getattr(update, "callback_query", None)
        if cb and getattr(cb, "from_user", None):
            return int(cb.from_user.id)
    except Exception:
        pass
    try:
        # Message
        msg = getattr(update, "message", None)
        if msg and getattr(msg, "chat", None):
            return int(msg.chat.id)
    except Exception:
        pass
    try:
        # Edited message
        em = getattr(update, "edited_message", None)
        if em and getattr(em, "chat", None):
            return int(em.chat.id)
    except Exception:
        pass
    try:
        # my_chat_member (приватка)
        mcm = getattr(update, "my_chat_member", None)
        if mcm and getattr(mcm, "chat", None) and mcm.chat.type == "private":
            return int(mcm.chat.id)
    except Exception:
        pass
    return None


async def global_error_handler(*args: Any) -> bool:
    if len(args) == 2:
        update, exception = args
    elif len(args) == 1:
        update = None
        exception = args[0]
    else:
        return True

    # ── Мягкая ветка: заблокировали бота ──
    if isinstance(exception, TelegramForbiddenError):
        uid = _extract_user_id_from_update(update) if update is not None else None
        try:
            if uid is not None:
                await _cleanup_blocked(uid)
                logging.getLogger(__name__).info(
                    "user_id=%s – TelegramForbiddenError перехвачен глобально: очистка выполнена",
                    uid, extra={"user_id": uid}
                )
            else:
                logging.getLogger(__name__).info(
                    "TelegramForbiddenError перехвачен глобально: user_id неизвестен",
                    extra={"user_id": "system"}
                )
        except Exception:
            # даже если очистка упала — не эскалируем Forbidden
            pass
        return True  # ← гасим ошибку, не шлём репорты

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
        return True  # некому слать — выходим

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


async def _warmup_tracked_chats(_log: logging.Logger):
    """Неблокирующий прогрев списка чатов: если БД недоступна — просто пишем лог и не падаем."""
    global tracked_chats
    try:
        data = await storage_get_chats()
        tracked_chats = set(data)
        _log.info(f"tracked_chats (warmup): {tracked_chats}")
    except Exception:
        _log.error("Не удалось получить список чатов (warmup), продолжим без него", exc_info=True)


async def main():
    if "Запускаем бота" not in already_logged:
        log.info("Запускаем бота")
        already_logged.add("Запускаем бота")

    # Инициализация бота
    if DefaultBotProperties is not None:
        bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        log.info("Инициализация Bot: aiogram>=3.7 (DefaultBotProperties)")
    else:
        bot = Bot(token=config.BOT_TOKEN, parse_mode=ParseMode.HTML)
        log.info("Инициализация Bot: aiogram<=3.6 (parse_mode в конструкторе)")

    dp = Dispatcher()
    # Подключаем новые реестры
    dp.include_router(hallway_router)
    dp.include_router(mailing_router)
    dp.errors.register(global_error_handler)

    # Фоновые задачи
    asyncio.create_task(_warmup_tracked_chats(log))

    # Интервал воркера рассылок
    _raw_interval = os.getenv("BROADCAST_WORKER_INTERVAL") or getattr(config, "BROADCAST_WORKER_INTERVAL", 900)
    try:
        interval = int(_raw_interval)
    except Exception:
        interval = 900
    asyncio.create_task(run_broadcast_worker(bot, interval_seconds=interval))

    # Регистрируем чат бота
    me = await bot.get_me()
    config.BOT_ID = me.id
    await upsert_chat({
        "id": me.id,
        "title": me.username or "",
        "type": "private",
        "added_at": now_msk_naive().isoformat(),  # МСК-naive
    })
    if f"Registered bot chat: {me.id}" not in already_logged:
        log.info(f"Зарегистрирован чат бота: {me.id}")
        already_logged.add(f"Registered bot chat: {me.id}")

    # Health-check HTTP
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

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        # Аккуратный shutdown
        try:
            await db_api_client.close()
        except Exception:
            pass
        try:
            await shutdown_utils()
        except Exception:
            pass
        try:
            await bot.session.close()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.getLogger(__name__).warning("Завершение работы...")
