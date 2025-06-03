import logging
import re
from aiogram import Router, F
from aiogram.types import ChatJoinRequest, InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from aiogram.enums import ParseMode
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from config import BOT_TOKEN, PUBLIC_CHAT_ID, LOG_CHANNEL_ID, ERROR_LOG_CHANNEL_ID, PRIVATE_DESTINATIONS
from storage import add_user, verify_user
from messages import escape_markdown, TERMS_MESSAGE, get_invite_links_text

router = Router()
bot = Bot(token=BOT_TOKEN)
join_requests: dict[int, ChatJoinRequest] = {}

@router.chat_join_request(F.chat.id == PUBLIC_CHAT_ID)
async def handle_join(update: ChatJoinRequest):
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
            f"{escape_markdown(user.full_name)} (@{escape_markdown(user.username or '')}, ID: `{user.id}`): "
            f"{escape_markdown(str(e))}"
        )
        logging.warning(f"[FAIL] {msg}")
        try:
            await bot.send_message(ERROR_LOG_CHANNEL_ID, msg, parse_mode="HTML")
        except Exception as log_e:
            logging.error(f"[FAIL] Не удалось отправить лог: {log_e}")

@router.message(F.text.startswith("/start"))
async def process_start(message: Message):
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
                except Exception as log_e:
                    logging.error(f"[FAIL] Не удалось отправить лог: {log_e}")

            user = message.from_user
            try:
                await add_user(uid, user.username, user.full_name)
            except Exception as e:
                log_msg = f"Ошибка добавления в БД {uid}: {escape_markdown(str(e))}"
                logging.error(f"[DB ERROR] {log_msg}")
                try:
                    await bot.send_message(ERROR_LOG_CHANNEL_ID, log_msg, parse_mode="HTML")
                except Exception as log_e:
                    logging.error(f"[FAIL] Не удалось отправить лог: {log_e}")

            # Generate and send initial links message
            await send_links_message(uid)
        else:
            await message.reply(
                "❗ Неверная команда. Чтобы пройти верификацию, нажмите «Вступить» в публичном чате и "
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
            try:
                await verify_user(uid, invite.invite_link)
            except Exception as e:
                log_msg = f"Ошибка обновления invite_link {uid}: {escape_markdown(str(e))}"
                logging.error(f"[DB ERROR] {log_msg}")
                try:
                    await bot.send_message(ERROR_LOG_CHANNEL_ID, log_msg, parse_mode="HTML")
                except Exception as log_e:
                    logging.error(f"[FAIL] Не удалось отправить лог: {log_e}")

            links.append((dest["title"], invite.invite_link, dest["description"]))
        except TelegramForbiddenError as e:
            log_msg = f"Не удалось создать invite link для {uid} в чате {dest['chat_id']}: {escape_markdown(str(e))}"
            logging.warning(f"[FAIL] {log_msg}")
            try:
                await bot.send_message(ERROR_LOG_CHANNEL_ID, log_msg, parse_mode="HTML")
            except Exception as log_e:
                logging.error(f"[FAIL] Не удалось отправить лог: {log_e}")

    # Add refresh button
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
            try:
                await verify_user(uid, invite.invite_link)
            except:
                pass
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
