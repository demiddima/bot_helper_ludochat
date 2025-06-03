import logging
import re
import asyncio
import time
from aiogram import Router, F
from aiogram.types import (
    ChatJoinRequest,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    CallbackQuery,
    ChatMemberUpdated
)
from aiogram.enums import ParseMode
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from config import BOT_TOKEN, PUBLIC_CHAT_ID, LOG_CHANNEL_ID, ERROR_LOG_CHANNEL_ID, PRIVATE_DESTINATIONS
from storage import (
    upsert_chat,
    delete_chat,
    add_user_to_chat,
    remove_user_from_chat
)
from utils import log_and_report, join_requests, cleanup_join_requests

from messages import escape_markdown, TERMS_MESSAGE, get_invite_links_text

router = Router()
bot = Bot(token=BOT_TOKEN)
BOT_ID = None  # will be set on startup

@router.startup()
async def on_startup():
    global BOT_ID
    BOT_ID = (await bot.get_me()).id
    # start cleanup task
    asyncio.create_task(cleanup_join_requests())

@router.chat_join_request(F.chat.id == PUBLIC_CHAT_ID)
async def handle_join(update: ChatJoinRequest):
    user = update.from_user
    join_requests[user.id] = time.time()

    bot_username = (await bot.get_me()).username
    payload = f"verify_{user.id}"
    url = f"https://t.me/{bot_username}?start={payload}"

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Я согласен(а) и ознакомлен(а) со всем", url=url)
    ]])

    try:
        await bot.send_message(
            user.id,
            TERMS_MESSAGE,
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logging.info(f"[SEND] Условия отправлены пользователю {user.id}")
    except TelegramForbiddenError as e:
        await log_and_report(e, "handle_join")

@router.message(F.text.startswith("/start"))
async def process_start(message: Message):
    parts = message.text.split()
    if len(parts) == 2 and parts[1].startswith("verify_"):
        try:
            uid = int(parts[1].split("_", 1)[1])
        except ValueError:
            return

        ts = join_requests.get(uid)
        if ts is None or time.time() - ts > 300:
            join_requests.pop(uid, None)
            return await message.reply("❗ Время ожидания прошло. Повторите запрос.", parse_mode="HTML")

        if message.from_user.id == uid:
            join_requests.pop(uid, None)
            try:
                await bot.approve_chat_join_request(PUBLIC_CHAT_ID, uid)
                logging.info(f"[APPROVE] Заявка пользователя {uid} одобрена")
            except TelegramForbiddenError as e:
                await log_and_report(e, "approve_chat_join_request")

            # Ensure chat present
            try:
                chat_obj = await bot.get_chat(PUBLIC_CHAT_ID)
                await upsert_chat(chat_obj.id, chat_obj.title or "", chat_obj.type)
            except Exception as e:
                await log_and_report(e, f"upsert_chat({PUBLIC_CHAT_ID}) in process_start")

            # Add user to chat, wrapped
            try:
                await add_user_to_chat(uid, PUBLIC_CHAT_ID)
            except Exception as e:
                await log_and_report(e, f"add_user_to_chat({uid}, {PUBLIC_CHAT_ID})")

            await send_links_message(uid)
        else:
            await message.reply(
                "❗ Неверная команда. Чтобы пройти верификацию, нажмите «Вступить» в публичном чате и используйте кнопку.",
                parse_mode="HTML"
            )
    else:
        public_chat_url = "https://t.me/ludoochat"
        await message.reply(
            f"Привет! Чтобы пройти верификацию, перейдите в публичный чат по ссылке {public_chat_url} и нажмите «Вступить».",
            parse_mode="HTML"
        )

async def send_links_message(uid: int):
    links = []
    for dest in PRIVATE_DESTINATIONS:
        if not all(k in dest for k in ("title", "chat_id", "description")):
            await log_and_report(Exception(f"Некорректный PRIVATE_DESTINATIONS элемент: {dest}"), "send_links_message")
            continue
        try:
            # Create individual invite link with member_limit=1 and no expiry
            invite = await bot.create_chat_invite_link(
                chat_id=dest["chat_id"],
                member_limit=1,
                creates_join_request=False,
                name=f"Invite for {uid}"
            )
            links.append((dest["title"], invite.invite_link, dest["description"]))
        except TelegramForbiddenError as e:
            await log_and_report(e, f"create_chat_invite_link({uid}, {dest['chat_id']})")
    buttons = [[InlineKeyboardButton(text="Обновить ссылки", callback_data=f"refresh_{uid}")]]
    text = get_invite_links_text(links)
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await bot.send_message(uid, text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        await log_and_report(e, "send_links_message")

@router.callback_query(F.data.startswith("refresh_"))
async def refresh_links(query: CallbackQuery):
    user_id = query.from_user.id
    try:
        _, uid_str = query.data.split("_", 1)
        uid = int(uid_str)
    except ValueError:
        return await query.answer("Неверные данные.")

    if user_id != uid:
        return await query.answer("Это не ваши ссылки.")

    links = []
    for dest in PRIVATE_DESTINATIONS:
        if not all(k in dest for k in ("title", "chat_id", "description")):
            await log_and_report(Exception(f"Некорректный PRIVATE_DESTINATIONS элемент: {dest}"), "refresh_links")
            continue
        try:
            invite = await bot.create_chat_invite_link(
                chat_id=dest["chat_id"],
                member_limit=1,
                creates_join_request=False,
                name=f"Invite for {uid}"
            )
            links.append((dest["title"], invite.invite_link, dest["description"]))
        except TelegramForbiddenError as e:
            await log_and_report(e, f"refresh create_chat_invite_link({uid}, {dest['chat_id']})")

    buttons = [[InlineKeyboardButton(text="Обновить ссылки", callback_data=f"refresh_{uid}")]]
    new_text = get_invite_links_text(links)
    new_markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await query.message.edit_text(new_text, reply_markup=new_markup, parse_mode="HTML", disable_web_page_preview=True)
        await query.answer("Ссылки обновлены.")
    except Exception as e:
        await log_and_report(e, "refresh_links edit_text")

@router.my_chat_member()
async def on_bot_status_change(event: ChatMemberUpdated):
    updated = event.new_chat_member.user
    if updated.id != BOT_ID:
        return

    new_status = event.new_chat_member.status
    chat = event.chat
    if new_status in ("administrator", "creator"):
        try:
            await upsert_chat(chat.id, chat.title or "", chat.type)
        except Exception as e:
            await log_and_report(e, f"upsert_chat({chat.id}) in on_bot_status_change")
    elif new_status in ("left", "kicked"):
        try:
            await delete_chat(chat.id)
        except Exception as e:
            await log_and_report(e, f"delete_chat({chat.id}) in on_bot_status_change")

@router.chat_member()
async def on_user_status_change(event: ChatMemberUpdated):
    updated_user = event.new_chat_member.user
    if updated_user.id == BOT_ID:
        return

    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    chat_id = event.chat.id

    # JOIN
    if old_status in ("left", "kicked") and new_status == "member":
        try:
            await upsert_chat(chat_id, event.chat.title or "", event.chat.type)
        except Exception as e:
            await log_and_report(e, f"upsert_chat({chat_id}) in on_user_status_change")
        try:
            await add_user_to_chat(updated_user.id, chat_id)
        except Exception as e:
            await log_and_report(e, f"add_user_to_chat({updated_user.id}, {chat_id})")
    # LEAVE
    elif new_status in ("left", "kicked"):
        try:
            await remove_user_from_chat(updated_user.id, chat_id)
        except Exception as e:
            await log_and_report(e, f"remove_user_from_chat({updated_user.id}, {chat_id})")
