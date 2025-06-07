"""Обработчик вступления с DB-управлением invite-ссылками."""

import logging
import asyncio
import time
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.types import (
    ChatJoinRequest,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    CallbackQuery,
)
from aiogram.exceptions import TelegramAPIError

from config import PUBLIC_CHAT_ID, PRIVATE_DESTINATIONS
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

# Rate limiting dict: user_id -> last refresh timestamp
_last_refresh: dict[int, float] = {}

@router.startup()
async def on_startup():
    # Запуск фоновой очистки просроченных запросов
    asyncio.create_task(cleanup_join_requests())

@router.chat_join_request(F.chat.id == PUBLIC_CHAT_ID)
async def handle_join(update: ChatJoinRequest):
    uid = update.from_user.id
    join_requests[uid] = time.time()
    bot = get_bot()
    bot_username = (await bot.get_me()).username
    url = f"https://t.me/{bot_username}?start=verify_{uid}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Я согласен(а)", url=url)
    ]])
    try:
        await bot.send_message(
            uid,
            TERMS_MESSAGE,
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        logging.info(f"[SEND] TERMS_MESSAGE to {uid}")
    except Exception as e:
        await log_and_report(e, f"handle_join({uid})")

@router.message(F.text.startswith("/start"))
async def process_start(message: Message):
    bot = get_bot()
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].startswith("verify_"):
        return
    try:
        uid = int(parts[1].split("_", 1)[1])
    except ValueError:
        return

    ts = join_requests.get(uid)
    if ts is None or time.time() - ts > 300:
        join_requests.pop(uid, None)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Лудочат · Переходник", url="https://t.me/ludoochat")]
        ])
        return await message.reply(
            "⏰ Время ожидания вышло. Повторите вступление через <a href=\"https://t.me/ludoochat\">Лудочат · Переходник</a>.",
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    if message.from_user.id != uid:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Лудочат · Переходник", url="https://t.me/ludoochat")]
        ])
        return await message.reply(
            "Это не ваши ссылки.",
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    join_requests.pop(uid, None)
    try:
        await bot.approve_chat_join_request(PUBLIC_CHAT_ID, uid)
        logging.info(f"[APPROVE] {uid}")
    except Exception as e:
        await log_and_report(e, f"approve({uid})")

    try:
        chat = await bot.get_chat(PUBLIC_CHAT_ID)
        await upsert_chat(chat.id, chat.title or "", chat.type)
        user = message.from_user
        await add_user_to_chat(uid, PUBLIC_CHAT_ID, user.username, user.full_name)
    except Exception as e:
        await log_and_report(e, f"db_user({uid})")

    await send_links_message(uid)

async def send_links_message(uid: int):
    bot = get_bot()
    # Rate limiting: не чаще 60 сек
    now = time.time()
    last = _last_refresh.get(uid, 0)
    if now - last < 60:
        return
    _last_refresh[uid] = now

    # Revoke old links
    for chat_id, link in await get_valid_invite_links(uid):
        try:
            await bot.revoke_chat_invite_link(chat_id=chat_id, invite_link=link)
        except TelegramAPIError as e:
            logging.warning(f"Revoke failed {link}: {e}")
            if 'forbidden' in str(e).lower():
                await log_and_report(e, f"revoke_forbidden({uid},{chat_id})")
    await delete_invite_links(uid)

    # Create new 1-day links
    expire_ts = int((datetime.utcnow() + timedelta(days=1)).timestamp())
    links = []
    for dest in PRIVATE_DESTINATIONS:
        cid = dest["chat_id"]
        try:
            invite = await bot.create_chat_invite_link(
                chat_id=cid,
                member_limit=1,
                expire_date=expire_ts,
                creates_join_request=False,
                name=f"Invite for {uid}",
            )
            await save_invite_link(uid, cid, invite.invite_link)
            links.append((dest["title"], invite.invite_link, dest["description"]))
        except Exception as e:
            await log_and_report(e, f"create({uid},{cid})")

    buttons = [
        [InlineKeyboardButton(text="Лудочат", url=links[0][1] if links else "https://t.me/ludoochat")],
        [InlineKeyboardButton(text="Выручат", url=links[1][1] if len(links) > 1 else "https://t.me/viruchkaa_bot?start=0012")],
        [InlineKeyboardButton(text="🔄 Обновить ссылки", callback_data=f"refresh_{uid}")],
    ]
    text = get_invite_links_text(links)
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await bot.send_message(uid, text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        await log_and_report(e, f"send_links({uid})")

@router.callback_query(F.data.startswith("refresh_"))
async def refresh_links(query: CallbackQuery):
    await query.answer("Обновляю...")
    try:
        _, str_uid = query.data.split("_", 1)
        uid = int(str_uid)
    except Exception:
        return await query.answer("Неверные данные.")
    if query.from_user.id != uid:
        return await query.answer("Это не ваши ссылки.")
    await send_links_message(uid)
