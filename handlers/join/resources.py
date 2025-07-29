# resources.py
# Корпоративный стиль логирования: [function] – user_id=… – описание, try/except для всех рисковых операций

import os
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest

from utils import get_bot
from storage import get_all_invite_links
from config import PRIVATE_DESTINATIONS, LOG_CHANNEL_ID
from services.invite_service import generate_invite_links

router = Router()

async def send_chunked_message(chat_id: int, text: str, **kwargs):
    func_name = "send_chunked_message"
    bot = get_bot()
    for start in range(0, len(text), 4096):
        try:
            await bot.send_message(chat_id, text[start:start+4096], **kwargs)
        except Exception as e:
            logging.error(
                f"user_id={chat_id} – Ошибка при отправке chunked message: {e}",
                extra={"user_id": chat_id}
            )

async def read_advertisement_file(file_name):
    func_name = "read_advertisement_file"
    try:
        file_path = os.path.join('text', file_name)
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logging.error(
            f"user_id=system – Ошибка при чтении файла {file_name}: {e}",
            extra={"user_id": "system"}
        )
        return ""

async def send_resources_message(bot, user, uid, refresh=False, previous_message_id=None):
    """
    Отправляет сообщение с ресурсами и кастомным меню.
    Если refresh=True, перегенерирует ссылки.
    """
    func_name = "send_resources_message"
    try:
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
        expires_ts = int(now.timestamp()) + 3600  # 1 час
        expires_iso = (now + timedelta(hours=1)).isoformat()

        bot_info = await bot.get_me()
        logging.debug(
            f"user_id={uid} – user: {user.full_name} (@{user.username or 'нет'}), bot: @{bot_info.username}, ID: {bot_info.id}",
            extra={"user_id": uid}
        )

        # Получаем/обновляем invite-ссылки
        if refresh:
            logging.info(
                f"user_id={uid} – Обновление ссылок",
                extra={"user_id": uid}
            )
            try:
                links, buttons = await generate_invite_links(
                    bot, user=user, uid=uid, PRIVATE_DESTINATIONS=PRIVATE_DESTINATIONS,
                    verify_user=None, ERROR_LOG_CHANNEL_ID=None
                )
            except Exception as e:
                logging.error(
                    f"user_id={uid} – Ошибка при генерации ссылок: {e}",
                    extra={"user_id": uid}
                )
                raise
        else:
            try:
                all_links = await get_all_invite_links(uid)
                if not all_links:
                    logging.warning(
                        f"user_id={uid} – Ссылки не найдены, генерируем новые",
                        extra={"user_id": uid}
                    )
                    links, buttons = await generate_invite_links(
                        bot, user=user, uid=uid, PRIVATE_DESTINATIONS=PRIVATE_DESTINATIONS,
                        verify_user=None, ERROR_LOG_CHANNEL_ID=None
                    )
                else:
                    logging.info(
                        f"user_id={uid} – Используем существующие ссылки",
                        extra={"user_id": uid}
                    )
                    buttons = []
                    for dest in PRIVATE_DESTINATIONS:
                        try:
                            cid = dest["chat_id"]
                            title = dest["title"]
                            description = dest.get("description", "")
                            if isinstance(cid, str) and cid.startswith("http"):
                                link = cid
                            else:
                                link = next((x["invite_link"] for x in all_links if x["chat_id"] == cid), None)

                            if link:
                                buttons.append([{"text": title, "url": link, "description": description}])
                            else:
                                logging.error(
                                    f"user_id={uid} – Не найдена ссылка для «{title}» (chat_id={cid})",
                                    extra={"user_id": uid}
                                )
                        except Exception as e:
                            logging.error(
                                f"user_id={uid} – Ошибка при обработке назначения {dest}: {e}",
                                extra={"user_id": uid}
                            )
                            continue
            except Exception as e:
                logging.error(
                    f"user_id={uid} – Ошибка при получении ссылок: {e}",
                    extra={"user_id": uid}
                )
                raise

        advertisement_1_text = await read_advertisement_file('advertisement_1.html')
        advertisement_2_text = await read_advertisement_file('advertisement_2.html')

        text = "Привет! Это бот с информацией для зависимых от азартных игр. Изучайте ссылки, пользуйтесь нашими инструментами и налаживайте жизнь.\n\n"

        logging.info(
            f"user_id={uid} – buttons: {buttons}",
            extra={"user_id": uid}
        )

        text += f"<a href='{buttons[0][0]['url']}'><b>Лудочат</b></a> — {advertisement_1_text}\n\n"
        text += f"<a href='{buttons[1][0]['url']}'><b>Выручка</b></a> — {advertisement_2_text}\n\n"

        # logging.info(
        #     f"user_id={uid} – Лудочат ссылка: {buttons[0][0]['url']}",
        #     extra={"user_id": uid}
        # )
        # logging.info(
        #     f"user_id={uid} – Выручка ссылка: {buttons[1][0]['url']}",
        #     extra={"user_id": uid}
        # )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Лудочат", url=buttons[0][0]["url"]),
                InlineKeyboardButton(text="Выручка", url=buttons[1][0]["url"]),
            #   InlineKeyboardButton(text="Обновить ссылки", callback_data=f"refresh_{uid}")
            ],
            [
                InlineKeyboardButton(text="Наше сообщество", callback_data="section_projects"),
                InlineKeyboardButton(text="Ваша анонимность", callback_data="section_anonymity"),
            #    InlineKeyboardButton(text="Помощь", callback_data="section_doctors"),
            ],
            # [
            #     InlineKeyboardButton(text="Работа", callback_data="section_work"),
            #     InlineKeyboardButton(text="Анонимность", callback_data="section_anonymity"),
            # ],
        ])

        await send_chunked_message(
            uid,
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=keyboard,
        )

        log_message = (
            f"🔗 Ссылки сгенерированы\n"
            f"Пользователь: {uid}\n"
            f"Лудочат: {buttons[0][0]['url']}\n"
            f"Выручка: {buttons[1][0]['url']}"
        )
        await send_chunked_message(
            LOG_CHANNEL_ID,
            log_message,
            parse_mode="HTML",
            disable_web_page_preview=True
        )

    except Exception as e:
        logging.error(
            f"user_id={uid} – Ошибка при отправке сообщения с ресурсами: {e}",
            extra={"user_id": uid}
        )
        raise

@router.callback_query(F.data.startswith("refresh_"))
async def on_refresh(query: CallbackQuery):
    func_name = "on_refresh"
    uid = query.from_user.id
    try:
        await query.answer("Обновляю ресурсы…")
        await send_resources_message(query.bot, query.from_user, uid, refresh=True)
    except Exception as e:
        logging.error(
            f"user_id={uid} – Ошибка при обновлении ресурсов: {e}",
            extra={"user_id": uid}
        )
        try:
            await query.answer("Произошла ошибка при обновлении ресурсов.")
        except Exception as ee:
            logging.error(
                f"user_id={uid} – Ошибка при отправке сообщения пользователю: {ee}",
                extra={"user_id": uid}
            )
