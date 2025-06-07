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
    ChatMemberUpdated,
)

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

def get_bot_instance():
    return get_bot()

@router.startup()
async def on_startup():
    asyncio.create_task(cleanup_join_requests())

@router.chat_join_request(F.chat.id == PUBLIC_CHAT_ID)
async def handle_join(update: ChatJoinRequest):
    user = update.from_user
    join_requests[user.id] = time.time()
    bot = get_bot_instance()
    bot_username = (await bot.get_me()).username
    url = f"https://t.me/{bot_username}?start=verify_{user.id}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я согласен(а) и ознакомлен(а) со всем", url=url)]
    ])
    try:
        await bot.send_message(
            user.id,
            TERMS_MESSAGE,
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        logging.info(f"[SEND] Условия отправлены пользователю {user.id}")
    except Exception as e:
        await log_and_report(e, "handle_join")

@router.message(F.text.startswith("/start"))
async def process_start(message: Message):
    bot = get_bot_instance()
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
            "⏰ Время ожидания прошло. Повторите вступление через <a href=\"https://t.me/ludoochat\">Лудочат · Переходник</a>.",
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    if message.from_user.id != uid:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Лудочат · Переходник", url="https://t.me/ludoochat")]
        ])
        return await message.reply(
            "Чтобы пройти верификацию, нажмите «Вступить» в <a href=\"https://t.me/ludoochat\">Лудочат · Переходник</a>.",
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    join_requests.pop(uid, None)
    try:
        await bot.approve_chat_join_request(PUBLIC_CHAT_ID, uid)
        logging.info(f"[APPROVE] Заявка пользователя {uid} одобрена")
    except Exception as e:
        await log_and_report(e, "approve_chat_join_request")
    try:
        chat_obj = await bot.get_chat(PUBLIC_CHAT_ID)
        await upsert_chat(chat_obj.id, chat_obj.title or "", chat_obj.type)
        user = message.from_user
        await add_user_to_chat(uid, PUBLIC_CHAT_ID, user.username, user.full_name)
    except Exception as e:
        await log_and_report(e, f"add_user_to_chat({uid}, {PUBLIC_CHAT_ID})")
    await send_links_message(uid)

async def send_links_message(uid: int):
    bot = get_bot_instance()
    # Revoke old
    for chat_id, link in await get_valid_invite_links(uid):
        try:
            await bot.revoke_chat_invite_link(chat_id=chat_id, invite_link=link)
        except Exception as e:
            logging.warning(f"Revoke failed: {e}")
    await delete_invite_links(uid)
    # Create new
    expire_ts = int((datetime.utcnow() + timedelta(days=1)).timestamp())
    links = []
    for dest in PRIVATE_DESTINATIONS:
        try:
            invite = await bot.create_chat_invite_link(
                chat_id=dest["chat_id"],
                member_limit=1,
                expire_date=expire_ts,
                creates_join_request=False,
                name=f"Invite for {uid}",
            )
            await save_invite_link(uid, dest["chat_id"], invite.invite_link)
            links.append((dest["title"], invite.invite_link, dest["description"]))
        except Exception as e:
            await log_and_report(e, f"create_invite({uid},{dest['chat_id']})")
    buttons = [
        [InlineKeyboardButton(text="Лудочат", url=links[0][1] if links else "https://t.me/ludoochat")],
        [InlineKeyboardButton(text="Выручат", url=links[1][1] if len(links) > 1 else "https://t.me/viruchkaa_bot?start=0012")],
        [InlineKeyboardButton(text="🔄 Обновить ссылки", callback_data="refresh_links")],
    ]
    text = get_invite_links_text(links)
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await bot.send_message(uid, text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        await log_and_report(e, "send_links_message")

@router.callback_query(F.data == "refresh_links")
async def refresh_links(query: CallbackQuery):
    await query.answer("Обновляю ссылки...")
    await send_links_message(query.from_user.id)

@router.my_chat_member()
async def on_bot_status_change(event: ChatMemberUpdated):
    # остальной код без изменений
    pass
