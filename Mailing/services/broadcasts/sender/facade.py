# Mailing/services/broadcasts/sender/facade.py
# Python 3.11+, aiogram v3
# Изменения:
# - Убраны зависимости от send_with_retry/policy/classify_exc (лишняя связка на этом уровне)
# - Единый анализ media_items → text/single_media/album/mixed
# - HTML-fallback (если нет entities, но строка похожа на HTML)
# - Альбом: подпись и caption_entities только у первого элемента; в превью при отсутствии текста — техсообщение с kb
# - Возврат: (ok, message_id | [message_ids], code, err)

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import re

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, Message, MessageEntity

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


# ---------- analyze input structure ----------

def _analyze(media: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Нормализуем вход (поддерживаем несколько historical-форматов):
    - {"type":"text","payload":{"text": "...", "entities":[...]?}}
    - {"type":"media","payload":{"kind":"photo|video|document","file_id": "...","caption":"...","caption_entities":[...]?}}
    - {"type":"photo|video|document","payload":{"file_id": "...","caption":"...","caption_entities":[...]?}}  # legacy
    - {"type":"album","payload":{"items":[ ... up to 10 ... ]}}
    """
    model: Dict[str, Any] = {"kind": "mixed", "items": media or []}
    if not media:
        return model

    first = media[0] or {}

    # album
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

    # single media (унификация legacy → media)
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

    # mixed: оставляем как есть
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


# ---------- public API ----------

async def send_preview(
    bot: Bot,
    chat_id: int,
    media: List[Dict[str, Any]],
    kb: Optional[InlineKeyboardMarkup] = None,
) -> Tuple[bool, Optional[Union[int, List[int]]], Optional[str], Optional[str]]:
    """
    Превью максимально совпадает с боевой логикой, но:
    - если альбом без текста, а нужна клавиатура — шлём дополнительное техсообщение с kb.
    """
    try:
        model = _analyze(media)

        if model["kind"] == "text":
            text = model.get("text_html") or ""
            ents = model.get("text_entities")
            # если entities нет, но это HTML — включаем parse_html
            parse_html = (ents is None) and _looks_like_html(text)
            msg: Message = await send_text(bot, chat_id, text, entities=ents, parse_html=parse_html, reply_markup=kb)
            return True, msg.message_id, None, None

        if model["kind"] == "single_media":
            payload = model.get("media_payload") or {}
            kind = (model.get("media_kind") or "document").lower()
            caption = (payload.get("caption") or None)
            caption_entities = _as_entities(payload.get("caption_entities"))
            parse_caption_html = (caption_entities is None) and _looks_like_html(caption)
            msg: Message = await send_single_media(
                bot, chat_id, kind, payload,
                parse_caption_html=parse_caption_html,
                reply_markup=kb
            )
            return True, msg.message_id, None, None

        if model["kind"] == "album":
            # 1) Шлём альбом (подпись и caption_entities — у первого)
            msgs = await send_album(bot, chat_id, model.get("album_items") or [])
            ids = [m.message_id for m in (msgs or [])]

            # 2) Если есть текст — шлём текст с kb
            text = model.get("text_html") or ""
            ents = model.get("text_entities")
            if text:
                parse_html = (ents is None) and _looks_like_html(text)
                msg = await send_text(bot, chat_id, text, entities=ents, parse_html=parse_html, reply_markup=kb)
                if msg:
                    ids.append(msg.message_id)
                return True, ids or None, None, None

            # 3) Текста нет, но нужно показать kb — добавим техсообщение в превью
            if kb:
                msg = await send_text(bot, chat_id, "Кнопки к альбому:", entities=None, parse_html=False, reply_markup=kb)
                if msg:
                    ids.append(msg.message_id)

            return True, ids or None, None, None

        # mixed: шлём по одному; kb — на последний элемент
        last_id: Optional[int] = None
        items = media or []
        for idx, el in enumerate(items):
            is_last = idx == len(items) - 1
            t = (el.get("type") or "").lower()
            p = (el.get("payload") or {})

            if t in {"text", "html"}:
                text = (p.get("text") or "").strip()
                ents = _as_entities(p.get("entities"))
                parse_html = (ents is None) and _looks_like_html(text)
                msg = await send_text(bot, chat_id, text, entities=ents, parse_html=parse_html, reply_markup=kb if is_last else None)
            elif t == "media":
                kind = (p.get("kind") or "document").lower()
                caption = (p.get("caption") or None)
                cap_ents = _as_entities(p.get("caption_entities"))
                parse_caption_html = (cap_ents is None) and _looks_like_html(caption)
                msg = await send_single_media(bot, chat_id, kind, p, parse_caption_html=parse_caption_html, reply_markup=kb if is_last else None)
            elif t in {"photo", "video", "document"}:
                # приведение legacy к единому виду
                kind = t
                caption = (p.get("caption") or None)
                cap_ents = _as_entities(p.get("caption_entities"))
                parse_caption_html = (cap_ents is None) and _looks_like_html(caption)
                msg = await send_single_media(bot, chat_id, kind, {"kind": kind, **p}, parse_caption_html=parse_caption_html, reply_markup=kb if is_last else None)
            elif t == "album":
                # отправим альбом сразу; kb при необходимости добавится следующим шагом (текст/техсообщение)
                msgs = await send_album(bot, chat_id, (p.get("items") or []))
                if msgs:
                    last_id = msgs[-1].message_id
                continue
            else:
                # неизвестный тип — пропустим
                continue

            if msg:
                last_id = msg.message_id

        return True, last_id, None, None

    except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter) as e:
        return _err(e)
    except Exception as e:
        return _err(e)


async def send_actual(
    bot: Bot,
    chat_id: int,
    media: List[Dict[str, Any]],
    kb_for_text: Optional[InlineKeyboardMarkup] = None,
) -> Tuple[bool, Optional[Union[int, List[int]]], Optional[str], Optional[str]]:
    """
    Боевая отправка: если можно одним — одним; иначе альбом → текст (если есть).
    """
    try:
        model = _analyze(media)

        if model["kind"] == "text":
            text = model.get("text_html") or ""
            ents = model.get("text_entities")
            parse_html = (ents is None) and _looks_like_html(text)
            msg = await send_text(bot, chat_id, text, entities=ents, parse_html=parse_html, reply_markup=kb_for_text)
            return True, msg.message_id, None, None

        if model["kind"] == "single_media":
            payload = model.get("media_payload") or {}
            kind = (model.get("media_kind") or "document").lower()
            caption = (payload.get("caption") or None)
            caption_entities = _as_entities(payload.get("caption_entities"))
            parse_caption_html = (caption_entities is None) and _looks_like_html(caption)
            msg = await send_single_media(bot, chat_id, kind, payload, parse_caption_html=parse_caption_html, reply_markup=kb_for_text)
            return True, msg.message_id, None, None

        if model["kind"] == "album":
            msgs = await send_album(bot, chat_id, model.get("album_items") or [])
            ids = [m.message_id for m in (msgs or [])]

            text = model.get("text_html") or ""
            ents = model.get("text_entities")
            if text:
                parse_html = (ents is None) and _looks_like_html(text)
                msg = await send_text(bot, chat_id, text, entities=ents, parse_html=parse_html, reply_markup=kb_for_text)
                if msg:
                    ids.append(msg.message_id)
            return True, ids or None, None, None

        # mixed
        last_id: Optional[int] = None
        items = media or []
        for idx, el in enumerate(items):
            is_last = idx == len(items) - 1
            t = (el.get("type") or "").lower()
            p = (el.get("payload") or {})

            if t in {"text", "html"}:
                text = (p.get("text") or "").strip()
                ents = _as_entities(p.get("entities"))
                parse_html = (ents is None) and _looks_like_html(text)
                msg = await send_text(bot, chat_id, text, entities=ents, parse_html=parse_html, reply_markup=kb_for_text if is_last else None)
            elif t == "media":
                kind = (p.get("kind") or "document").lower()
                caption = (p.get("caption") or None)
                cap_ents = _as_entities(p.get("caption_entities"))
                parse_caption_html = (cap_ents is None) and _looks_like_html(caption)
                msg = await send_single_media(bot, chat_id, kind, p, parse_caption_html=parse_caption_html, reply_markup=kb_for_text if is_last else None)
            elif t in {"photo", "video", "document"}:
                kind = t
                caption = (p.get("caption") or None)
                cap_ents = _as_entities(p.get("caption_entities"))
                parse_caption_html = (cap_ents is None) and _looks_like_html(caption)
                msg = await send_single_media(bot, chat_id, kind, {"kind": kind, **p}, parse_caption_html=parse_caption_html, reply_markup=kb_for_text if is_last else None)
            elif t == "album":
                msgs = await send_album(bot, chat_id, (p.get("items") or []))
                if msgs:
                    last_id = msgs[-1].message_id
                continue
            else:
                continue

            if msg:
                last_id = msg.message_id

        return True, last_id, None, None

    except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter) as e:
        return _err(e)
    except Exception as e:
        return _err(e)
