# services/broadcasts/sender.py
# Отправка в Telegram: HTML/медиа/альбомы, лимиты, ретраи.
# Новое:
#  - send_preview(): предпросмотр контента тем же способом, что боевой Sender,
#    без "Отписаться" и с Inline-клавиатурой; для альбомов клавиатура
#    прикрепляется к последнему сообщению через edit_message_reply_markup.
#  - Жёсткая проверка CAPTION_LIMIT (1024 символа) у подписи к медиа.
#  - Исправлена ошибка "can't use file of type Photo as Document": теперь
#    тип → метод маппится строго (photo→send_photo, video→send_video, document→send_document).

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from aiogram import Bot
from aiogram.types import (
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
    InlineKeyboardMarkup,
    Message,
    MessageEntity,
)
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest

from utils.common import log_and_report

log = logging.getLogger(__name__)

CAPTION_LIMIT = 1024  # лимит подписи к медиа по требованиям Telegram


# ========================= helpers =========================

def _looks_like_html(s: str) -> bool:
    return "<" in s and ">" in s


def _to_entities(raw: Optional[List[Dict[str, Any]]]) -> Optional[List[MessageEntity]]:
    if not raw:
        return None
    out: List[MessageEntity] = []
    for e in raw:
        out.append(e if isinstance(e, MessageEntity) else MessageEntity.model_validate(e))
    return out


async def _send_with_retry(coro) -> Tuple[Optional[Message], Optional[str], Optional[str]]:
    """
    Унифицированный вызов send_* с одной повторной попыткой при RetryAfter.
    Возвращает (Message|None, error_code|None, error_message|None).
    """
    try:
        msg = await coro
        return msg, None, None
    except TelegramRetryAfter as e:
        wait_s = float(getattr(e, "retry_after", 1.0)) + 1.0
        log.warning("TG rate-limit: подождём %.1fs и повторим", wait_s)
        await asyncio.sleep(wait_s)
        try:
            msg = await coro
            return msg, None, None
        except Exception as e2:
            return None, "RetryAfter", str(e2)
    except TelegramForbiddenError as e:
        return None, "Forbidden", str(e)
    except TelegramBadRequest as e:
        return None, "BadRequest", str(e)
    except Exception as e:
        return None, "Unknown", str(e)


# ========================= ПРЕДПРОСМОТР =========================
async def send_preview(
    bot: Bot,
    chat_id: int,
    media: List[Dict[str, Any]],
    kb: Optional[InlineKeyboardMarkup] = None,
) -> Tuple[bool, Optional[int], Optional[str], Optional[str]]:
    """
    Отправляет media (формат ContentBuilder.make_media_items()) как предпросмотр:
      - теми же методами, как боевая рассылка;
      - без «Отписаться»;
      - с жёсткой проверкой CAPTION_LIMIT;
      - для альбома прикручивает kb к последнему сообщению альбома через edit_message_reply_markup.

    Возврат: (ok, last_message_id, error_code, error_message)
    """
    if not media:
        return False, None, "Empty", "media is empty"

    try:
        item = media[0]
        mtype = item.get("type")
        payload = item.get("payload", {}) or item.get("payload_json", {})

        # Текстовый HTML
        if mtype == "html":
            text = (payload.get("text") or "").strip()
            msg, code, err = await _send_with_retry(
                bot.send_message(
                    chat_id,
                    text if text else " ",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=kb,
                )
            )
            return (msg is not None), (msg.message_id if msg else None), code, err

        # Одиночные медиа
        if mtype in {"photo", "video", "document"}:
            file_id: str = payload.get("file_id")
            if not file_id:
                return False, None, "BadPayload", "missing file_id"

            caption: Optional[str] = payload.get("caption")
            ents_raw = payload.get("caption_entities")
            ents = _to_entities(ents_raw)

            if caption and len(caption) > CAPTION_LIMIT:
                return False, None, "CaptionTooLong", f"Подпись превышает {CAPTION_LIMIT} символов"

            parse_mode = None if ents else ("HTML" if (caption and _looks_like_html(caption)) else None)

            if mtype == "photo":
                msg, code, err = await _send_with_retry(
                    bot.send_photo(chat_id, file_id, caption=caption, caption_entities=ents, parse_mode=parse_mode, reply_markup=kb)
                )
            elif mtype == "video":
                msg, code, err = await _send_with_retry(
                    bot.send_video(chat_id, file_id, caption=caption, caption_entities=ents, parse_mode=parse_mode, reply_markup=kb)
                )
            else:
                msg, code, err = await _send_with_retry(
                    bot.send_document(chat_id, file_id, caption=caption, caption_entities=ents, parse_mode=parse_mode, reply_markup=kb)
                )
            return (msg is not None), (msg.message_id if msg else None), code, err

        # Альбом (мульти-медиа)
        if mtype == "album":
            items = (payload or {}).get("items", [])[:10]
            if not items:
                return False, None, "EmptyAlbum", "album items missing"

            media_group = []
            for el in items:
                t = el.get("type")
                p = el.get("payload", {})
                fid = p.get("file_id")
                cap = p.get("caption")
                ents = _to_entities(p.get("caption_entities"))

                if not fid:
                    continue

                if cap and len(cap) > CAPTION_LIMIT:
                    return False, None, "CaptionTooLong", f"Подпись в альбоме превышает {CAPTION_LIMIT} символов"

                parse_mode = None if ents else ("HTML" if (cap and _looks_like_html(cap)) else None)

                if t == "photo":
                    media_group.append(InputMediaPhoto(media=fid, caption=cap, caption_entities=ents, parse_mode=parse_mode))
                elif t == "video":
                    media_group.append(InputMediaVideo(media=fid, caption=cap, caption_entities=ents, parse_mode=parse_mode))
                elif t == "document":
                    # у документов подпись в альбоме Telegram не поддерживает — оставляем без подписи
                    media_group.append(InputMediaDocument(media=fid))
                else:
                    # пропускаем неизвестные
                    continue

            if not media_group:
                return False, None, "BadAlbum", "no valid items"

            sent: List[Message] = await bot.send_media_group(chat_id, media_group)
            last_id = sent[-1].message_id if sent else None

            # Прикручиваем клавиатуру к последнему сообщению альбома
            if kb and last_id:
                try:
                    await bot.edit_message_reply_markup(chat_id=chat_id, message_id=last_id, reply_markup=kb)
                except Exception:
                    pass  # не критично

            return True, last_id, None, None

        # Fallback: если пришёл какой-то иной тип, но c payload.text
        if "text" in payload:
            msg, code, err = await _send_with_retry(
                bot.send_message(chat_id, payload.get("text", ""), parse_mode="HTML", disable_web_page_preview=True, reply_markup=kb)
            )
            return (msg is not None), (msg.message_id if msg else None), code, err

        return False, None, "UnsupportedType", f"type={mtype}"

    except TelegramRetryAfter as e:
        await asyncio.sleep(float(getattr(e, "retry_after", 1.0)) + 1.0)
        return await send_preview(bot, chat_id, media, kb)
    except TelegramForbiddenError as e:
        return False, None, "Forbidden", str(e)
    except TelegramBadRequest as e:
        return False, None, "BadRequest", str(e)
    except Exception as e:
        try:
            await log_and_report(e, "send_preview unknown")
        except Exception:
            pass
        return False, None, "Unknown", str(e)


# ========================= Совместимость (если где-то дергают старые методы) =========================
def _split_files(files_field: Any) -> List[str]:
    """Поддерживаем как строку 'id1,id2', так и массив."""
    if not files_field:
        return []
    if isinstance(files_field, list):
        vals = files_field
    else:
        vals = str(files_field).split(",")
    return [str(x).strip() for x in vals if str(x).strip()]


async def send_content_json(
    bot: Bot,
    user_id: int,
    content: Dict[str, Any],
) -> Tuple[bool, Optional[int], Optional[str], Optional[str]]:
    """
    DEPRECATED для предпросмотра — не умеет корректно различать типы file_id.
    Сохраняем для обратной совместимости старых вызовов.
    """
    text = (content.get("text") or "").strip()
    files = _split_files(content.get("files"))

    if not files:
        msg, code, err = await _send_with_retry(
            bot.send_message(
                user_id,
                text if text else " ",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        )
        if msg:
            return True, msg.message_id, None, None
        return False, None, code or "SendFailed", err or "send_message returned None"

    first_msg_id: Optional[int] = None
    caption_too_long = bool(text) and (len(text) > CAPTION_LIMIT)

    for idx, fid in enumerate(files):
        if not fid:
            continue
        use_caption = (idx == 0) and (not caption_too_long) and bool(text)
        # СТАРОЕ (и потенциально падающее) поведение: всё отправлялось send_document
        msg, code, err = await _send_with_retry(
            bot.send_document(
                user_id,
                fid,
                caption=text if use_caption else None,
                parse_mode="HTML" if use_caption else None,
            )
        )
        if msg and first_msg_id is None:
            first_msg_id = msg.message_id
        if idx == 0 and msg is None:
            return False, None, code or "SendFailed", err or "first document send failed"

    if first_msg_id is None:
        return False, None, "SendFailed", "all file sends failed"

    if caption_too_long:
        _msg, _code, _err = await _send_with_retry(
            bot.send_message(
                user_id,
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        )
    return True, first_msg_id, None, None


async def send_html(bot: Bot, user_id: int, html: str) -> bool:
    try:
        msg, code, err = await _send_with_retry(
            bot.send_message(user_id, html, parse_mode="HTML", disable_web_page_preview=True)
        )
        return msg is not None
    except Exception as e:
        try:
            await log_and_report(e, "send_html")
        except Exception:
            pass
        return False


async def send_media(bot: Bot, user_id: int, media: List[Dict[str, Any]]) -> bool:
    """
    Боевая отправка нормализованных media-items (тот же формат, что у send_preview).
    """
    ok, _, _, _ = await send_preview(bot, user_id, media, kb=None)
    return ok


__all__ = ["send_preview", "send_content_json", "send_media", "send_html", "CAPTION_LIMIT"]
