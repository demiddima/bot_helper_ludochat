# handlers/join/menu.py
# Меню и управление рассылками (актуальная версия)
# Корп. логи: – user_id=… – описание (имя функции логгер сам подставит)

import logging
from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    Message,
)
import messages
from storage import (
    get_user_subscriptions,
    ensure_user_subscriptions_defaults,
    toggle_user_subscription,
)

router = Router(name="menu")


def _kb_label(name: str, state: bool) -> str:
    return f"{name}: {'Вкл' if state else 'Выкл'}"


def _subs_kb(news: bool, meetings: bool, important: bool) -> InlineKeyboardMarkup:
    """
    Раскладка:
    [ Новости | Встречи ]
    [ Важные послания ]
    [ ⬅️ Назад ]
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_kb_label("Новости", news), callback_data="subs:toggle:news"),
                InlineKeyboardButton(text=_kb_label("Встречи", meetings), callback_data="subs:toggle:meetings"),
            ],
            [InlineKeyboardButton(text=_kb_label("Важные послания", important), callback_data="subs:toggle:important")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:open")],
        ]
    )


def _extract_flags(rec: dict | None) -> tuple[bool, bool, bool]:
    if not rec:
        # наши дефолты: news=False, meetings=True, important=True
        return False, True, True
    return (
        bool(rec.get("news_enabled", False)),
        bool(rec.get("meetings_enabled", True)),
        bool(rec.get("important_enabled", True)),
    )


@router.callback_query(F.data == "menu:open")
async def on_menu_open(query: CallbackQuery):
    """
    Нажатие inline-кнопки «🧭 Меню»:
    – не редактируем исходное сообщение,
    – отправляем новое с заголовком и Reply-клавиатурой.
    """
    uid = query.from_user.id
    try:
        logging.info("user_id=%s – нажата кнопка «Меню»", uid, extra={"user_id": uid})
        await query.answer()
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📣 Рассылки")]],
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Выберите раздел…",
        )
        await query.bot.send_message(
            chat_id=uid,
            text=messages.get_menu_title_text(),  # "<b>Доступные разделы:</b>"
            reply_markup=kb,
        )
    except Exception as e:
        logging.error("user_id=%s – Ошибка открытия меню: %s", uid, e, extra={"user_id": uid})


@router.message(F.text.in_({"Рассылки", "📣 Рассылки"}))
async def on_menu_subscriptions_message(msg: Message):
    """
    Раздел «Рассылки»: берём состояние из БД; если записи нет — создаём дефолты.
    Никаких приписок «Этап 1…» — выводим только messages.get_subscriptions_text(...).
    """
    uid = msg.from_user.id
    try:
        logging.info("user_id=%s – открываю «Рассылки» (GET state)", uid, extra={"user_id": uid})

        rec = await get_user_subscriptions(uid)
        if not rec:
            logging.info("user_id=%s – state отсутствует ⇒ создаю дефолты", uid, extra={"user_id": uid})
            rec = await ensure_user_subscriptions_defaults(uid)

        news, meetings, important = _extract_flags(rec)
        await msg.answer(
            messages.get_subscriptions_text(news, meetings, important),
            reply_markup=_subs_kb(news, meetings, important),
        )
    except Exception as e:
        logging.error("user_id=%s – Ошибка открытия «Рассылки»: %s", uid, e, extra={"user_id": uid})
        try:
            await msg.answer("Не удалось открыть «Рассылки».")
        except Exception as ee:
            logging.error("user_id=%s – Ошибка ответа: %s", uid, ee, extra={"user_id": uid})


@router.callback_query(F.data == "subs:open")
async def on_subs_open_cb(query: CallbackQuery):
    """
    Нажатие inline-кнопки «Настроить рассылки» внутри любого сообщения.
    Открываем «📣 Рассылки» так же, как из меню.
    """
    uid = query.from_user.id
    try:
        logging.info("user_id=%s – открываю «Рассылки» (CB)", uid, extra={"user_id": uid})
        await query.answer()

        rec = await get_user_subscriptions(uid)
        if not rec:
            logging.info("user_id=%s – state отсутствует ⇒ создаю дефолты (CB)", uid, extra={"user_id": uid})
            rec = await ensure_user_subscriptions_defaults(uid)

        news, meetings, important = _extract_flags(rec)
        await query.message.answer(
            messages.get_subscriptions_text(news, meetings, important),
            reply_markup=_subs_kb(news, meetings, important),
        )
    except Exception as e:
        logging.error("user_id=%s – Ошибка открытия «Рассылки» (CB): %s", uid, e, extra={"user_id": uid})
        try:
            await query.message.answer("Не удалось открыть «Рассылки».")
        except Exception as ee:
            logging.error("user_id=%s – Ошибка ответа (CB): %s", uid, ee, extra={"user_id": uid})


@router.callback_query(F.data.startswith("subs:toggle:"))
async def on_subs_toggle(query: CallbackQuery):
    """
    Тумблеры: дергаем toggle в хранилище и перерисовываем экран.
    """
    uid = query.from_user.id
    try:
        kind = query.data.split(":")[-1]  # news|meetings|important
        logging.info("user_id=%s – toggle kind=%s", uid, kind, extra={"user_id": uid})

        rec = await toggle_user_subscription(uid, kind)
        news, meetings, important = _extract_flags(rec)

        await query.message.edit_text(
            messages.get_subscriptions_text(news, meetings, important),
            reply_markup=_subs_kb(news, meetings, important),
        )
        await query.answer("Обновлено")
    except Exception as e:
        logging.error("user_id=%s – Ошибка toggle: %s", uid, e, extra={"user_id": uid})
        await query.answer("Не получилось переключить", show_alert=False)
