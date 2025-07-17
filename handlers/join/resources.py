import os
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest

from utils import get_bot
from storage import get_all_invite_links
from config import PRIVATE_DESTINATIONS, BOT_ID  # Импортируем BOT_ID для использования в коде
from services.invite_service import generate_invite_links  # Подключаем функцию генерации ссылок

router = Router()

async def send_chunked_message(chat_id: int, text: str, **kwargs):
    bot = get_bot()
    for start in range(0, len(text), 4096):
        await bot.send_message(chat_id, text[start:start+4096], **kwargs)


# Функция для чтения текстов из файлов с правильным путем
async def read_advertisement_file(file_name):
    try:
        file_path = os.path.join('text', file_name)  # Путь относительно директории с main.py
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logging.error(f"[ERROR] Ошибка при чтении файла {file_name}: {e}")
        return ""


async def send_resources_message(bot, user, uid, refresh=False, previous_message_id=None):
    """
    Отправляет сообщение с ресурсами и кастомным меню.
    Если refresh=True, перегенерирует ссылки.
    """
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    expires_ts = int(now.timestamp()) + 3600  # 1 час
    expires_iso = (now + timedelta(hours=1)).isoformat()

    bot_info = await bot.get_me()  # Получаем информацию о боте
    logging.info(f"[DEBUG] user: {user.full_name} (@{user.username or 'нет'}, ID: {uid}), bot: @{bot_info.username}, ID: {bot_info.id}")

    # Получаем/обновляем invite-ссылки
    if refresh:
        logging.info(f"[INFO] Обновление ссылок для uid={uid}")
        try:
            links, buttons = await generate_invite_links(
                bot, user=user, uid=uid, PRIVATE_DESTINATIONS=PRIVATE_DESTINATIONS,
                verify_user=None, ERROR_LOG_CHANNEL_ID=None
            )
        except Exception as e:
            logging.error(f"[ERROR] Ошибка при генерации ссылок для uid={uid}: {e}")
            raise
    else:
        logging.info(f"[INFO] Получение всех ссылок для uid={uid} из базы данных")
        try:
            all_links = await get_all_invite_links(uid)
            if not all_links:
                logging.warning(f"[WARNING] Не найдено ссылок для uid={uid} в базе данных.")
                # Генерация ссылок, если их нет
                logging.info(f"[INFO] Генерация новых ссылок для uid={uid}")
                links, buttons = await generate_invite_links(
                    bot, user=user, uid=uid, PRIVATE_DESTINATIONS=PRIVATE_DESTINATIONS,
                    verify_user=None, ERROR_LOG_CHANNEL_ID=None
                )
            else:
                # Если ссылки есть, используем их
                logging.info(f"[INFO] Используем существующие ссылки для uid={uid}")
                buttons = []
                for dest in PRIVATE_DESTINATIONS:
                    cid = dest["chat_id"]
                    title = dest["title"]
                    description = dest.get("description", "")
                    link = next((x["invite_link"] for x in all_links if x["chat_id"] == cid), None)
                    if link:
                        buttons.append([{"text": title, "url": link, "description": description}])
                    else:
                        logging.error(f"[ERROR] Не найдено действующей ссылки для {title} с chat_id={cid}")

        except Exception as e:
            logging.error(f"[ERROR] Ошибка при получении ссылок для uid={uid}: {e}")
            raise

    # Чтение текстов из файлов advertisement_1.html и advertisement_2.html
    advertisement_1_text = await read_advertisement_file('advertisement_1.html')
    advertisement_2_text = await read_advertisement_file('advertisement_2.html')

    # Формируем текст с правильным форматом
    text = "<b>Наше сообщество</b>:\n\n"
    
    # Вставляем ссылки в текст и добавляем текст из HTML файлов
    text += f"<a href='{buttons[0][0]['url']}'>Лудочат</a> — {advertisement_1_text}\n\n"
    text += f"<a href='{buttons[1][0]['url']}'>Выручка</a> — {advertisement_2_text}\n\n"

    # Кнопка "Назад"
    back_button = InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_{uid}")

    # Отправляем сообщение
    logging.info(f"Лудочат ссылка: {buttons[0][0]['url']}")
    logging.info(f"Выручка ссылка: {buttons[1][0]['url']}")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[ 
        [InlineKeyboardButton(text="Лудочат", url=buttons[0][0]["url"]),
         InlineKeyboardButton(text="Выручка", url=buttons[1][0]["url"]),
         InlineKeyboardButton(text="Обновить ссылки", callback_data=f"refresh_{uid}")],
        [
            InlineKeyboardButton(text="Все проекты", callback_data="section_projects"),
            InlineKeyboardButton(text="Помощь", callback_data="section_doctors"),
        ],
        [
            InlineKeyboardButton(text="Работа", callback_data="section_work"),
            InlineKeyboardButton(text="Анонимность", callback_data="section_anonymity"),
        ],
    ])

    await send_chunked_message(
        uid,
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=keyboard,
    )



@router.callback_query(F.data.startswith("refresh_"))
async def on_refresh(query: CallbackQuery):
    """ Обновление ссылки по запросу пользователя """
    await query.answer("Обновляю ресурсы…")
    
    # Получаем ID пользователя из callback_query
    uid = query.from_user.id
    
    # Проверяем, соответствует ли ID пользователя
    if query.from_user.id != uid:
        return await query.answer("Это не ваши ресурсы.")
    
    # Вызываем функцию с правильными параметрами
    await send_resources_message(query.bot, query.from_user, uid, refresh=True)
