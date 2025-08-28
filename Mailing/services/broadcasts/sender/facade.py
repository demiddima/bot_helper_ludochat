# Mailing/services/broadcasts/sender/facade.py
# Python 3.11+, aiogram v3
# Поведение:
# - send_preview: как прежде (если kb нельзя прикрепить — отправляется отдельное сообщение с кнопками).
# - send_actual: если kb_for_text не передали — пробуем подставить кнопку «Настроить рассылки».
#   Кнопка крепится ТОЛЬКО когда это возможно (текст/одиночное медиа или текст после альбома).
#   Если невозможно (чистый альбом без текста) — отправляем без кнопки, никаких дополнительных сообщений.

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import (
    InlineKeyboardMarkup,
    Message,
    MessageEntity,
)

from Mailing.keyboards.subscriptions import subscriptions_kb
from .transport import send_text, send_single_media, send_album

_HTML_RE = re.compile(r"<[^>]+>")


def _looks_like_html(s: Optional[str]) -> bool:
    return bool(s) and bool(_HTML_RE.search(s))


def _as_entities(seq: Optional[Sequence[Any]]) -> Optional[List[MessageEntity]]:
    if not seq:
        return None
    out: List[MessageEntity] = []
    for e in seq:
        out.append(e if isinstance(e, MessageEntity) else MessageEntity.model_validate(e))
    return out


async def _default_manage_kb(bot: Bot) -> InlineKeyboardMarkup:
   return subscriptions_kb()


# ---------- analyze input structure ----------

def _analyze(media: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Поддерживаем форматы:
    - {"type":"text","payload":{"text": "...", "entities":[...]?}}
    - {"type":"media","payload":{"kind":"photo|video|document","file_id":"...","caption":"...","caption_entities":[...]?}}
    - {"type":"photo|video|document","payload":{...}}          # legacy → приводим к "media"
    - {"type":"album","payload":{"items":[...]}}
    """
    model: Dict[str, Any] = {"kind": "mixed", "items": media or []}
    if not media:
        return model

    first = media[0] or {}

    if first.get("type") == "album":
        items = (first.get("payload") or {}).get("items") or []
        model["kind"] = "album"
        model["album_items"] = items
        # возможный текст вторым элементом
        txt, ents = None, None
        if len(media) >= 2 and (media[1] or {}).get("type") in {"text", "html"}:
            p = (media[1] or {}).get("payload") or {}
            txt = (p.get("text") or "").strip() or None
            ents = _as_entities(p.get("entities"))
        model["text_html"] = txt
        model["text_entities"] = ents
        return model

    if len(media) == 1:
        t = (first.get("type") or "").lower()
        if t in {"text", "html"}:
            p = (first.get("payload") or {})
            model["kind"] = "text"
            model["text_html"] = (p.get("text") or "").strip()
            model["text_entities"] = _as_entities(p.get("entities"))
            return model
        if t == "media":
            model["kind"] = "single_media"
            model["media_kind"] = ((first.get("payload") or {}).get("kind") or "document").lower()
            model["media_payload"] = (first.get("payload") or {})
            return model
        if t in {"photo", "video", "document"}:
            p = (first.get("payload") or {})
            model["kind"] = "single_media"
            model["media_kind"] = t
            model["media_payload"] = {"kind": t, **p}
            return model

    # mixed
    model["kind"] = "mixed"
    return model


def _err(e: Exception) -> Tuple[bool, None, str, str]:
    if isinstance(e, TelegramRetryAfter):
        return False, None, "RetryAfter", str(e)
    if isinstance(e, TelegramForbiddenError):
        return False, None, "Forbidden", str(e)
    if isinstance(e, TelegramBadRequest):
        return False, None, "BadRequest", str(e)
    return False, None, "Unknown", str(e)


async def _send_text_with_auto_html(
    bot: Bot,
    chat_id: int,
    text: str,
    kb: Optional[InlineKeyboardMarkup],
    entities: Optional[Sequence[Any]] = None,
) -> Message:
    ents = _as_entities(entities)
    parse_html = (ents is None) and _looks_like_html(text)
    return await send_text(bot, chat_id, text, entities=ents, parse_html=parse_html, reply_markup=kb)


# ---------- PREVIEW (как было: с fallback отдельным сообщением для кнопок) ----------

async def send_preview(
    bot: Bot,
    chat_id: int,
    media: List[Dict[str, Any]],
    kb: Optional[InlineKeyboardMarkup] = None,
) -> Tuple[bool, Optional[Union[int, List[int]]], Optional[str], Optional[str]]:
    try:
        model = _analyze(media)

        if model["kind"] == "text":
            msg = await _send_text_with_auto_html(bot, chat_id, model.get("text_html") or "", kb, model.get("text_entities"))
            return True, msg.message_id, None, None

        if model["kind"] == "single_media":
            payload = model.get("media_payload") or {}
            kind = (model.get("media_kind") or "document").lower()
            caption = (payload.get("caption") or None)
            cap_ents = _as_entities(payload.get("caption_entities"))
            parse_caption_html = (cap_ents is None) and _looks_like_html(caption)
            msg = await send_single_media(bot, chat_id, kind, payload, parse_caption_html=parse_caption_html, reply_markup=kb)
            return True, msg.message_id, None, None

        if model["kind"] == "album":
            msgs = await send_album(bot, chat_id, model.get("album_items") or [])
            ids = [m.message_id for m in (msgs or [])]

            text = model.get("text_html") or ""
            ents = model.get("text_entities")
            if text:
                msg = await _send_text_with_auto_html(bot, chat_id, text, kb, ents)
                if msg:
                    ids.append(msg.message_id)
            elif kb:
                # Кнопку к альбому не прикрепить — fallback: отдельное пустое сообщение с клавиатурой
                msg = await send_text(bot, chat_id, "\u2063", parse_html=False, entities=None, reply_markup=kb)
                if msg:
                    ids.append(msg.message_id)
            return True, ids or None, None, None

        # mixed: клава — на последний поддерживающий элемент; если некуда — отправим отдельное сообщение
        last_id: Optional[int] = None
        last_supports_kb = False
        for idx, el in enumerate(media or []):
            is_last = idx == len(media) - 1
            t = (el.get("type") or "").lower()
            p = (el.get("payload") or {})

            if t in {"text", "html"}:
                msg = await _send_text_with_auto_html(bot, chat_id, (p.get("text") or "").strip(), kb if is_last else None, _as_entities(p.get("entities")))
                last_supports_kb = True
            elif t == "media":
                kind = (p.get("kind") or "document").lower()
                cap = (p.get("caption") or None)
                cap_ents = _as_entities(p.get("caption_entities"))
                parse_caption_html = (cap_ents is None) and _looks_like_html(cap)
                msg = await send_single_media(bot, chat_id, kind, p, parse_caption_html=parse_caption_html, reply_markup=kb if is_last else None)
                last_supports_kb = True
            elif t == "album":
                group = await send_album(bot, chat_id, (p.get("items") or []))
                msg = group[-1] if group else None
                last_supports_kb = False
            else:
                msg = None

            if msg:
                last_id = msg.message_id

        if kb and not last_supports_kb:
            await send_text(bot, chat_id, "\u2063", parse_html=False, entities=None, reply_markup=kb)

        return True, last_id, None, None

    except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter) as e:
        return _err(e)
    except Exception as e:
        return _err(e)


# ---------- ACTUAL (добавлена авто-кнопка «Настроить рассылки») ----------

async def send_actual(
    bot: Bot,
    chat_id: int,
    media: List[Dict[str, Any]],
    kb_for_text: Optional[InlineKeyboardMarkup] = None,
) -> Tuple[bool, Optional[Union[int, List[int]]], Optional[str], Optional[str]]:
    """
    Боевая отправка.
    Если kb_for_text не передан — используем клавиатуру «Настроить рассылки» по умолчанию.
    Кнопку прикрепляем ТОЛЬКО если это возможно. Никаких отдельных сообщений.
    """
    try:
        # если клава не пришла — подставим дефолтную
        kb = kb_for_text or await _default_manage_kb(bot)

        model = _analyze(media)

        if model["kind"] == "text":
            msg = await _send_text_with_auto_html(bot, chat_id, model.get("text_html") or "", kb, model.get("text_entities"))
            return True, msg.message_id, None, None

        if model["kind"] == "single_media":
            payload = model.get("media_payload") or {}
            kind = (model.get("media_kind") or "document").lower()
            caption = (payload.get("caption") or None)
            cap_ents = _as_entities(payload.get("caption_entities"))
            parse_caption_html = (cap_ents is None) and _looks_like_html(caption)
            msg = await send_single_media(bot, chat_id, kind, payload, parse_caption_html=parse_caption_html, reply_markup=kb)
            return True, msg.message_id, None, None

        if model["kind"] == "album":
            msgs = await send_album(bot, chat_id, model.get("album_items") or [])
            ids = [m.message_id for m in (msgs or [])]

            text = model.get("text_html") or ""
            ents = model.get("text_entities")
            if text:
                msg = await _send_text_with_auto_html(bot, chat_id, text, kb, ents)
                if msg:
                    ids.append(msg.message_id)
            # нет текста → кнопке не к чему крепиться → ничего не добавляем
            return True, ids or None, None, None

        # mixed: клава — на последний поддерживающий элемент; если последний — альбом, ничего не добавляем
        last_id: Optional[int] = None
        last_supports_kb = False
        for idx, el in enumerate(media or []):
            is_last = idx == len(media) - 1
            t = (el.get("type") or "").lower()
            p = (el.get("payload") or {})

            if t in {"text", "html"}:
                msg = await _send_text_with_auto_html(bot, chat_id, (p.get("text") or "").strip(), kb if is_last else None, _as_entities(p.get("entities")))
                last_supports_kb = True
            elif t == "media":
                kind = (p.get("kind") or "document").lower()
                cap = (p.get("caption") or None)
                cap_ents = _as_entities(p.get("caption_entities"))
                parse_caption_html = (cap_ents is None) and _looks_like_html(cap)
                msg = await send_single_media(bot, chat_id, kind, p, parse_caption_html=parse_caption_html, reply_markup=kb if is_last else None)
                last_supports_kb = True
            elif t == "album":
                group = await send_album(bot, chat_id, (p.get("items") or []))
                msg = group[-1] if group else None
                last_supports_kb = False
            else:
                msg = None

            if msg:
                last_id = msg.message_id

        return True, last_id, None, None

    except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter) as e:
        return _err(e)
    except Exception as e:
        return _err(e)
