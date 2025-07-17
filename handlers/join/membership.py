import asyncio
import logging
from datetime import datetime

from aiogram import Router
from aiogram.types import ChatMemberUpdated
from httpx import HTTPStatusError

from utils import cleanup_join_requests, log_and_report, get_bot
from storage import upsert_chat, add_user, add_membership, remove_membership

router = Router()
BOT_ID: int | None = None

@router.startup()
async def on_startup():
    """
    Запускаем фоновую очистку и регистрируем бота в БД.
    """
    asyncio.create_task(cleanup_join_requests())
    global BOT_ID
    bot = get_bot()
    me = await bot.get_me()
    BOT_ID = me.id
    try:
        await upsert_chat({
            "id": BOT_ID,
            "title": me.username or "bot",
            "type": "private",
            "added_at": datetime.utcnow().isoformat(),
        })
    except Exception as exc:
        await log_and_report(exc, "upsert_chat(bot)")

async def add_user_and_membership(user, chat_id):
    """
    Добавляем пользователя и membership.
    Если chat_id не задан, используем глобальный BOT_ID.
    Ошибки 422 и другие логируем через log_and_report, но не кидаем дальше.
    """
    # 1) Добавляем самого пользователя
    await add_user({
        "id": user.id,
        "username": user.username or None,
        "full_name": user.full_name or None,
    })

    # 2) Добавляем membership
    if not chat_id:
        logging.warning(f"[MEMBERSHIP] chat_id не передан, используем BOT_ID={BOT_ID!r}")
        chat_id = BOT_ID
    if not chat_id:
        logging.error(f"[MEMBERSHIP] нет chat_id, пропускаем add_membership для user {user.id}")
        return

    try:
        await add_membership(user.id, chat_id)
    except HTTPStatusError as exc:
        logging.warning(f"[MEMBERSHIP] HTTP 422 при add_membership(user={user.id}, chat={chat_id}): {exc}")
        await log_and_report(exc, f"add_membership(user={user.id}, chat={chat_id})")
    except Exception as exc:
        logging.exception(f"[MEMBERSHIP] Unexpected error при add_membership(user={user.id}, chat={chat_id}): {exc}")
        await log_and_report(exc, f"add_membership(user={user.id}, chat={chat_id})")

@router.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated):
    """
    Если пользователь вышел или был кикнут, удаляем его membership.
    """
    status = update.new_chat_member.status
    if status in ("left", "kicked"):
        uid = update.from_user.id
        try:
            await remove_membership(uid, BOT_ID)
            logging.info(f"[MEMBERSHIP] Removed membership: user {uid} → bot {BOT_ID}")
        except Exception as exc:
            logging.warning(f"[MEMBERSHIP] Failed to remove: {exc}")
