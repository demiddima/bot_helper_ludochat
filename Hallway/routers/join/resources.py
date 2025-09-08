# Hallway/routers/join/resources.py)
from __future__ import annotations

import os
import logging
from typing import Sequence

from aiogram import Router, F
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from common.utils import get_bot
from storage import get_all_invite_links
from config import PRIVATE_DESTINATIONS, LOG_CHANNEL_ID
from Hallway.services.invite_service import generate_invite_links
from common.utils.chatlink import is_url, to_int_or_none, eq_chat_id

router = Router()


async def send_chunked_message(chat_id: int, text: str, *, allow_group: bool = False, **kwargs):
    bot = get_bot()

    if chat_id < 0 and not allow_group:
        logging.info(f"Пропустить отправку в group/channel chat_id={chat_id}")
        return

    # Автодобавление «🧭 Меню»
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
        logging.error(f"user_id={chat_id} – ошибка добавления кнопки «Меню»: {e}", extra={"user_id": chat_id})

    for start in range(0, len(text), 4096):
        try:
            await bot.send_message(chat_id, text[start:start + 4096], **kwargs)
        except Exception as e:
            logging.error(
                f"user_id={chat_id} – ошибка при отправке chunked message: {e}",
                extra={"user_id": chat_id}
            )
            try:
                kwargs.pop("reply_markup", None)
                await bot.send_message(chat_id, text[start:start + 4096])
            except Exception as ee:
                logging.error(
                    f"user_id={chat_id} – повторная ошибка отправки chunked message: {ee}",
                    extra={"user_id": chat_id}
                )
                break


async def read_advertisement_file(file_name: str) -> str:
    try:
        file_path = os.path.join("text", file_name)
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logging.error(f"user_id=system – ошибка при чтении файла {file_name}: {e}", extra={"user_id": "system"})
        return ""


def _compute_missing_chat_ids(
    destinations: Sequence[dict],
    existing_links: list[dict],
) -> set[int]:
    """
    Возвращает множество числовых chat_id из destinations, для которых нет записи в existing_links.
    URL-назначения игнорируются.
    """
    missing: set[int] = set()

    for dest in destinations:
        raw_cid = dest.get("chat_id")
        if is_url(raw_cid):
            continue
        num_cid = to_int_or_none(raw_cid)
        if num_cid is None:
            continue

        found = any(eq_chat_id(link.get("chat_id"), num_cid) for link in existing_links)
        if not found:
            missing.add(num_cid)

    return missing


async def send_resources_message(bot, user, uid: int, refresh: bool = False, previous_message_id: int | None = None):
    """
    Отправляет сообщение с ресурсами.
    При refresh=True — регенерирует все числовые инвайты.
    Без refresh — догенерирует ТОЛЬКО недостающие.
    """
    try:
        bot_info = await bot.get_me()
        logging.debug(
            f"user_id={uid} – user: {user.full_name} (@{user.username or 'нет'}), bot: @{bot_info.username}, ID: {bot_info.id}",
            extra={"user_id": uid}
        )

        # 1) Загружаем текущие ссылки
        all_links = await get_all_invite_links(uid)
        logging.info(f"user_id={uid} – найдено ссылок в БД: {len(all_links)}", extra={"user_id": uid})

        # 2) Генерация: полная (refresh) или частичная (только отсутствующие)
        generated_buttons: list[list[dict]] = []
        if refresh:
            logging.info(f"user_id={uid} – refresh=True → регенерируем все (числовые) ссылки", extra={"user_id": uid})
            _, generated_buttons = await generate_invite_links(
                bot,
                user=user,
                uid=uid,
                PRIVATE_DESTINATIONS=PRIVATE_DESTINATIONS,
                verify_user=None,
                ERROR_LOG_CHANNEL_ID=None,
                only_chat_ids=None,
            )
            all_links = await get_all_invite_links(uid)
        else:
            missing_ids = _compute_missing_chat_ids(PRIVATE_DESTINATIONS, all_links)
            if missing_ids:
                logging.info(
                    f"user_id={uid} – отсутствуют ссылки для chat_id: {sorted(missing_ids)} → генерируем",
                    extra={"user_id": uid},
                )
                _, generated_buttons = await generate_invite_links(
                    bot,
                    user=user,
                    uid=uid,
                    PRIVATE_DESTINATIONS=PRIVATE_DESTINATIONS,
                    verify_user=None,
                    ERROR_LOG_CHANNEL_ID=None,
                    only_chat_ids=missing_ids,
                )
                all_links = await get_all_invite_links(uid)
            else:
                logging.info(f"user_id={uid} – все назначения уже есть в БД", extra={"user_id": uid})

        # 3) Маппинг title -> url из (а) .env URL, (б) БД, (в) свежесгенерированных кнопок
        title_to_url: dict[str, str] = {}

        # (а) прямые URL из .env
        for dest in PRIVATE_DESTINATIONS:
            if is_url(dest["chat_id"]):
                title_to_url[dest["title"]] = dest["chat_id"]

        # (б) по БД для числовых chat_id
        for dest in PRIVATE_DESTINATIONS:
            raw_cid = dest["chat_id"]
            if is_url(raw_cid):
                continue
            num_cid = to_int_or_none(raw_cid)
            if num_cid is None:
                continue
            link = next((x.get("invite_link") for x in all_links if eq_chat_id(x.get("chat_id"), num_cid)), None)
            if link:
                title_to_url[dest["title"]] = link

        # (в) свежие кнопки перекрывают всё
        for row in generated_buttons:
            if row and isinstance(row[0], dict):
                t = row[0].get("text")
                u = row[0].get("url")
                if t and u:
                    title_to_url[t] = u

        # 4) Тексты
        advertisement_1_text = await read_advertisement_file("advertisement_1.html")  # Лудочат
        advertisement_2_text = await read_advertisement_file("advertisement_2.html")  # Практичат
        advertisement_3_text = await read_advertisement_file("advertisement_3.html")  # Выручат

        url_ludo = title_to_url.get("Лудочат")
        url_prak = title_to_url.get("Практичат")
        url_vyru = title_to_url.get("Выручат")

        logging.info(
            f"user_id={uid} – URLs: Ludo={'+' if url_ludo else '-'}, Prak={'+' if url_prak else '-'}, Vyru={'+' if url_vyru else '-'}",
            extra={"user_id": uid}
        )

        intro = (
            "Привет! Это бот с информацией для зависимых от азартных игр. "
            "Изучайте ссылки, пользуйтесь нашими инструментами и налаживайте жизнь.\n\n"
        )

        parts: list[str] = []
        if url_ludo:
            parts.append(f"<a href='{url_ludo}'><b>Лудочат</b></a> — {advertisement_1_text}")
        if url_prak:
            parts.append(f"<a href='{url_prak}'><b>Практичат</b></a> — {advertisement_2_text}")
        if url_vyru:
            parts.append(f"<a href='{url_vyru}'><b>Выручат</b></a> — {advertisement_3_text}")

        text = intro + (
            "\n\n".join(parts)
            if parts
            else "Ссылки временно недоступны. Нажмите «Меню» и попробуйте «Обновить ссылки»."
        )

        # 5) Клавиатура
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

        await send_chunked_message(
            uid,
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=keyboard,
        )

        # 6) Лог-канал
        try:
            log_lines = []
            if url_ludo:
                log_lines.append(f"Лудочат: {url_ludo}")
            if url_prak:
                log_lines.append(f"Практичат: {url_prak}")
            if url_vyru:
                log_lines.append(f"Выручат: {url_vyru}")
            if LOG_CHANNEL_ID and log_lines:
                log_message = f"🔗 Ссылки актуальны\nПользователь: {uid}\n" + "\n".join(log_lines)
                await send_chunked_message(LOG_CHANNEL_ID, log_message, parse_mode=None, reply_markup=None, allow_group=True)
        except Exception as e:
            logging.error(f"user_id={uid} – ошибка отправки лога в канал: {e}", extra={"user_id": uid})

    except Exception as e:
        logging.error(f"user_id={uid} – ошибка при отправке сообщения с ресурсами: {e}", extra={"user_id": uid})
        raise


@router.callback_query(F.message.chat.type == ChatType.PRIVATE, F.data.startswith("refresh_"))
async def on_refresh(query: CallbackQuery):
    uid = query.from_user.id
    try:
        await query.answer("Обновляю ресурсы…")
        await send_resources_message(query.bot, query.from_user, uid, refresh=True)
    except Exception as e:
        logging.error(f"user_id={uid} – ошибка при обновлении ресурсов: {e}", extra={"user_id": uid})
        try:
            await query.answer("Произошла ошибка при обновлении ресурсов.")
        except Exception as ee:
            logging.error(f"user_id={uid} – ошибка при отправке сообщения пользователю: {ee}", extra={"user_id": uid})
