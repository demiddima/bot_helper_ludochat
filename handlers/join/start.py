# start.py
# Обновление: Добавлен флаг SHOW_WELCOME — можно отключать сообщение согласия. Все действия фиксации сохраняются.

import time
import logging
import asyncio
import config
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup

from utils import get_bot, join_requests
from storage import (
    has_terms_accepted as has_user_accepted,
    track_link_visit,
    set_terms_accepted as set_user_accepted,
)
import handlers.join.membership as membership
from handlers.join.resources import send_resources_message, send_chunked_message
from messages import get_welcome_text


router = Router()

@router.message(F.text.startswith("/start"))
async def process_start(message: Message):
    bot = get_bot()
    uid = message.from_user.id
    parts = message.text.split()
    bot_username = (await bot.get_me()).username or ""
    func_name = "process_start"

    async def _safe_track(key: str):
        try:
            await track_link_visit(key)
        except Exception as exc:
            logging.error(
                f"user_id={uid} – Ошибка отслеживания визита ссылки: {exc}",
                extra={"user_id": uid}
            )

    # В любом случае регистрируем пользователя и подписку
    try:
        await membership.add_user_and_membership(message.from_user, config.BOT_ID)
    except Exception as exc:
        logging.exception(
            f"user_id={uid} – Ошибка add_user_and_membership: {exc}",
            extra={"user_id": uid}
        )

    # Если SHOW_WELCOME выключен — сразу ставим галку и шлём ресурсы
    if not config.SHOW_WELCOME:
        try:
            await set_user_accepted(uid)
            logging.info(
                f"user_id={uid} – Условие принято автоматически (SHOW_WELCOME=0)",
                extra={"user_id": uid}
            )
        except Exception as exc:
            logging.exception(
                f"user_id={uid} – Ошибка при auto set_terms_accepted: {exc}",
                extra={"user_id": uid}
            )
        if len(parts) == 2 and parts[1] not in ("start",) and not parts[1].startswith("verify_"):
            asyncio.create_task(_safe_track(parts[1]))
        return await send_resources_message(bot, message.from_user, uid)

    # Если уже приняли — шлём ресурсы
    if await has_user_accepted(uid):
        if len(parts) == 2 and parts[1] not in ("start",) and not parts[1].startswith("verify_"):
            asyncio.create_task(_safe_track(parts[1]))
        return await send_resources_message(bot, message.from_user, uid)

    # verify — подтверждение
    if len(parts) == 2 and parts[1].startswith("verify_"):
        orig = int(parts[1].split("_", 1)[1])
        ts = join_requests.get(orig)
        if ts is None or time.time() - ts > 300:
            join_requests.pop(orig, None)
            logging.warning(
                f"user_id={uid} – verify_{orig} истёк или не найден",
                extra={"user_id": uid}
            )
            return await message.reply(
                "⏰ Время ожидания вышло. Отправьте /start ещё раз.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[  
                    InlineKeyboardButton(
                        text="/start",
                        url=f"https://t.me/{bot_username}?start=start"
                    )
                ]])
            )
        join_requests.pop(orig, None)
        try:
            await set_user_accepted(orig)
            logging.info(
                f"user_id={uid} – Условие принято (verify_{orig})",
                extra={"user_id": uid}
            )
        except Exception as exc:
            logging.exception(
                f"user_id={uid} – Ошибка set_terms_accepted: {exc}",
                extra={"user_id": uid}
            )
        return await send_resources_message(bot, message.from_user, orig)

    # Первый /start – приветствие
    join_requests[uid] = time.time()
    confirm_link = f"https://t.me/{bot_username}?start=verify_{uid}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[  
        InlineKeyboardButton(
            text="✅ Я согласен(а) и ознакомлен(а) со всем",
            url=confirm_link
        )
    ]])
    await send_chunked_message(
        uid,
        get_welcome_text(),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=kb,
    )
