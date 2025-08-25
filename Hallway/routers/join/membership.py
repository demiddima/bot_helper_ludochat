# handlers/join/membership.py
# Логи без названий функций, только смысл действий. Добавлена обработка приватных чатов.

import asyncio
import logging

from aiogram import Router
from aiogram.types import ChatMemberUpdated
from httpx import HTTPStatusError

from common.utils import cleanup_join_requests, log_and_report, get_bot
from common.utils.time_msk import now_msk_naive
from storage import upsert_chat, add_user, add_membership, remove_membership
from common.db_api_client import db_api_client
import config

router = Router()
tracked_chats: set[int] = set()


async def add_user_and_membership(user, chat_id: int = None):
    """Добавляет/обновляет пользователя и подписку."""
    try:
        await add_user(user.id, user.username or None, user.full_name or None)
        logging.info(
            f"user_id={user.id} – Пользователь сохранён (username={user.username}, full_name={user.full_name})",
            extra={"user_id": user.id}
        )
    except Exception as exc:
        logging.error(f"user_id={user.id} – Ошибка при сохранении пользователя: {exc}", extra={"user_id": user.id})
        await log_and_report(exc, f"add_user user={user.id}")

    if not chat_id:
        chat_id = config.BOT_ID
        logging.info(f"user_id={user.id} – Подписка без chat_id, используем BOT_ID={chat_id}", extra={"user_id": user.id})

    try:
        await add_membership(user.id, chat_id)
        logging.info(f"user_id={user.id} – Подписан на chat={chat_id}", extra={"user_id": user.id})
    except HTTPStatusError as exc:
        logging.warning(
            f"user_id={user.id} – HTTP {exc.response.status_code} при добавлении подписки на chat={chat_id}",
            extra={"user_id": user.id}
        )
        await log_and_report(exc, f"add_membership(user={user.id}, chat={chat_id})")
    except Exception as exc:
        logging.error(
            f"user_id={user.id} – Ошибка при добавлении подписки на chat={chat_id}: {exc}",
            extra={"user_id": user.id}
        )
        await log_and_report(exc, f"add_membership(user={user.id}, chat={chat_id})")


@router.startup()
async def on_startup():
    """Очистка join-requests, регистрация бота и загрузка tracked_chats."""
    asyncio.create_task(cleanup_join_requests())
    bot = get_bot()
    me = await bot.get_me()
    config.BOT_ID = me.id

    global tracked_chats
    try:
        tracked_chats = set(await db_api_client.get_chats())
        logging.info(f"user_id=system – Загружены tracked_chats: {tracked_chats}", extra={"user_id": "system"})
    except Exception as exc:
        logging.error(f"user_id=system – Ошибка загрузки tracked_chats: {exc}", extra={"user_id": "system"})
        await log_and_report(exc, "get_chats")

    try:
        await upsert_chat({
            "id": config.BOT_ID,
            "title": me.username or "bot",
            "type": "private",
            "added_at": now_msk_naive().isoformat(),
        })
        logging.info(f"user_id={config.BOT_ID} – Бот зарегистрирован как private chat", extra={"user_id": config.BOT_ID})
    except Exception as exc:
        logging.error(f"user_id={config.BOT_ID} – Ошибка регистрации бота: {exc}", extra={"user_id": config.BOT_ID})
        await log_and_report(exc, "upsert_chat(bot)")


@router.chat_member()
async def on_chat_member(update: ChatMemberUpdated):
    """Фиксируем изменения статуса пользователя в отслеживаемых чатах."""
    chat_id = update.chat.id
    user = update.new_chat_member.user
    user_id = user.id

    if chat_id not in tracked_chats or user_id == config.BOT_ID:
        return

    status = update.new_chat_member.status
    logging.info(f"user_id={user_id} – status='{status}' в chat={chat_id}", extra={"user_id": user_id})

    try:
        await add_user(user.id, user.username or None, user.full_name or None)
    except Exception as exc:
        logging.error(f"user_id={user_id} – Ошибка add_user: {exc}", extra={"user_id": user_id})
        await log_and_report(exc, f"add_user user={user_id}")

    if status in ("member", "restricted"):
        try:
            await add_membership(user_id, chat_id)
            logging.info(f"user_id={user_id} – Подписан в chat={chat_id}", extra={"user_id": user_id})
        except Exception as exc:
            logging.error(f"user_id={user_id} – Ошибка add_membership: {exc}", extra={"user_id": user_id})
            await log_and_report(exc, f"add_membership user={user_id}, chat={chat_id}")
    elif status in ("left", "kicked"):
        try:
            await remove_membership(user_id, chat_id)
            logging.info(f"user_id={user_id} – Отписан от chat={chat_id}", extra={"user_id": user_id})
        except Exception as exc:
            logging.error(f"user_id={user_id} – Ошибка remove_membership: {exc}", extra={"user_id": user_id})
            await log_and_report(exc, f"remove_membership user={user_id}, chat={chat_id}")


@router.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated):
    """Фиксируем изменения статуса бота и приватные подписки пользователей."""
    chat = update.chat
    status = update.new_chat_member.status

    # приватные чаты = пользователь ↔ бот
    if chat.type == "private":
        user_id = chat.id
        if status in ("member", "creator", "administrator"):
            try:
                await add_membership(user_id, config.BOT_ID)
                logging.info(f"user_id={user_id} – Подписался на бота", extra={"user_id": user_id})
            except Exception as exc:
                logging.error(f"user_id={user_id} – Ошибка подписки на бота: {exc}", extra={"user_id": user_id})
                await log_and_report(exc, f"add_membership bot user={user_id}")
        elif status in ("left", "kicked"):
            # 1) снимаем membership в БД
            try:
                await remove_membership(user_id, config.BOT_ID)
                logging.info(f"user_id={user_id} – Отписался от бота", extra={"user_id": user_id})
            except Exception as exc:
                logging.error(f"user_id={user_id} – Ошибка отписки от бота: {exc}", extra={"user_id": user_id})
                await log_and_report(exc, f"remove_membership bot user={user_id}")

            # 2) удаляем запись user_subscriptions
            try:
                await db_api_client.delete_user_subscriptions(user_id)
                logging.info(f"user_id={user_id} – Подписки удалены (user_subscriptions)", extra={"user_id": user_id})
            except HTTPStatusError as exc:
                # например, если записи уже нет — пусть будет warning
                logging.warning(
                    f"user_id={user_id} – HTTP {exc.response.status_code} при удалении подписок",
                    extra={"user_id": user_id}
                )
                await log_and_report(exc, f"DELETE /subscriptions/{user_id}")
            except Exception as exc:
                logging.error(f"user_id={user_id} – Ошибка удаления подписок: {exc}", extra={"user_id": user_id})
                await log_and_report(exc, f"DELETE /subscriptions/{user_id}")
        return

    # группы/каналы – статус бота
    chat_id = chat.id
    if chat_id not in tracked_chats:
        return

    logging.info(f"user_id={config.BOT_ID} – bot status='{status}' в chat={chat_id}", extra={"user_id": config.BOT_ID})
    if status == "member":
        try:
            await upsert_chat({
                "id": chat_id,
                "title": chat.title or "",
                "type": chat.type,
                "added_at": now_msk_naive().isoformat(),
            })
            await add_membership(config.BOT_ID, chat_id)
            logging.info(f"user_id={config.BOT_ID} – Бот подписан на chat={chat_id}", extra={"user_id": config.BOT_ID})
        except Exception as exc:
            logging.error(f"user_id={config.BOT_ID} – Ошибка подписки бота: {exc}", extra={"user_id": config.BOT_ID})
            await log_and_report(exc, f"bot add_membership chat={chat_id}")
    elif status in ("left", "kicked"):
        try:
            await remove_membership(config.BOT_ID, chat_id)
            logging.info(f"user_id={config.BOT_ID} – Бот отписан от chat={chat_id}", extra={"user_id": config.BOT_ID})
        except Exception as exc:
            logging.error(f"user_id={config.BOT_ID} – Ошибка отписки бота: {exc}", extra={"user_id": config.BOT_ID})
            await log_and_report(exc, f"bot remove_membership chat={chat_id}")
