# keyboards/broadcasts.py
from __future__ import annotations
from aiogram.utils.keyboard import InlineKeyboardBuilder


def kb_content_type():
    b = InlineKeyboardBuilder()
    b.button(text="Текст (HTML)", callback_data="ct:html")
    b.button(text="Фото", callback_data="ct:photo")
    b.button(text="Видео", callback_data="ct:video")
    b.button(text="Документ", callback_data="ct:document")
    b.button(text="Альбом (до 10)", callback_data="ct:album")
    b.adjust(1, 2, 2)
    return b.as_markup()


def kb_target_type():
    b = InlineKeyboardBuilder()
    b.button(text="Подписки (kind)", callback_data="tg:kind")
    b.button(text="Список ID", callback_data="tg:ids")
    b.button(text="SQL", callback_data="tg:sql")
    b.adjust(1, 2)
    return b.as_markup()


def kb_preview_actions():
    b = InlineKeyboardBuilder()
    b.button(text="Ок", callback_data="pv:ok")
    b.button(text="Изменить таргет", callback_data="pv:back")
    b.button(text="Отмена", callback_data="pv:cancel")
    b.adjust(2, 1)
    return b.as_markup()


def kb_schedule():
    b = InlineKeyboardBuilder()
    b.button(text="Отправить сейчас", callback_data="sc:now")
    b.button(text="Запланировать", callback_data="sc:schedule")
    b.adjust(1, 1)
    return b.as_markup()


def kb_album_controls():
    b = InlineKeyboardBuilder()
    b.button(text="Готово ✅", callback_data="al:done")
    b.button(text="Отмена", callback_data="al:cancel")
    b.adjust(1, 1)
    return b.as_markup()
