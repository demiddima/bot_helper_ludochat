# Mailing/keyboards/broadcasts_manager.py
# Коммит: feat(keyboard): kb_bm_list — поддержка флага has_more (корректный «Далее» после фильтра)
from __future__ import annotations

from typing import Optional
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup


def kb_bm_list(
    items: list[dict],
    offset: int = 0,
    limit: int = 50,
    has_more: Optional[bool] = None,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for it in items:
        bid = it.get("id")
        ttl = (it.get("title") or "").strip() or "Без названия"
        en = "🟢" if it.get("enabled") else "🔴"
        kb.button(text=f"{en} #{bid} — {ttl[:40]}", callback_data=f"bm:open:{bid}")

    if offset > 0:
        kb.button(text="⬅️ Назад", callback_data=f"bm:page:{max(0, offset - limit)}")

    show_next = has_more if has_more is not None else (len(items) >= limit)
    if show_next:
        kb.button(text="➡️ Далее", callback_data=f"bm:page:{offset + limit}")

    kb.adjust(1)
    return kb.as_markup()


def kb_bm_item(bid: int, enabled: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=("🔴 Отключить" if enabled else "🟢 Включить"), callback_data=f"bm:toggle:{bid}")
    kb.button(text="✏️ Изменить расписание", callback_data=f"bm:edit:{bid}")
    kb.button(text="🚀 Отправить сейчас", callback_data=f"bm:send:{bid}")
    kb.button(text="🗑 Удалить", callback_data=f"bm:del:{bid}")
    kb.button(text="🔙 К списку", callback_data="bm:back")
    kb.adjust(2, 2, 1)
    return kb.as_markup()
