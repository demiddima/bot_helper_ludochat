# Mailing/keyboards/subscriptions.py
# Commit: единая клавиатура «Настроить рассылки» — callback уже обрабатывается в Hallway/routers/join/menu.py.

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def subscriptions_kb() -> InlineKeyboardMarkup:
    """
    Клавиатура с единственной кнопкой «Настроить рассылки».
    Callback: subs:open — уже обрабатывается в Hallway/routers/join/menu.py.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔔 Настроить рассылки", callback_data="subs:open")]
        ]
    )
