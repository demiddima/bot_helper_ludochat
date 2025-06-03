import logging
import re
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
from messages import escape_markdown, TERMS_MESSAGE, get_invite_links_text

router = Router()
bot = Bot(token=BOT_TOKEN)
join_requests: dict[int, ChatJoinRequest] = {}

@router.chat_join_request(F.chat.id == PUBLIC_CHAT_ID)
async def handle_join(update: ChatJoinRequest):
    """
    Когда пользователь нажимает «Вступить» в публичном чате,
    мы сохраняем его запрос и отправляем ему условие с кнопкой «✅ Я согласен».
    """
    user = update.from_user
    join_requests[user.id] = update

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
        msg = (
            f"Не удалось отправить ЛС пользователю "
            f"{escape_markdown(user.full_name)} "
            f"(@{escape_markdown(user.username or '')}, ID: `{user.id}`): "
            f"{escape_markdown(str(e))}"
        )
        logging.warning(f"[FAIL] {msg}")
        try:
            await bot.send_message(ERROR_LOG_CHANNEL_ID, msg, parse_mode="HTML")
        except Exception:
            logging.error("[ERROR LOG] Не удалось отправить лог об ошибке handle_join")

@router.message(F.text.startswith("/start"))
async def process_start(message: Message):
    """
    Когда пользователь переходит в бота по кнопке '✅ Я согласен',
    сюда приходит команда '/start verify_<user_id>'.
    Если всё верно, мы одобряем заявку и добавляем пользователя в публичный чат,
    а после — сразу фиксируем его в таблице user_memberships.
    """
    parts = message.text.split()
    if len(parts) == 2 and parts[1].startswith("verify_"):
        try:
            uid = int(parts[1].split("_", 1)[1])
        except ValueError:
            return

        if message.from_user.id == uid and uid in join_requests:
            join_requests.pop(uid)

            try:
                await bot.approve_chat_join_request(PUBLIC_CHAT_ID, uid)
                logging.info(f"[APPROVE] Заявка пользователя {uid} одобрена")
            except TelegramForbiddenError as e:
                log_msg = (
                    f"Не удалось одобрить заявку {uid}: {escape_markdown(str(e))}"
                )
                logging.warning(f"[FAIL] {log_msg}")
                try:
                    await bot.send_message(ERROR_LOG_CHANNEL_ID, log_msg, parse_mode="HTML")
                except Exception:
                    logging.error("[FAIL] Не удалось отправить лог об ошибке approve_chat_join_request")

            # Сначала убедимся, что chat есть в таблице
            try:
                chat_obj = await bot.get_chat(PUBLIC_CHAT_ID)
                await upsert_chat(chat_obj.id, chat_obj.title or "", chat_obj.type)
            except Exception as e:
                logging.error(f"[DB ERROR] Не удалось upsert_chat для {PUBLIC_CHAT_ID}: {e}")

            try:
                await add_user_to_chat(uid, PUBLIC_CHAT_ID)
            except Exception as e:
                log_msg = f"Ошибка add_user_to_chat({uid}, {PUBLIC_CHAT_ID}): {escape_markdown(str(e))}"
                logging.error(f"[DB ERROR] {log_msg}")
                try:
                    await bot.send_message(ERROR_LOG_CHANNEL_ID, log_msg, parse_mode="HTML")
                except Exception:
                    logging.error("[FAIL] Не удалось отправить лог об ошибке add_user_to_chat")

            await send_links_message(uid)
        else:
            await message.reply(
                "❗ Неверная команда. Чтобы пройти верификацию, "
                "нажмите «Вступить» в публичном чате и "
                "используйте полученную кнопку «✅ Я согласен(а) и ознакомлен(а) со всем».",
                parse_mode="HTML"
            )
    else:
        public_chat_url = "https://t.me/ludoochat"
        await message.reply(
            f"Привет! Чтобы пройти верификацию, перейдите в публичный чат по ссылке {public_chat_url} и нажмите «Вступить». "
            "Там вы получите кнопку «✅ Я согласен(а) и ознакомлен(а) со всем».",
            parse_mode="HTML"
        )

async def send_links_message(uid: int):
    links = []
    for dest in PRIVATE_DESTINATIONS:
        if not all(k in dest for k in ("title", "chat_id", "description")):
            logging.error(f"[CONFIG ERROR] Некорректный элемент PRIVATE_DESTINATIONS: {dest}")
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
            log_msg = f"Не удалось создать invite link для {uid} в чате {dest['chat_id']}: {escape_markdown(str(e))}"
            logging.warning(f"[FAIL] {log_msg}")
            try:
                await bot.send_message(ERROR_LOG_CHANNEL_ID, log_msg, parse_mode="HTML")
            except Exception:
                logging.error("[FAIL] Не удалось отправить лог об ошибке create_chat_invite_link")

    buttons = [[InlineKeyboardButton(text="Обновить ссылки", callback_data=f"refresh_{uid}")]]
    text = get_invite_links_text(links)
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await bot.send_message(uid, text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)
        logging.info(f"[SEND LINKS] Ссылки отправлены пользователю {uid}")
    except Exception as e:
        logging.error(f"[FAIL SEND LINKS] {e}")

@router.callback_query(F.data.startswith("refresh_"))
async def refresh_links(query: CallbackQuery):
    user_id = query.from_user.id
    data = query.data
    try:
        _, uid_str = data.split("_", 1)
        uid = int(uid_str)
    except ValueError:
        await query.answer("Неверные данные.")
        return

    if user_id != uid:
        await query.answer("Это не ваши ссылки.")
        return

    links = []
    for dest in PRIVATE_DESTINATIONS:
        if not all(k in dest for k in ("title", "chat_id", "description")):
            continue
        try:
            invite = await bot.create_chat_invite_link(
                chat_id=dest["chat_id"],
                member_limit=1,
                creates_join_request=False,
                name=f"Invite for {uid}"
            )
            links.append((dest["title"], invite.invite_link, dest["description"]))
        except:
            pass

    buttons = [[InlineKeyboardButton(text="Обновить ссылки", callback_data=f"refresh_{uid}")]]
    new_text = get_invite_links_text(links)
    new_markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await query.message.edit_text(new_text, reply_markup=new_markup, parse_mode="HTML", disable_web_page_preview=True)
        await query.answer("Ссылки обновлены.")
        logging.info(f"[REFRESH LINKS] Ссылки обновлены для пользователя {uid}")
    except Exception as e:
        logging.error(f"[FAIL REFRESH] {e}")

@router.my_chat_member()
async def on_bot_status_change(event: ChatMemberUpdated):
    updated = event.new_chat_member.user
    bot_info = await bot.get_me()
    if updated.id != bot_info.id:
        return

    new_status = event.new_chat_member.status
    chat = event.chat
    if new_status in ("administrator", "creator"):
        await upsert_chat(chat.id, chat.title or "", chat.type)
    elif new_status in ("left", "kicked"):
        await delete_chat(chat.id)

@router.chat_member()
async def on_user_status_change(event: ChatMemberUpdated):
    updated_user = event.new_chat_member.user
    bot_info = await bot.get_me()
    if updated_user.id == bot_info.id:
        return

    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    chat_id = event.chat.id

    if old_status in ("left", "kicked") and new_status == "member":
        await add_user_to_chat(updated_user.id, chat_id)
    elif new_status in ("left", "kicked"):
        await remove_user_from_chat(updated_user.id, chat_id)
