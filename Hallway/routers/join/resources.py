# handlers/join/resources.py
# Корпоративный стиль логирования: [function] – user_id=… – описание, try/except для всех рисковых операций

import os
import logging

from aiogram import Router, F
from aiogram.enums import ChatType
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from common.utils import get_bot
from storage import get_all_invite_links
from config import PRIVATE_DESTINATIONS, LOG_CHANNEL_ID
from Hallway.services.invite_service import generate_invite_links

router = Router()


async def send_chunked_message(chat_id: int, text: str, *, allow_group: bool = False, **kwargs):
    """
    По умолчанию не отправляем в группы/каналы (chat_id < 0).
    Для лог-канала/групп — передай allow_group=True явно.
    """
    func_name = "send_chunked_message"
    bot = get_bot()

    if chat_id < 0 and not allow_group:
        logging.info(f"[guard] skip send to group/channel chat_id={chat_id}")
        return

    # Подмешиваем кнопку «Меню» в самый низ inline-клавиатуры, если она есть
    try:
        reply_markup = kwargs.get("reply_markup")
        if isinstance(reply_markup, InlineKeyboardMarkup):
            has_menu = any(
                isinstance(btn, InlineKeyboardButton)
                and (btn.callback_data or "").startswith("menu:open")
                for row in (reply_markup.inline_keyboard or [])
                for btn in row
            )
            if not has_menu:
                new_rows = list(reply_markup.inline_keyboard or [])
                new_rows.append([InlineKeyboardButton(text="🧭 Меню", callback_data="menu:open")])
                kwargs["reply_markup"] = InlineKeyboardMarkup(inline_keyboard=new_rows)
    except Exception as e:
        logging.error(f"user_id={chat_id} – Ошибка добавления кнопки «Меню»: {e}", extra={"user_id": chat_id})

    for start in range(0, len(text), 4096):
        try:
            await bot.send_message(chat_id, text[start:start + 4096], **kwargs)
        except Exception as e:
            logging.error(
                f"user_id={chat_id} – Ошибка при отправке chunked message: {e}",
                extra={"user_id": chat_id}
            )
            try:
                kwargs.pop("reply_markup", None)
                await bot.send_message(chat_id, text[start:start + 4096])
            except Exception as ee:
                logging.error(
                    f"user_id={chat_id} – Повторная ошибка отправки chunked message: {ee}",
                    extra={"user_id": chat_id}
                )
                break

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
    Отправляет сообщение с ресурсами:
      1-я строка: Лудочат | Практичат | Выручат (URL-кнопки)
      2-я строка: Наше сообщество | Ваша анонимность (callback-кнопки)
      3-я строка: 🧭 Меню (автодобавляется в send_chunked_message)
    При refresh=True перегенерирует инвайты (для числовых chat_id).
    """
    func_name = "send_resources_message"
    try:
        bot_info = await bot.get_me()
        logging.debug(
            f"user_id={uid} – user: {user.full_name} (@{user.username or 'нет'}), bot: @{bot_info.username}, ID: {bot_info.id}",
            extra={"user_id": uid}
        )

        # 1) Собираем кнопки (как раньше), но дальше будем маппить по названию
        if refresh:
            logging.info(f"user_id={uid} – Обновление ссылок", extra={"user_id": uid})
            _, buttons = await generate_invite_links(
                bot, user=user, uid=uid, PRIVATE_DESTINATIONS=PRIVATE_DESTINATIONS,
                verify_user=None, ERROR_LOG_CHANNEL_ID=None
            )
        else:
            all_links = await get_all_invite_links(uid)
            if not all_links:
                logging.warning(f"user_id={uid} – Ссылки не найдены, генерируем новые", extra={"user_id": uid})
                _, buttons = await generate_invite_links(
                    bot, user=user, uid=uid, PRIVATE_DESTINATIONS=PRIVATE_DESTINATIONS,
                    verify_user=None, ERROR_LOG_CHANNEL_ID=None
                )
            else:
                logging.info(f"user_id={uid} – Используем существующие ссылки", extra={"user_id": uid})
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

        # 2) Берём тексты из файлов (жёсткая привязка: 1—Лудочат, 2—Практичат, 3—Выручат)
        advertisement_1_text = await read_advertisement_file('advertisement_1.html')  # Лудочат
        advertisement_2_text = await read_advertisement_file('advertisement_2.html')  # Практичат
        advertisement_3_text = await read_advertisement_file('advertisement_3.html')  # Выручат

        logging.info(f"user_id={uid} – buttons: {buttons}", extra={"user_id": uid})

        # 3) Достаём конкретные ссылки по названию (независимо от порядка в .env)
        mapping = {row[0]["text"]: row[0]["url"] for row in buttons if row and "text" in row[0] and "url" in row[0]}
        url_ludo = mapping.get("Лудочат")
        url_prak = mapping.get("Практичат")  # новый
        url_vyru = mapping.get("Выручат")    # прежний (в .env — «Выручат»)

        # 4) Текст
        intro = (
            "Привет! Это бот с информацией для зависимых от азартных игр. "
            "Изучайте ссылки, пользуйтесь нашими инструментами и налаживайте жизнь.\n\n"
        )

        parts = []
        if url_ludo:
            parts.append(f"<a href='{url_ludo}'><b>Лудочат</b></a> — {advertisement_1_text}")
        if url_prak:
            parts.append(f"<a href='{url_prak}'><b>Практичат</b></a> — {advertisement_2_text}")
        if url_vyru:
            parts.append(f"<a href='{url_vyru}'><b>Выручат</b></a> — {advertisement_3_text}")

        text = intro + ("\n\n".join(parts) if parts else "Ссылки временно недоступны. Нажмите «Меню» и попробуйте «Обновить ссылки».")

        # 5) Клавиатура:
        row1 = []
        if url_ludo:
            row1.append(InlineKeyboardButton(text="Лудочат", url=url_ludo))
        if url_prak:
            row1.append(InlineKeyboardButton(text="Практичат", url=url_prak))
        if url_vyru:
            row1.append(InlineKeyboardButton(text="Выручат", url=url_vyru))

        row2 = [
            InlineKeyboardButton(text="Наше сообщество", callback_data="section_projects"),
            InlineKeyboardButton(text="Ваша анонимность", callback_data="section_anonymity"),
        ]

        keyboard_rows = []
        if row1:
            keyboard_rows.append(row1)
        keyboard_rows.append(row2)
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

        # 6) Отправляем пользователю
        await send_chunked_message(
            uid,
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=keyboard,
        )

        # 7) Лог-канал (✅ фикс: используем f-строку для uid)
        try:
            log_chunks = []
            if url_ludo: log_chunks.append(f"Лудочат: {url_ludo}")
            if url_prak: log_chunks.append(f"Практичат: {url_prak}")
            if url_vyru: log_chunks.append(f"Выручат: {url_vyru}")
            if LOG_CHANNEL_ID and log_chunks:
                log_message = f"🔗 Ссылки сгенерированы\nПользователь: {uid}\n" + "\n".join(log_chunks)
                await send_chunked_message(LOG_CHANNEL_ID, log_message, parse_mode=None, reply_markup=None)
        except Exception as e:
            logging.error(f"user_id={uid} – Ошибка отправки лога в канал: {e}", extra={"user_id": uid})

    except Exception as e:
        logging.error(
            f"user_id={uid} – Ошибка при отправке сообщения с ресурсами: {e}",
            extra={"user_id": uid}
        )
        raise

@router.callback_query(F.message.chat.type == ChatType.PRIVATE, F.data.startswith("refresh_"))
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
