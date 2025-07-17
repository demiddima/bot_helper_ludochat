import time
import logging
import asyncio

from aiogram import Router, F
from aiogram.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

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
    uid = message.from_user.id  # Получаем id пользователя
    parts = message.text.split()
    bot_username = (await bot.get_me()).username or ""

    async def _safe_track(key: str):
        try:
            await track_link_visit(key)
        except Exception as exc:
            logging.error(f"[TRACK] {exc}")

    # 1) Если уже приняли условия — сразу ресурсы
    if await has_user_accepted(uid):
        if len(parts) == 2 and parts[1] not in ("start",) and not parts[1].startswith("verify_"):
            asyncio.create_task(_safe_track(parts[1]))
        return await send_resources_message(bot, message.from_user, uid)  # Передаем все три аргумента

    # 2) Пришли по verify_<uid> — отмечаем и показываем ресурсы
    if len(parts) == 2 and parts[1].startswith("verify_"):
        orig = int(parts[1].split("_", 1)[1])
        ts = join_requests.get(orig)
        if ts is None or time.time() - ts > 300:
            join_requests.pop(orig, None)
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
            await membership.add_user_and_membership(message.from_user, membership.BOT_ID)
        except Exception as exc:
            logging.exception(f"[JOIN] Ошибка add_user_and_membership для verify_{orig}: {exc}")
        try:
            await set_user_accepted(orig)
        except Exception:
            logging.exception(f"[STORAGE] Не удалось записать acceptance для {orig}")
        return await send_resources_message(bot, message.from_user, orig)  # Передаем все три аргумента

    # 3) Первый /start — сохраняем запрос и шлём welcome
    join_requests[uid] = time.time()
    try:
        await membership.add_user_and_membership(message.from_user, membership.BOT_ID)
    except Exception as exc:
        logging.exception(f"[JOIN] Ошибка add_user_and_membership на первом /start для {uid}: {exc}")

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