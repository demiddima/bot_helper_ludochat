# keyboards/broadcasts_wizard.py
# Клавиатуры визарда рассылок

from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup

def kb_kinds() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📰 Новости", callback_data="kind:news")
    kb.button(text="📅 Встречи", callback_data="kind:meetings")
    kb.button(text="⚡️ Важные послания", callback_data="kind:important")
    kb.button(text="🚫 Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()

def kb_audience() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Все (ALL)", callback_data="aud:all")
    kb.button(text="🧾 IDs вручную", callback_data="aud:ids")
    kb.button(text="🧠 SQL-выборка", callback_data="aud:sql")
    kb.button(text="🔙 Назад (тип)", callback_data="back:kind")
    kb.button(text="🚫 Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()

def kb_schedule() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Отправить сейчас", callback_data="sch:now")
    kb.button(text="🗓 Ввести дату/время (МСК)", callback_data="sch:manual")
    kb.button(text="🔙 Назад (аудитория)", callback_data="back:aud")
    kb.button(text="🚫 Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()

def kb_confirm() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data="post:confirm")
    kb.button(text="🔙 Назад (расписание)", callback_data="back:sch")
    kb.button(text="🚫 Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()
