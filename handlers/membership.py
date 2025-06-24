# handlers/membership.py
# commit: changed added_at to use .isoformat() for JSON serialization

"""Обработчик подписки/отписки пользователей в чатах и каналах из таблицы chats."""

import logging
from datetime import datetime

from aiogram import Router
from aiogram.types import ChatMemberUpdated

from storage import get_chats, add_membership, remove_membership, upsert_chat
from utils import log_and_report

router = Router()
TRACKED_CHAT_IDS: list[int] = []

@router.startup()
async def load_tracked_chats():
    """Загружаем список chat_id из таблицы chats в кэш при старте бота."""
    global TRACKED_CHAT_IDS
    try:
        TRACKED_CHAT_IDS = await get_chats()
        logging.info(f"[MEMBERSHIP] Loaded tracked chats: {TRACKED_CHAT_IDS}")
    except Exception as e:
        await log_and_report(e, "load_tracked_chats")

@router.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated):
    """При получении прав администратора или добавлении бота в чат — регистрируем чат в БД."""
    chat = update.chat
    status = update.new_chat_member.status

    if status in ("administrator", "creator"):
        chat_data = {
            "id": chat.id,
            "title": chat.title or "",
            "type": chat.type,
            "added_at": datetime.utcnow().isoformat()  # ← теперь строка ISO
        }
        try:
            await upsert_chat(chat_data)
        except Exception as e:
            await log_and_report(e, f"upsert_chat(chat {chat.id})")

    elif status in ("left", "kicked"):
        # при выходе/выгоне бота из чата удаляем из кэша
        if chat.id in TRACKED_CHAT_IDS:
            TRACKED_CHAT_IDS.remove(chat.id)
        logging.info(f"[MEMBERSHIP] Bot removed from chat {chat.id}")

@router.chat_member()
async def handle_membership_change(update: ChatMemberUpdated):
    """Обрабатываем вход/выход пользователей в отслеживаемых чатах."""
    chat_id = update.chat.id
    if chat_id not in TRACKED_CHAT_IDS:
        return

    user = update.new_chat_member.user
    status = update.new_chat_member.status

    try:
        if status in ("member", "administrator", "creator"):
            await add_membership(user.id, chat_id)
            logging.info(f"[MEMBERSHIP] User {user.id} joined chat {chat_id}")
        elif status in ("left", "kicked"):
            await remove_membership(user.id, chat_id)
            logging.info(f"[MEMBERSHIP] User {user.id} left chat {chat_id}")
    except Exception as e:
        await log_and_report(e, f"membership_change({user.id},{chat_id})")
