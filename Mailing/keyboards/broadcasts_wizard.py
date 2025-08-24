# keyboards/broadcasts_wizard.py
# Клавиатуры визарда рассылок (/post).
# В этом файле собраны ВСЕ inline-клавиатуры, чтобы хендлеры не держали локальные билдеры.

from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup


def kb_kinds() -> InlineKeyboardMarkup:
    """
    Выбор типа рассылки.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="📰 Новости", callback_data="kind:news")
    kb.button(text="📅 Встречи", callback_data="kind:meetings")
    kb.button(text="⚡️ Важно", callback_data="kind:important")
    kb.button(text="🚫 Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()


def kb_audience() -> InlineKeyboardMarkup:
    """
    Выбор аудитории.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Все подписчики выбранного типа", callback_data="aud:all")
    kb.button(text="🧾 IDs вручную", callback_data="aud:ids")
    kb.button(text="🧠 SQL-выборка", callback_data="aud:sql")
    kb.button(text="🔙 Назад (тип)", callback_data="back:kind")
    kb.button(text="🚫 Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()


def kb_schedule() -> InlineKeyboardMarkup:
    """
    Выбор режима отправки.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Отправить сейчас", callback_data="sch:now")
    kb.button(text="🗓 На дату/время (МСК)", callback_data="sch:manual")
    kb.button(text="🔙 Назад (аудитория)", callback_data="back:aud")
    kb.button(text="🚫 Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()


def kb_preview() -> InlineKeyboardMarkup:
    """
    Клавиатура предпросмотра контента (после первого сообщения с контентом).
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data="post:preview_ok")
    kb.button(text="✏️ Исправить", callback_data="post:preview_edit")
    kb.adjust(1)
    return kb.as_markup()


# (Опционально оставляем для совместимости — если где-то используется)
def kb_confirm() -> InlineKeyboardMarkup:
    """
    Финальная «Подтвердить» — если используется в старых хендлерах.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data="post:confirm")
    kb.button(text="🔙 Назад (расписание)", callback_data="back:sch")
    kb.button(text="🚫 Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()
