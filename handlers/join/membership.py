# membership.py
# Корпоративный стиль логирования: [function] – user_id=… – описание, try/except для всех рисковых операций

import asyncio
import logging
from datetime import datetime

from aiogram import Router
from aiogram.types import ChatMemberUpdated
from httpx import HTTPStatusError

from utils import cleanup_join_requests, log_and_report, get_bot
from storage import upsert_chat, add_user, add_membership, remove_membership
from services.db_api_client import db_api_client
import config

router = Router()
tracked_chats: set[int] = set()

async def add_user_and_membership(user, chat_id: int = None):
    """
    Добавляет или обновляет пользователя в БД и оформляет подписку.
    Если chat_id не передан — подписывает на личные уведомления (BOT_ID).
    Вызывается из start.py.
    """
    func_name = "add_user_and_membership"
    try:
        await add_user(
            user.id,
            user.username or None,
            user.full_name or None,
        )
        logging.info(
            f"[{func_name}] – user_id={user.id} – Пользователь добавлен в БД username={user.username}, full_name={user.full_name}",
            extra={"user_id": user.id}
        )
    except Exception as exc:
        logging.error(
            f"[{func_name}] – user_id={user.id} – Ошибка add_user: {exc}",
            extra={"user_id": user.id}
        )
        await log_and_report(exc, f"{func_name} add_user user={user.id}")

    if not chat_id:
        logging.warning(
            f"[{func_name}] – user_id={user.id} – chat_id не передан, используем BOT_ID={config.BOT_ID}",
            extra={"user_id": user.id}
        )
        chat_id = config.BOT_ID

    if not chat_id:
        logging.error(
            f"[{func_name}] – user_id={user.id} – Нет chat_id, пропускаем add_membership",
            extra={"user_id": user.id}
        )
        return

    try:
        await add_membership(user.id, chat_id)
        logging.info(
            f"[{func_name}] – user_id={user.id} – Подписан на chat={chat_id}",
            extra={"user_id": user.id}
        )
    except HTTPStatusError as exc:
        logging.warning(
            f"[{func_name}] – user_id={user.id} – HTTP {exc.response.status_code} при add_membership(chat={chat_id})",
            extra={"user_id": user.id}
        )
        await log_and_report(exc, f"{func_name} add_membership(user={user.id}, chat={chat_id})")
    except Exception as exc:
        logging.error(
            f"[{func_name}] – user_id={user.id} – Ошибка add_membership(chat={chat_id}): {exc}",
            extra={"user_id": user.id}
        )
        await log_and_report(exc, f"{func_name} add_membership(user={user.id}, chat={chat_id})")


@router.startup()
async def on_startup():
    """
    Запускаем фоновую очистку, регистрируем бота и загружаем трек-лист чатов.
    """
    func_name = "on_startup"
    asyncio.create_task(cleanup_join_requests())
    bot = get_bot()
    me = await bot.get_me()
    config.BOT_ID = me.id

    global tracked_chats
    try:
        tracked_chats = set(await db_api_client.get_chats())
        logging.info(
            f"[{func_name}] – user_id=system – Загружены tracked_chats: {tracked_chats}",
            extra={"user_id": "system"}
        )
    except Exception as exc:
        logging.error(
            f"[{func_name}] – user_id=system – Ошибка при загрузке tracked_chats: {exc}",
            extra={"user_id": "system"}
        )
        await log_and_report(exc, f"{func_name} get_chats")

    try:
        await upsert_chat({
            "id": config.BOT_ID,
            "title": me.username or "bot",
            "type": "private",
            "added_at": datetime.utcnow().isoformat(),
        })
        logging.info(
            f"[{func_name}] – user_id={config.BOT_ID} – Бот зарегистрирован в БД как private chat",
            extra={"user_id": config.BOT_ID}
        )
    except Exception as exc:
        logging.error(
            f"[{func_name}] – user_id={config.BOT_ID} – Ошибка upsert_chat(bot): {exc}",
            extra={"user_id": config.BOT_ID}
        )
        await log_and_report(exc, f"{func_name} upsert_chat(bot)")


@router.chat_member()
async def on_chat_member(update: ChatMemberUpdated):
    """
    Единый хендлер для входа/выхода/ограничений пользователей в отслеживаемых чатах.
    По status='restricted' лишь фиксируем факт захода (add_membership) и логируем.
    """
    func_name = "on_chat_member"
    chat_id = update.chat.id
    new_member = update.new_chat_member.user
    user_id = new_member.id

    if chat_id not in tracked_chats or user_id == config.BOT_ID:
        return

    status = update.new_chat_member.status
    logging.info(
        f"[{func_name}] – user_id={user_id} – Получен status='{status}' для chat={chat_id}",
        extra={"user_id": user_id}
    )

    # 1) ensure user exists
    try:
        await add_user(
            new_member.id,
            new_member.username or None,
            new_member.full_name or None,
        )
    except Exception as exc:
        logging.error(
            f"[{func_name}] – user_id={user_id} – Ошибка add_user: {exc}",
            extra={"user_id": user_id}
        )
        await log_and_report(exc, f"{func_name} add_user user={user_id}")

    # 2) логика по статусу
    if status == "restricted":
        try:
            await add_membership(user_id, chat_id)
            logging.info(
                f"[{func_name}] – user_id={user_id} – Фиксирован restricted в chat={chat_id}",
                extra={"user_id": user_id}
            )
        except Exception as exc:
            logging.error(
                f"[{func_name}] – user_id={user_id} – Ошибка при фиксации restricted: {exc}",
                extra={"user_id": user_id}
            )
            await log_and_report(exc, f"{func_name} add_membership restricted user={user_id}, chat={chat_id}")

    elif status == "member":
        try:
            await add_membership(user_id, chat_id)
            logging.info(
                f"[{func_name}] – user_id={user_id} – Присоединился к chat={chat_id}",
                extra={"user_id": user_id}
            )
        except Exception as exc:
            logging.error(
                f"[{func_name}] – user_id={user_id} – Ошибка add_membership: {exc}",
                extra={"user_id": user_id}
            )
            await log_and_report(exc, f"{func_name} add_membership member user={user_id}, chat={chat_id}")

    elif status in ("left", "kicked"):
        try:
            await remove_membership(user_id, chat_id)
            logging.info(
                f"[{func_name}] – user_id={user_id} – Отписался от chat={chat_id}",
                extra={"user_id": user_id}
            )
        except Exception as exc:
            logging.error(
                f"[{func_name}] – user_id={user_id} – Ошибка remove_membership: {exc}",
                extra={"user_id": user_id}
            )
            await log_and_report(exc, f"{func_name} remove_membership user={user_id}, chat={chat_id}")

@router.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated):
    """
    Отслеживаем изменение статуса бота.
    """
    func_name = "on_my_chat_member"
    chat_id = update.chat.id
    new_member = update.new_chat_member.user
    status = update.new_chat_member.status

    if new_member.id != config.BOT_ID or (chat_id not in tracked_chats and chat_id != config.BOT_ID):
        return

    logging.info(
        f"[{func_name}] – user_id={config.BOT_ID} – bot status '{status}' in chat={chat_id}",
        extra={"user_id": config.BOT_ID}
    )
    if status == "member":
        try:
            await upsert_chat({
                "id": chat_id,
                "title": update.chat.title or "",
                "type": update.chat.type,
                "added_at": datetime.utcnow().isoformat(),
            })
            await add_membership(config.BOT_ID, chat_id)
            logging.info(
                f"[{func_name}] – user_id={config.BOT_ID} – Бот подписан на chat={chat_id}",
                extra={"user_id": config.BOT_ID}
            )
        except Exception as exc:
            logging.error(
                f"[{func_name}] – user_id={config.BOT_ID} – Ошибка bot add_membership: {exc}",
                extra={"user_id": config.BOT_ID}
            )
            await log_and_report(exc, f"{func_name} bot add_membership chat={chat_id}")
    elif status in ("left", "kicked"):
        try:
            await remove_membership(config.BOT_ID, chat_id)
            logging.info(
                f"[{func_name}] – user_id={config.BOT_ID} – Бот отписался от chat={chat_id}",
                extra={"user_id": config.BOT_ID}
            )
        except Exception as exc:
            logging.error(
                f"[{func_name}] – user_id={config.BOT_ID} – Ошибка bot remove_membership: {exc}",
                extra={"user_id": config.BOT_ID}
            )
            await log_and_report(exc, f"{func_name} bot remove_membership chat={chat_id}")
