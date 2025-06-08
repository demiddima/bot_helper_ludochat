# handlers/membership.py
# commit: added membership router to track subscriptions by cached chat list

"""Обработчик подписки/отписки пользователей в чатах и каналах из таблицы chats."""

import logging
from aiogram import Router
from aiogram.types import ChatMemberUpdated
from storage import get_all_chats, add_user_to_chat, remove_user_from_chat
from utils import log_and_report

router = Router()
TRACKED_CHAT_IDS: list[int] = []

@router.startup()
async def load_tracked_chats():
    """Загружаем список chat_id из таблицы chats в кэш при старте бота."""
    global TRACKED_CHAT_IDS
    TRACKED_CHAT_IDS = await get_all_chats()
    logging.info(f"[MEMBERSHIP] Loaded tracked chats: {TRACKED_CHAT_IDS}")

@router.chat_member()
async def handle_membership_change(update: ChatMemberUpdated):
    """Обрабатываем вход/выход в отслеживаемых чатах."""
    chat_id = update.chat.id
    if chat_id not in TRACKED_CHAT_IDS:
        return

    user = update.new_chat_member.user
    status = update.new_chat_member.status

    try:
        if status in ("member", "administrator", "creator"):
            await add_user_to_chat(user.id, chat_id, user.username or "", user.full_name or "")
        elif status in ("left", "kicked"):
            await remove_user_from_chat(user.id, chat_id)
    except Exception as e:
        await log_and_report(e, f"membership_change({user.id},{chat_id})")
