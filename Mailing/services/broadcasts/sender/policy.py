# Mailing/services/broadcasts/sender/policy.py
# Политики отправки: лимиты, ретраи, классификация ошибок.

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Tuple

from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

log = logging.getLogger(__name__)

CAPTION_LIMIT = 1024  # лимит подписи к медиа по требованиям Telegram


def ensure_caption_fits(caption: str) -> None:
    if caption and len(caption) > CAPTION_LIMIT:
        raise ValueError(f"CaptionTooLong: {len(caption)} > {CAPTION_LIMIT}")


async def send_with_retry(coro) -> Tuple[Optional[Message], Optional[str], Optional[str]]:
    """
    Унифицированный вызов send_* с одной повторной попыткой при RetryAfter.
    Ждём retry_after + 1 сек и логируем предупреждение, чтобы снизить шанс повторного 429.
    Возвращает (Message|None, error_code|None, error_message|None).
    """
    try:
        msg = await coro
        return msg, None, None
    except TelegramRetryAfter as e:
        wait_s = int(getattr(e, "retry_after", 1)) or 1
        wait_s += 1  # небольшая подстраховка
        log.warning("RetryAfter: sleeping for %s s before retry", wait_s)
        await asyncio.sleep(wait_s)
        try:
            msg = await coro
            return msg, None, None
        except Exception as e2:
            return None, classify_exc(e2), str(e2)
    except Exception as e:
        return None, classify_exc(e), str(e)


def classify_exc(e: Exception) -> str:
    if isinstance(e, TelegramRetryAfter):
        return "RetryAfter"
    if isinstance(e, TelegramForbiddenError):
        return "Forbidden"
    if isinstance(e, TelegramBadRequest):
        return "BadRequest"
    return "Unknown"
