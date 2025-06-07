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
    ChatMemberUpdated
)
from aiogram.exceptions import TelegramForbiddenError, TelegramAPIError

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
BOT_ID: int | None = None  # ID самого бота-секретаря
_last_refresh: dict[int, float] = {}  # rate-limit «обновить ссылки»

@router.startup()
async def on_startup() -> None:
    """Запоминаем ID бота и запускаем фоновую очистку заявок."""
    global BOT_ID
    bot = get_bot()
    bot_info = await bot.get_me()
    BOT_ID = bot_info.id
    try:
        await upsert_chat(BOT_ID, bot_info.username or "", "bot")
    except Exception as e:
        await log_and_report(e, f"upsert_chat({BOT_ID})")
    asyncio.create_task(cleanup_join_requests())

@router.chat_join_request(F.chat.id == PUBLIC_CHAT_ID)
async def handle_join(update: ChatJoinRequest) -> None:
    uid = update.from_user.id
    join_requests[uid] = time.time()
    bot = get_bot()
    bot_username = (await bot.get_me()).username or ""
    url = f"https://t.me/{bot_username}?start=verify_{uid}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Я согласен(а) и ознакомлен(а) со всем",
            url=url
        )
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
    except TelegramForbiddenError:
        # Пользователь заблокировал бота до начала верификации
        await remove_user_from_chat(uid, BOT_ID)
    except TelegramAPIError as e:
        await log_and_report(e, f"handle_join({uid})")

@router.message(F.text.startswith("/start"))
async def process_start(message: Message) -> None:
    bot = get_bot()
    # fallback: subscribe user to bot on any /start
    user = message.from_user
    try:
        await add_user_to_chat(user.id, BOT_ID, user.username or "", user.full_name or "")
    except Exception as e:
        await log_and_report(e, f"add_user_to_chat({user.id}, BOT_ID)")

    parts = message.text.split()
    if len(parts) != 2 or not parts[1].startswith("verify_"):
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text="Лудочат · Переходник", url="https://t.me/ludoochat"
        )]])
        return await message.reply(
            "Привет! Чтобы пройти верификацию, перейдите в <a href=\"https://t.me/ludoochat\">Лудочат · Переходник</a> и нажмите «Вступить».",
            reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True
        )
    try:
        uid = int(parts[1].split("_", 1)[1])
    except ValueError:
        return
    ts = join_requests.get(uid)
    if ts is None or time.time() - ts > 300:
        join_requests.pop(uid, None)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text="Лудочат · Переходник", url="https://t.me/ludoochat"
        )]])
        return await message.reply(
            "⏰ Время ожидания вышло. Повторите вступление через <a href=\"https://t.me/ludoochat\">Лудочат · Переходник</a>.",
            reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True
        )
    if message.from_user.id == uid:
        join_requests.pop(uid, None)
        try:
            await bot.approve_chat_join_request(PUBLIC_CHAT_ID, uid)
            logging.info(f"[APPROVE] {uid}")
        except TelegramAPIError as e:
            await log_and_report(e, f"approve({uid})")
        try:
            chat = await bot.get_chat(PUBLIC_CHAT_ID)
            await upsert_chat(chat.id, chat.title or "", chat.type)
            user = message.from_user
            await add_user_to_chat(user.id, PUBLIC_CHAT_ID, user.username or "", user.full_name or "")
            await add_user_to_chat(user.id, BOT_ID, user.username or "", user.full_name or "")
        except Exception as e:
            await log_and_report(e, f"db_user({uid})")
        await send_links_message(uid)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="Лудочат · Переходник", url="https://t.me/ludoochat"
    )]])
    await message.reply(
        "Чтобы пройти верификацию, нажмите «Вступить» в <a href=\"https://t.me/ludoochat\">Лудочат · Переходник</a>.",
        reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True
    )

async def send_links_message(uid: int) -> None:
    bot = get_bot()
    now = time.time()
    if now - _last_refresh.get(uid, 0) < 60:
        return
    _last_refresh[uid] = now
    for chat_id, link in await get_valid_invite_links(uid):
        try:
            await bot.revoke_chat_invite_link(chat_id=chat_id, invite_link=link)
        except TelegramAPIError as e:
            logging.warning(f"Revoke failed {link}: {e}")
    await delete_invite_links(uid)
    expire_ts = int((datetime.utcnow() + timedelta(days=1)).timestamp())
    links = []
    for dest in PRIVATE_DESTINATIONS:
        cid = dest["chat_id"]
        try:
            invite = await bot.create_chat_invite_link(
                chat_id=cid, member_limit=1, creates_join_request=False,
                name=f"Invite for {uid}", expire_date=expire_ts
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
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = get_invite_links_text(links)
    try:
        await bot.send_message(uid, text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramForbiddenError:
            await remove_user_from_chat(uid, BOT_ID)
    except TelegramAPIError as e:
            await log_and_report(e, f"send_links({uid})")

@router.callback_query(F.data.startswith("refresh_"))
async def refresh_links(query: CallbackQuery) -> None:
    await query.answer("Обновляю...")
    try:
        _, uid_str = query.data.split("_", 1)
        uid = int(uid_str)
    except Exception:
        return await query.answer("Неверные данные.")
    if query.from_user.id != uid:
        return await query.answer("Это не ваши ссылки.")
    await send_links_message(uid)

@router.chat_member()
async def on_chat_member_update(update: ChatMemberUpdated) -> None:
    """Удаляем запись, когда пользователь выходит из чата."""
    if update.new_chat_member.status in ("left", "kicked"):
        user_id = update.from_user.id
        chat_id = update.chat.id
        try:
            await remove_user_from_chat(user_id, chat_id)
        except Exception as e:
            await log_and_report(e, f"remove_user_from_chat({user_id}, {chat_id})")

@router.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated) -> None:
    """Удаляем подписку, когда пользователь блокирует бота."""
    if update.new_chat_member.status in ("left", "kicked"):
        user_id = update.from_user.id
        try:
            await remove_user_from_chat(user_id, BOT_ID)
        except Exception as e:
            await log_and_report(e, f"remove_user_from_chat({user_id}, {BOT_ID})")


@router.my_chat_member()
async def on_my_chat_member_add(update: ChatMemberUpdated) -> None:
    """Добавляем запись, когда пользователь вновь подписывается на бота."""
    if update.new_chat_member.status == "member":
        user_id = update.from_user.id
        try:
            await add_user_to_chat(
                user_id,
                BOT_ID,
                update.from_user.username or "",
                update.from_user.full_name or ""
            )
        except Exception as e:
            await log_and_report(e, f"add_user_to_chat({user_id}, BOT_ID)")