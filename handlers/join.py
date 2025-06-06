"""
Обработчик вступления пользователя: перехват ChatJoinRequest и отправка сообщений.
"""

import logging
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

from config import PUBLIC_CHAT_ID, ERROR_LOG_CHANNEL_ID, PRIVATE_DESTINATIONS
from storage import (
    upsert_chat,
    delete_chat,
    add_user_to_chat,
    remove_user_from_chat
)
from utils import log_and_report, join_requests, cleanup_join_requests, get_bot
from messages import escape_html, TERMS_MESSAGE, get_invite_links_text  # HTML-версии

router = Router()

def get_bot_instance():
    return get_bot()

BOT_ID = None

@router.startup()
async def on_startup():
    global BOT_ID
    bot = get_bot_instance()
    BOT_ID = (await bot.get_me()).id
    # Запуск очистки join_requests (если нужна фоновая очистка)
    asyncio.create_task(cleanup_join_requests())

@router.chat_join_request(F.chat.id == PUBLIC_CHAT_ID)
async def handle_join(update: ChatJoinRequest):
    """
    Когда пользователь нажал «Вступить» в публичный чат (PUBLIC_CHAT_ID),
    мы отправляем ему в личку HTML-TERMS_MESSAGE с кнопкой deep-link.
    """
    user = update.from_user
    join_requests[user.id] = time.time()

    bot = get_bot_instance()
    bot_username = (await bot.get_me()).username
    payload = f"verify_{user.id}"
    url = f"https://t.me/{bot_username}?start={payload}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я согласен(а) и ознакомлен(а) со всем", url=url)]
    ])

    try:
        await bot.send_message(
            chat_id=user.id,
            text=TERMS_MESSAGE,
            reply_markup=kb,
            parse_mode="HTML",          # перешли на HTML
            disable_web_page_preview=True
        )
        logging.info(f"[SEND] Условия отправлены пользователю {user.id}")
    except Exception as e:
        await log_and_report(e, "handle_join")

@router.message(F.text.startswith("/start"))
async def process_start(message: Message):
    """
    Когда пользователь переходит по deep-link /start=verify_<user_id>:
    – проверяем таймаут (5 минут),
    – одобряем ChatJoinRequest,
    – сохраняем в БД,
    – шлём приватные ссылки.
    """
    bot = get_bot_instance()
    parts = message.text.split()
    if len(parts) == 2 and parts[1].startswith("verify_"):
        try:
            uid = int(parts[1].split("_", 1)[1])
        except ValueError:
            return

        ts = join_requests.get(uid)
        # Если таймаут вышел — отпишем и предложим попробовать снова
        if ts is None or time.time() - ts > 300:
            join_requests.pop(uid, None)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Лудочат · Переходник", url="https://t.me/ludoochat")]
            ])
            return await message.reply(
                "⏰ Время ожидания вышло. Повторите вступление через "
                "<a href=\"https://t.me/ludoochat\">Лудочат · Переходник</a>.",
                reply_markup=kb,
                parse_mode="HTML",       # HTML вместо Markdown
                disable_web_page_preview=True
            )

        # Только тот же самый пользователь может подтвердить свою заявку
        if message.from_user.id == uid:
            join_requests.pop(uid, None)
            try:
                # Одобряем заявку в публичный чат
                await bot.approve_chat_join_request(PUBLIC_CHAT_ID, uid)
                logging.info(f"[APPROVE] Заявка пользователя {uid} одобрена")
            except Exception as e:
                await log_and_report(e, "approve_chat_join_request")

            # Получаем информацию о чате и сохраняем/обновляем
            try:
                chat_obj = await bot.get_chat(PUBLIC_CHAT_ID)
                await upsert_chat(chat_obj.id, chat_obj.title or "", chat_obj.type)
            except Exception as e:
                await log_and_report(e, f"upsert_chat({PUBLIC_CHAT_ID}) in process_start")

            user = message.from_user
            try:
                await add_user_to_chat(uid, PUBLIC_CHAT_ID, user.username, user.full_name)
            except Exception as e:
                await log_and_report(e, f"add_user_to_chat({uid}, {PUBLIC_CHAT_ID})")

            # Шлём приватные ссылки в личку
            await send_links_message(uid)
        else:
            # Если кто-то другой написал /start verify_<uid>
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Лудочат · Переходник", url="https://t.me/ludoochat")]
            ])
            await message.reply(
                "Чтобы пройти верификацию, нажмите «Вступить» в "
                "<a href=\"https://t.me/ludoochat\">Лудочат · Переходник</a>.",
                reply_markup=kb,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
    else:
        # Обычный /start без параметра, просто даём ссылку-приглашение
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Лудочат · Переходник", url="https://t.me/ludoochat")]
        ])
        await message.reply(
            "Привет! Чтобы пройти верификацию, перейдите в "
            "<a href=\"https://t.me/ludoochat\">Лудочат · Переходник</a> и нажмите «Вступить».",
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True
        )

async def send_links_message(uid: int):
    """
    Генерирует приватные invite-ссылки и отправляет их пользователю.
    """
    bot = get_bot_instance()
    links = []
    for dest in PRIVATE_DESTINATIONS:
        try:
            invite = await bot.create_chat_invite_link(
                chat_id=dest["chat_id"],
                member_limit=1,
                creates_join_request=False,
                name=f"Invite for {uid}"
            )
            links.append((dest["title"], invite.invite_link, dest["description"]))
        except Exception as e:
            await log_and_report(e, f"create_chat_invite_link({uid}, {dest.get('chat_id')})")

    buttons = [
        [InlineKeyboardButton(text="Лудочат", url="https://t.me/ludoochat")],
        [InlineKeyboardButton(text="Выручат", url="https://t.me/viruchkaa_bot?start=0012")],
        [InlineKeyboardButton(text="Обновить ссылки", callback_data=f"refresh_{uid}")]
    ]
    text = get_invite_links_text(links)
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await bot.send_message(
            chat_id=uid,
            text=text,
            reply_markup=markup,
            parse_mode="HTML",            # HTML для ссылок и форматирования
            disable_web_page_preview=True
        )
    except Exception as e:
        await log_and_report(e, "send_links_message")

@router.callback_query(F.data.startswith("refresh_"))
async def refresh_links(query: CallbackQuery):
    """
    Когда пользователь нажал «Обновить ссылки» – генерируем и отправляем заново.
    """
    bot = get_bot_instance()
    user_id = query.from_user.id
    try:
        _, uid_str = query.data.split("_", 1)
        uid = int(uid_str)
    except ValueError:
        return await query.answer("Неверные данные.")

    if user_id != uid:
        return await query.answer("Это не ваши ссылки.")

    await query.answer("Генерирую новые ссылки...")
    try:
        await send_links_message(uid)
    except Exception as e:
        await log_and_report(e, "refresh_links send_links_message")

@router.my_chat_member()
async def on_bot_status_change(event: ChatMemberUpdated):
    """
    Обрабатывает изменение статуса бота в чатах – сохраняем/удаляем чат в БД.
    """
    bot = get_bot_instance()
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
    """
    Обрабатывает добавление/удаление любого пользователя из чата (кроме бота).
    """
    bot = get_bot_instance()
    updated_user = event.new_chat_member.user
    if updated_user.id == BOT_ID:
        return

    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    chat_id = event.chat.id

    if old_status in ("left", "kicked") and new_status == "member":
        try:
            await upsert_chat(chat_id, event.chat.title or "", event.chat.type)
        except Exception as e:
            await log_and_report(e, f"upsert_chat({chat_id}) in on_user_status_change")
        try:
            await add_user_to_chat(updated_user.id, chat_id,
                                   updated_user.username, updated_user.full_name)
        except Exception as e:
            await log_and_report(e, f"add_user_to_chat({updated_user.id}, {chat_id})")
    elif new_status in ("left", "kicked"):
        try:
            await remove_user_from_chat(updated_user.id, chat_id)
        except Exception as e:
            await log_and_report(e, f"remove_user_from_chat({updated_user.id}, {chat_id})")
