# resources.py
# Корпоративный стиль логирования: [function] – user_id=… – описание, try/except для всех рисковых операций

import os
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    Message,
)
from aiogram.exceptions import TelegramBadRequest

from utils import get_bot
from storage import get_all_invite_links
from config import PRIVATE_DESTINATIONS, LOG_CHANNEL_ID
from services.invite_service import generate_invite_links
import messages  # тексты выносим сюда

router = Router()

async def send_chunked_message(chat_id: int, text: str, **kwargs):
    func_name = "send_chunked_message"
    bot = get_bot()
    # Подмешиваем кнопку «Меню» в самый низ inline-клавиатуры, если она есть (ресурсы остаются как есть)
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
            await bot.send_message(chat_id, text[start:start+4096], **kwargs)
        except Exception as e:
            logging.error(
                f"user_id={chat_id} – Ошибка при отправке chunked message: {e}",
                extra={"user_id": chat_id}
            )
            try:
                kwargs.pop("reply_markup", None)
                await bot.send_message(chat_id, text[start:start+4096])
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
    Отправляет сообщение с ресурсами и кастомным меню (inline).
    Если refresh=True, перегенерирует ссылки.
    Сообщение с ресурсами НЕ редактируем: «Меню» открывается отдельным сообщением.
    """
    func_name = "send_resources_message"
    try:
        now = datetime.utcnow().replace(tzinfo=timezone.utc)

        bot_info = await bot.get_me()
        logging.debug(
            f"user_id={uid} – user: {user.full_name} (@{user.username or 'нет'}), bot: @{bot_info.username}, ID: {bot_info.id}",
            extra={"user_id": uid}
        )

        # Получаем/обновляем invite-ссылки
        if refresh:
            logging.info(f"user_id={uid} – Обновление ссылок", extra={"user_id": uid})
            links, buttons = await generate_invite_links(
                bot, user=user, uid=uid, PRIVATE_DESTINATIONS=PRIVATE_DESTINATIONS,
                verify_user=None, ERROR_LOG_CHANNEL_ID=None
            )
        else:
            all_links = await get_all_invite_links(uid)
            if not all_links:
                logging.warning(f"user_id={uid} – Ссылки не найдены, генерируем новые", extra={"user_id": uid})
                links, buttons = await generate_invite_links(
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
                        continue

        advertisement_1_text = await read_advertisement_file('advertisement_1.html')
        advertisement_2_text = await read_advertisement_file('advertisement_2.html')

        text = (
            "Привет! Это бот с информацией для зависимых от азартных игр. "
            "Изучайте ссылки, пользуйтесь нашими инструментами и налаживайте жизнь.\n\n"
        )

        logging.info(f"user_id={uid} – buttons: {buttons}", extra={"user_id": uid})

        text += f"<a href='{buttons[0][0]['url']}'><b>Лудочат</b></a> — {advertisement_1_text}\n\n"
        text += f"<a href='{buttons[1][0]['url']}'><b>Выручка</b></a> — {advertisement_2_text}\n\n"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Лудочат", url=buttons[0][0]["url"]),
                InlineKeyboardButton(text="Выручка", url=buttons[1][0]["url"]),
            ],
            [
                InlineKeyboardButton(text="Наше сообщество", callback_data="section_projects"),
                InlineKeyboardButton(text="Ваша анонимность", callback_data="section_anonymity"),
            ],
            # Кнопка «🧭 Меню» будет добавлена автоматически в send_chunked_message()
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

# ===== Меню и Рассылки (Этап 1, заглушка) =====

def _subs_kb_stub(news: bool, meetings: bool, important: bool) -> InlineKeyboardMarkup:
    def label(name: str, state: bool) -> str:
        return f"{name}: {'Вкл' if state else 'Выкл'}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label("Новости", news), callback_data="subs:toggle:news")],
        [InlineKeyboardButton(text=label("Встречи", meetings), callback_data="subs:toggle:meetings")],
        [InlineKeyboardButton(text=label("Важные послания", important), callback_data="subs:toggle:important")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:open")]
    ])

def _parse_states_from_markup(markup: InlineKeyboardMarkup) -> dict[str, bool]:
    states = {"news": False, "meetings": False, "important": False}
    if not markup or not getattr(markup, "inline_keyboard", None):
        return states
    for row in markup.inline_keyboard:
        for btn in row:
            t = (btn.text or "")
            if t.startswith("Новости:"):
                states["news"] = "Вкл" in t
            elif t.startswith("Встречи:"):
                states["meetings"] = "Вкл" in t
            elif t.startswith("Важные послания:"):
                states["important"] = "Вкл" in t
    return states

@router.callback_query(F.data == "menu:open")
async def on_menu_open(query: CallbackQuery):
    """
    По нажатию inline-кнопки «🧭 Меню» из сообщения с ресурсами:
    – не редактируем старое сообщение,
    – отправляем НОВОЕ сообщение с жирным заголовком и Reply-клавиатурой.
    """
    uid = query.from_user.id
    try:
        await query.answer()
        # Reply-клавиатура с пунктом «Рассылки»
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📣 Рассылки")],
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Выберите раздел…"
        )
        await query.bot.send_message(
            chat_id=uid,
            text=messages.get_menu_title_text(),  # <b>Доступные разделы:</b>
            reply_markup=kb
        )
    except Exception as e:
        logging.error(f"user_id={uid} – Ошибка открытия меню: {e}", extra={"user_id": uid})

@router.message(F.text.in_({"Рассылки", "📣 Рассылки"}))
async def on_menu_subscriptions_message(msg: Message):
    """
    Раздел «Рассылки» открывается по текстовой кнопке Reply-клавиатуры.
    Дефолты (демо): Новости OFF, Встречи ON, Важные ON.
    """
    uid = msg.from_user.id
    try:
        news, meetings, important = False, True, True
        await msg.answer(
            messages.get_subscriptions_text(news, meetings, important),
            reply_markup=_subs_kb_stub(news, meetings, important)
        )
    except Exception as e:
        logging.error(f"user_id={uid} – Ошибка открытия экрана Рассылок: {e}", extra={"user_id": uid})
        try:
            await msg.answer("Не удалось открыть «Рассылки».")
        except Exception as ee:
            logging.error(f"user_id={uid} – Ошибка ответа пользователю: {ee}", extra={"user_id": uid})

@router.callback_query(F.data.startswith("subs:toggle:"))
async def on_subs_toggle_stub(query: CallbackQuery):
    """
    Переключатели в заглушке: читаем текущее состояние из текста кнопок и инвертируем выбранный.
    """
    uid = query.from_user.id
    try:
        kind = query.data.split(":")[-1]  # news|meetings|important
        current = _parse_states_from_markup(query.message.reply_markup)
        if kind in current:
            current[kind] = not current[kind]
        await query.message.edit_text(
            messages.get_subscriptions_text(current["news"], current["meetings"], current["important"]),
            reply_markup=_subs_kb_stub(current["news"], current["meetings"], current["important"])
        )
        await query.answer("Переключено (демо)")
    except Exception as e:
        logging.error(f"user_id={uid} – Ошибка переключения рассылки: {e}", extra={"user_id": uid})
        await query.answer("Не получилось переключить", show_alert=False)
