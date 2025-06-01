\
# handlers/join.py
import logging
import re
from aiogram import Router, F
from aiogram.types import ChatJoinRequest, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from config import BOT_TOKEN, PUBLIC_CHAT_ID, LOG_CHANNEL_ID, ERROR_LOG_CHANNEL_ID, PRIVATE_DESTINATIONS
from storage import add_user, verify_user

router = Router()
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
join_requests: dict[int, ChatJoinRequest] = {}

def escape_markdown(text: str) -> str:
    # Экранируем специальные символы Markdown, чтобы избежать ошибок парсинга.
    return re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', text or "")

@router.chat_join_request(F.chat.id == PUBLIC_CHAT_ID)
async def handle_join(update: ChatJoinRequest):
    user = update.from_user
    join_requests[user.id] = update

    text = (
        "Нажимая кнопку, вы подтверждаете, что:\n\n"
        "– вы не бот\n"
        "– ознакомлены с Офертой\n"
        "– согласны на обработку ПД\n"
        "– вам исполнилось 18 лет\n\n"
        "Чат — не медицинское сообщество. "
        "Общение не заменяет лечение, это лишь поддержка. "
        "Если вам тяжело — обратитесь к специалистам.\n"
        "Вы ответственны за последствия применения любой информации."
    )

    bot_username = (await bot.get_me()).username
    payload = f"verify_{user.id}"
    url = f"https://t.me/{bot_username}?start={payload}"

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Я согласен(а) и ознакомлен(а) со всем", url=url)
    ]])

    try:
        await bot.send_message(user.id, text, reply_markup=kb)
        logging.info(f"[SEND] Условия отправлены пользователю {user.id}")
    except TelegramForbiddenError as e:
        # Логируем и посылаем уведомление в ERROR_LOG_CHANNEL_ID
        msg = (
            f"Не удалось отправить ЛС с условиями пользователю "
            f"{escape_markdown(user.full_name)} (@{escape_markdown(user.username or '')}, ID: `{user.id}`): "
            f"{escape_markdown(str(e))}"
        )
        logging.warning(f"[FAIL] {msg}")
        try:
            await bot.send_message(ERROR_LOG_CHANNEL_ID, msg, parse_mode=ParseMode.MARKDOWN)
        except Exception as log_e:
            logging.error(f"[FAIL] Не удалось отправить лог в канал ошибок: {log_e}")

@router.message(F.text.startswith("/start"))
async def process_start(message: Message):
    parts = message.text.split()
    if len(parts) == 2 and parts[1].startswith("verify_"):
        try:
            uid = int(parts[1].split("_", 1)[1])
        except ValueError:
            return

        if message.from_user.id == uid and uid in join_requests:
            request = join_requests.pop(uid)

            # Одобряем заявку
            try:
                await bot.approve_chat_join_request(PUBLIC_CHAT_ID, uid)
                logging.info(f"[APPROVE] Заявка пользователя {uid} одобрена")
            except TelegramForbiddenError as e:
                log_msg = (
                    f"Не удалось одобрить заявку пользователя {uid}: {escape_markdown(str(e))}"
                )
                logging.warning(f"[FAIL] {log_msg}")
                try:
                    await bot.send_message(ERROR_LOG_CHANNEL_ID, log_msg, parse_mode=ParseMode.MARKDOWN)
                except Exception as log_e:
                    logging.error(f"[FAIL] Не удалось отправить лог в канал ошибок: {log_e}")

            user = message.from_user
            try:
                await add_user(uid, user.username, user.full_name)
            except Exception as e:
                log_msg = f"Ошибка добавления пользователя в БД {uid}: {escape_markdown(str(e))}"
                logging.error(f"[DB ERROR] {log_msg}")
                try:
                    await bot.send_message(ERROR_LOG_CHANNEL_ID, log_msg, parse_mode=ParseMode.MARKDOWN)
                except Exception as log_e:
                    logging.error(f"[FAIL] Не удалось отправить лог в канал ошибок: {log_e}")

            links = []
            buttons = []
            for dest in PRIVATE_DESTINATIONS:
                if not all(k in dest for k in ("title", "chat_id", "description")):
                    logging.error(f"[CONFIG ERROR] Некорректный элемент PRIVATE_DESTINATIONS: {dest}")
                    continue
                try:
                    invite = await bot.create_chat_invite_link(
                        chat_id=dest["chat_id"],
                        member_limit=1,
                        creates_join_request=False,
                        name=f"Invite for {user.username or user.id}"
                    )
                    try:
                        await verify_user(uid, invite.invite_link)
                    except Exception as e:
                        log_msg = f"Ошибка обновления invite_link для {uid}: {escape_markdown(str(e))}"
                        logging.error(f"[DB ERROR] {log_msg}")
                        try:
                            await bot.send_message(ERROR_LOG_CHANNEL_ID, log_msg, parse_mode=ParseMode.MARKDOWN)
                        except Exception as log_e:
                            logging.error(f"[FAIL] Не удалось отправить лог в канал ошибок: {log_e}")

                    links.append((dest["title"], invite.invite_link, dest["description"]))
                    buttons.append([InlineKeyboardButton(text=dest["title"], url=invite.invite_link)])
                except TelegramForbiddenError as e:
                    log_msg = f"Не удалось создать invite link для {uid} в чате {dest['chat_id']}: {escape_markdown(str(e))}"
                    logging.warning(f"[FAIL] {log_msg}")
                    try:
                        await bot.send_message(ERROR_LOG_CHANNEL_ID, log_msg, parse_mode=ParseMode.MARKDOWN)
                    except Exception as log_e:
                        logging.error(f"[FAIL] Не удалось отправить лог в канал ошибок: {log_e}")

            test_link = links[0][1] if links else ""
            text2 = (
                "**Здесь ссылки на проекты «Лудочат»**\n\n"
                "[Лудочат · помощь игрокам](https://t.me/+as3JmHK21sxhMGEy) — чат взаимовыручки...\n"
                "[Серый Лудочат](https://t.me/GrayLudoChat) — «серые» темы (продать БК и т. д.)\n\n"
                "**Приватные чаты:**\n"
                "[12 шагов](https://t.me/Ludo12Steps) — ...\n"
                "[Поп-психология](https://t.me/LudoPopPsych) — ...\n"
                "[Научно доказанные методы лечения](https://t.me/LudoScience) — ...\n"
                f"[Тест]({test_link}) — тестовая индивидуальная ссылка\n\n"
                "**Наши каналы:**\n"
                "[Антигембл](https://t.me/antigambl) — ...\n"
                "[Блог «Лудочат»](https://t.me/LudoBlog) — ...\n\n"
                "**Наши боты:**\n"
                "[Выручка](https://t.me/viruchkaa_bot?start=0012) — ...\n"
                "[Алгоритм](https://t.me/algorithmga_bot?start=0011) — ..."
            )

            sent = False
            try:
                await bot.send_message(
                    uid, text2,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                    parse_mode=ParseMode.MARKDOWN
                )
                logging.info(f"[SEND] Ссылки отправлены пользователю {uid}")
                sent = True
            except TelegramForbiddenError as e:
                log_msg = f"Не удалось отправить ссылки {uid}: {escape_markdown(str(e))}"
                logging.warning(f"[FAIL] {log_msg}")
                try:
                    await bot.send_message(ERROR_LOG_CHANNEL_ID, log_msg, parse_mode=ParseMode.MARKDOWN)
                except Exception as log_e:
                    logging.error(f"[FAIL] Не удалось отправить лог в канал ошибок: {log_e}")

            # Логируем факт успешной верификации
            log_text = (
                f"👤 <b>{escape_markdown(user.full_name)}</b> (@{escape_markdown(user.username or '')})\n"
                f"🆔 <code>{user.id}</code>\n"
                "📨 Завершил верификацию и получил доступ:\n"
            )
            for title, invite_link, _ in links:
                log_text += f"— <b>{escape_markdown(title)}</b>: {invite_link}\n"

            try:
                # Используем HTML, чтобы не опасаться Markdown-ошибок
                await bot.send_message(LOG_CHANNEL_ID, log_text, parse_mode="HTML")
                logging.info(f"[LOG] Лог отправлен в канал {LOG_CHANNEL_ID}")
            except Exception as e:
                log_msg = f"Не удалось отправить лог о верификации {uid} в канал {LOG_CHANNEL_ID}: {escape_markdown(str(e))}"
                logging.warning(f"[FAIL] {log_msg}")
                try:
                    await bot.send_message(ERROR_LOG_CHANNEL_ID, log_msg, parse_mode=ParseMode.MARKDOWN)
                except Exception as log_e:
                    logging.error(f"[FAIL] Не удалось отправить лог в канал ошибок: {log_e}")
        else:
            await message.reply(
                "❗ Неверная команда. Чтобы пройти верификацию, нажмите «Вступить» в публичном чате и "
                "используйте полученную кнопку «✅ Я согласен(а) и ознакомлен(а) со всем»."
            )
    else:
        await message.reply(
            "Привет! Чтобы пройти верификацию, нажмите «Вступить» в публичном чате. "
            "Там вы получите кнопку «✅ Я согласен(а) и ознакомлен(а) со всем».")
