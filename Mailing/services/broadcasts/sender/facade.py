# Mailing/services/broadcasts/sender/facade.py
# Публичные функции отправки (бывший sender.py), теперь внутри пакета.
# Сигнатуры сохранены, импорты «как раньше» продолжают работать через __init__.

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, Message
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from .policy import (
    CAPTION_LIMIT,
    ensure_caption_fits,
    send_with_retry,
    classify_exc,
)
from .transport import (
    send_text,
    send_single_media,
    send_album,
)


def _split_files(files_field: Any) -> List[str]:
    """Поддерживаем как строку 'id1,id2', так и массив."""
    if not files_field:
        return []
    if isinstance(files_field, list):
        vals = files_field
    else:
        vals = str(files_field).split(",")
    return [str(x).strip() for x in vals if str(x).strip()]


_HTML_RE = re.compile(r"<[^>]+>")  # грубый детектор HTML-тегов

def _looks_like_html(s: str) -> bool:
    return bool(s) and bool(_HTML_RE.search(s))


# --- helper: отправка file_id с фолбэком по типу ---
async def _send_file_with_fallback(
    bot: Bot,
    chat_id: int,
    payload: dict,
    *,
    primary: str = "document",
    parse_caption_html: bool = False,
) -> Tuple[Optional[Message], Optional[str], Optional[str]]:
    """
    Пробуем отправить file_id как primary-тип.
    Если BadRequest (например, "Photo as Document") — пробуем другие типы.
    Порядок: primary → photo → video → document.
    """
    order = [primary] + [t for t in ("photo", "video", "document") if t != primary]
    last_err: Tuple[Optional[str], Optional[str]] = (None, None)

    for media_type in order:
        msg, code, err = await send_with_retry(
            send_single_media(bot, chat_id, media_type, payload, parse_caption_html=parse_caption_html)
        )
        if code is None:
            return msg, None, None
        if code != "BadRequest":
            return None, code, err
        last_err = (code, err)

    return None, last_err[0], last_err[1]


async def send_preview(
    bot: Bot,
    chat_id: int,
    media: List[Dict[str, Any]],
    kb: Optional[InlineKeyboardMarkup] = None,
) -> Tuple[bool, Optional[int], Optional[str], Optional[str]]:
    """
    Отправляет media (формат ContentBuilder.make_media_items()) как предпросмотр.
    Возвращает: (ok, last_msg_id|None, error_code|None, error_message|None)
    """
    last_msg: Optional[Message] = None

    try:
        for item in media:
            t = (item.get("type") or "").lower()
            payload = item.get("payload") or {}

            if t in {"text", "html"}:
                text = str(payload.get("text") or "").strip()
                entities = payload.get("entities")
                parse_html = False if entities else _looks_like_html(text)
                msg, code, err = await send_with_retry(
                    send_text(bot, chat_id, text, entities=entities, parse_html=parse_html)
                )
                if code:
                    return False, (last_msg.message_id if last_msg else None), code, err
                last_msg = msg

            elif t in {"photo", "video", "document"}:
                cap = payload.get("caption")
                cap_entities = payload.get("caption_entities")
                if cap:
                    ensure_caption_fits(cap)
                parse_caption_html = False if cap_entities else _looks_like_html(cap or "")

                msg, code, err = await send_with_retry(
                    send_single_media(bot, chat_id, t, payload, parse_caption_html=parse_caption_html)
                )
                if code:
                    return False, (last_msg.message_id if last_msg else None), code, err
                last_msg = msg

            elif t == "album":
                items = (payload or {}).get("items") or []
                if items:
                    last = items[-1]
                    cap = (last.get("payload") or {}).get("caption")
                    if cap:
                        ensure_caption_fits(cap)
                msgs, code, err = await send_with_retry(send_album(bot, chat_id, items))
                if code:
                    return False, (last_msg.message_id if last_msg else None), code, err
                if msgs:
                    last_msg = msgs[-1]

            else:
                continue

        if kb and last_msg:
            try:
                await bot.edit_message_reply_markup(chat_id=chat_id, message_id=last_msg.message_id, reply_markup=kb)
            except Exception:
                pass

        if last_msg is None:
            return False, None, "NoMessages", "nothing was sent"
        return True, last_msg.message_id, None, None

    except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter) as e:
        return False, (last_msg.message_id if last_msg else None), classify_exc(e), str(e)
    except Exception as e:
        return False, (last_msg.message_id if last_msg else None), "Unknown", str(e)


async def send_content_json(
    bot: Bot,
    user_id: int,
    content: Dict[str, Any],
) -> Tuple[bool, Optional[int], Optional[str], Optional[str]]:
    """
    Старый формат: {"text": "<HTML>", "files": "id1,id2"}
    Если files → пробуем каждое как document, при BadRequest fallback photo→video→document.
    """
    text = (content.get("text") or "").strip()
    files = _split_files(content.get("files"))

    last_msg_id: Optional[int] = None

    try:
        if not files and text:
            parse_html = _looks_like_html(text)
            msg, code, err = await send_with_retry(
                send_text(bot, user_id, text, entities=None, parse_html=parse_html)
            )
            if code:
                return False, None, code, err
            return True, msg.message_id if msg else None, None, None

        caption_used = False
        for file_id in files:
            payload = {"file_id": file_id}
            cap_here = None
            parse_caption_html = False
            if text and not caption_used:
                try:
                    ensure_caption_fits(text)
                    cap_here = text
                    parse_caption_html = _looks_like_html(text)
                    caption_used = True
                except ValueError:
                    cap_here = None
                    parse_caption_html = False

            if cap_here:
                payload["caption"] = cap_here

            msg, code, err = await _send_file_with_fallback(
                bot, user_id, payload, primary="document", parse_caption_html=parse_caption_html
            )
            if code:
                return False, last_msg_id, code, err
            if msg:
                last_msg_id = msg.message_id

        if text and not caption_used:
            parse_html = _looks_like_html(text)
            msg, code, err = await send_with_retry(send_text(bot, user_id, text, entities=None, parse_html=parse_html))
            if code:
                return False, last_msg_id, code, err
            if msg:
                last_msg_id = msg.message_id

        return True, last_msg_id, None, None

    except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter) as e:
        return False, last_msg_id, classify_exc(e), str(e)
    except Exception as e:
        return False, last_msg_id, "Unknown", str(e)


async def send_html(bot: Bot, user_id: int, html: str) -> bool:
    try:
        msg, code, err = await send_with_retry(send_text(bot, user_id, html, entities=None, parse_html=True))
        return msg is not None and code is None
    except Exception:
        return False


async def send_media(bot: Bot, user_id: int, media: List[Dict[str, Any]]) -> bool:
    ok, _, _, _ = await send_preview(bot, user_id, media, kb=None)
    return ok
