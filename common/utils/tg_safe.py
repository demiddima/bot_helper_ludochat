# common/utils/tg_safe.py
# Безопасные отправки в личку: гасим TelegramForbiddenError, чистим подписки и membership только по BOT_ID.

from __future__ import annotations

import logging
from typing import Any, Optional

from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramForbiddenError

import config
from storage import remove_membership, delete_user_subscriptions

log = logging.getLogger(__name__)


async def _cleanup_blocked(user_id: int) -> None:
    """
    Очистка после блокировки: remove_membership(user_id, BOT_ID) + delete_user_subscriptions(user_id).
    Лог — одно INFO-сообщение.
    """
    m_ok = True
    s_ok = True
    try:
        await remove_membership(user_id, config.BOT_ID)
    except Exception as exc:
        m_ok = False
        log.error("user_id=%s – Ошибка remove_membership(bot): %s", user_id, exc, extra={"user_id": user_id})
    try:
        await delete_user_subscriptions(user_id)
    except Exception as exc:
        s_ok = False
        log.error("user_id=%s – Ошибка delete_user_subscriptions: %s", user_id, exc, extra={"user_id": user_id})

    parts = []
    parts.append("membership(bot)=OK" if m_ok else "membership(bot)=ERR")
    parts.append("subscriptions=OK" if s_ok else "subscriptions=ERR")
    log.info("user_id=%s – Автоочистка после Forbidden: %s", user_id, ", ".join(parts), extra={"user_id": user_id})


def _extract_user_id(target: Message | CallbackQuery | Any) -> Optional[int]:
    """
    Аккуратно вытаскиваем user_id получателя (личка):
    - для Message → chat.id
    - для CallbackQuery → from_user.id
    """
    try:
        if isinstance(target, Message):
            return int(target.chat.id)
        if isinstance(target, CallbackQuery):
            return int(target.from_user.id)
    except Exception:
        return None
    return None


async def answer_safe(target: Message | CallbackQuery, text: str, **kwargs) -> Optional[Message]:
    """
    Безопасный аналог .answer():
    - отправляет сообщение,
    - при TelegramForbiddenError чистит подписки/membership (по BOT_ID) и молча возвращает None.
    """
    user_id = _extract_user_id(target)
    try:
        if isinstance(target, Message):
            return await target.answer(text, **kwargs)
        elif isinstance(target, CallbackQuery):
            return await target.message.answer(text, **kwargs)
        else:
            raise TypeError("answer_safe: неподдерживаемый target")
    except TelegramForbiddenError:
        if user_id:
            await _cleanup_blocked(user_id)
        return None


async def edit_text_safe(target: Message | CallbackQuery, text: str, **kwargs) -> bool:
    """
    Безопасный аналог .edit_text():
    - редактирует сообщение,
    - при TelegramForbiddenError → очистка и False.
    """
    user_id = _extract_user_id(target)
    try:
        if isinstance(target, Message):
            await target.edit_text(text, **kwargs)
            return True
        elif isinstance(target, CallbackQuery):
            await target.message.edit_text(text, **kwargs)
            return True
        else:
            raise TypeError("edit_text_safe: неподдерживаемый target")
    except TelegramForbiddenError:
        if user_id:
            await _cleanup_blocked(user_id)
        return False
