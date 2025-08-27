# Mailing/keyboards/broadcasts_wizard.py
# Коммит: feat(keyboard): понятные подписи кнопок для визарда рассылок
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup


def kb_kinds() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📰 Новостной пост", callback_data="kind:news")
    kb.button(text="📅 Анонс встречи", callback_data="kind:meetings")
    kb.button(text="⚡️ Важное сообщение", callback_data="kind:important")
    kb.button(text="🚫 Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()


def kb_audience() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Все подписчики выбранного типа", callback_data="aud:all")
    kb.button(text="🧾 Указать список ID", callback_data="aud:ids")
    kb.button(text="🧠 Выборка SQL", callback_data="aud:sql")
    kb.button(text="🔙 Назад (тип)", callback_data="back:kind")
    kb.button(text="🚫 Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()


def kb_schedule() -> InlineKeyboardMarkup:
    """Выбор режима отправки/расписания."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Отправить сейчас", callback_data="sch:now")
    kb.button(text="🗓 Разовая дата/время (МСК)", callback_data="sch:oneoff")
    kb.button(text="🔂 Периодически (CRON)", callback_data="sch:cron")
    kb.button(text="🔙 Назад (аудитория)", callback_data="back:aud")
    kb.button(text="🚫 Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()


def kb_schedule_confirm(enabled: bool) -> InlineKeyboardMarkup:
    """Подтверждение выбранного расписания (превью уже показано)."""
    kb = InlineKeyboardBuilder()
    kb.button(text=("🟢 Включить после создания" if not enabled else "🔴 Сохранить выключенной"), callback_data="sch:toggle")
    kb.button(text="✏️ Изменить расписание", callback_data="sch:edit")
    kb.button(text="✅ Сохранить и создать", callback_data="sch:save")
    kb.button(text="🔙 Назад (аудитория)", callback_data="back:aud")
    kb.button(text="🚫 Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()


def kb_preview() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Исправить контент", callback_data="post:preview_edit")
    kb.button(text="✅ Всё верно — дальше", callback_data="post:preview_ok")
    kb.button(text="🚫 Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()


def kb_confirm() -> InlineKeyboardMarkup:
    """Запасной вариант на будущее."""
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data="post:confirm")
    kb.button(text="🔙 Назад (расписание)", callback_data="back:sch")
    kb.button(text="🚫 Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()
