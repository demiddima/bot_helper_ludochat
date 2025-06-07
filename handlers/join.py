"""Обработчик сценария вступления через /start с подтверждением в течение 5 минут.

Обновлено: возвращён динамический текст со ссылками из messages.get_invite_links_text, сохранён общий шаблон.
Кнопки-приватные чаты оставлены для удобства обновления ссылок.
"""

import logging
import time
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    CallbackQuery,
    ChatMemberUpdated,
)
from aiogram.exceptions import TelegramAPIError

from config import PRIVATE_DESTINATIONS
from storage import (
    upsert_chat,
    add_user_to_chat,
    remove_user_from_chat,
    save_invite_link,
    get_valid_invite_links,
    delete_invite_links,
)
from utils import log_and_report, join_requests, cleanup_join_requests, get_bot
from messages import TERMS_MESSAGE, get_invite_links_text

router = Router()
BOT_ID: int | None = None
_last_refresh: dict[int, float] = {}

@router.startup()
async def on_startup():
    """Сохраняем ID бота и очищаем устаревшие заявки"""
    global BOT_ID
    bot = get_bot()
    me = await bot.get_me()
    BOT_ID = me.id
    try:
        await upsert_chat(BOT_ID, me.username or "bot", "bot")
    except Exception as exc:
        await log_and_report(exc, "upsert_chat(bot)")
    cleanup_join_requests()

@router.message(F.text.startswith("/start"))
async def process_start(message: Message):
    """Обрабатываем /start и deep-link /start verify_<uid>"""
    bot = get_bot()
    parts = message.text.split()
    bot_username = (await bot.get_me()).username or ""

    # deep-link подтверждения
    if len(parts) == 2 and parts[1].startswith("verify_"):
        orig_uid = int(parts[1].split("_", 1)[1])
        ts = join_requests.get(orig_uid)
        if ts is None or time.time() - ts > 300:
            join_requests.pop(orig_uid, None)
            await message.reply(
                "⏰ Время ожидания вышло. Отправьте /start ещё раз.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="/start", url=f"https://t.me/{bot_username}?start")]
                ])
            )
            return
        join_requests.pop(orig_uid, None)
        try:
            u = message.from_user
            await add_user_to_chat(orig_uid, BOT_ID, u.username or "", u.full_name or "")
        except Exception as exc:
            await log_and_report(exc, f"add_user({orig_uid})")
        await send_invite_links(orig_uid)
        return

    # простой /start
    uid = message.from_user.id
    join_requests[uid] = time.time()
    try:
        await add_user_to_chat(uid, BOT_ID, message.from_user.username or "", message.from_user.full_name or "")
    except Exception as exc:
        await log_and_report(exc, f"add_user_on_start({uid})")

    confirm_link = f"https://t.me/{bot_username}?start=verify_{uid}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Я согласен(а) и ознакомлен(а) со всем",
            url=confirm_link
        )]
    ])
    await bot.send_message(
        uid,
        TERMS_MESSAGE,
        reply_markup=kb,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

@router.callback_query(F.data.startswith("refresh_"))
async def on_refresh(query: CallbackQuery):
    """Обработка обновления ссылок"""
    await query.answer("Обновляю...")
    _, uid_str = query.data.split("_", 1)
    uid = int(uid_str)
    if query.from_user.id != uid:
        return await query.answer("Это не ваши ссылки.")
    await send_invite_links(uid)

async def send_invite_links(uid: int):
    """Генерируем новые инвайт-ссылки, формируем текст и кнопки"""
    bot = get_bot()
    now = time.time()
    if now - _last_refresh.get(uid, 0) < 10:
        return
    _last_refresh[uid] = now

    # отзываем старые ссылки
    existing = await get_valid_invite_links(uid)
    for chat_id, link in existing:
        try:
            await bot.revoke_chat_invite_link(chat_id, link)
        except TelegramAPIError:
            pass
    await delete_invite_links(uid)

    # генерируем новые
    triples: list[tuple[str, str, str]] = []
    expire_ts = int((datetime.utcnow() + timedelta(days=1)).timestamp())
    buttons: list[list[InlineKeyboardButton]] = []
    for dest in PRIVATE_DESTINATIONS:
        cid = dest['chat_id']
        title = dest.get('title', 'Chat')
        try:
            invite = await bot.create_chat_invite_link(
                chat_id=cid,
                member_limit=1,
                expire_date=expire_ts,
                name=f"Invite for {uid}",
                creates_join_request=False,
            )
            await save_invite_link(uid, cid, invite.invite_link)
            triples.append((title, invite.invite_link, dest.get('description', '')))
            buttons.append([InlineKeyboardButton(text=title, url=invite.invite_link)])
        except TelegramAPIError as exc:
            logging.warning(f"Failed to create link for {cid}: {exc}")
    # кнопка обновления
    buttons.append([InlineKeyboardButton(text="🔄 Обновить ссылки", callback_data=f"refresh_{uid}")])

    # формируем текст из шаблона
    text = get_invite_links_text(triples)
    # отправляем текст и кнопки
    await bot.send_message(uid, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML", disable_web_page_preview=True)

@router.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated):
    """Обработка блокировки/разблокировки бота"""
    user_id = update.from_user.id
    status = update.new_chat_member.status
    if status in ("left", "kicked"):
        await remove_user_from_chat(user_id, BOT_ID)
        join_requests.pop(user_id, None)
    elif status == "member":
        await add_user_to_chat(user_id, BOT_ID, update.from_user.username or "", update.from_user.full_name or "")
