# Mailing/services/broadcasts/sender/facade.py
# commit: refactor(sender/facade): smart-режим (one-message+kb vs split), альбом: текст с кнопкой; превью без лишних служебок; удалены старые билдеры

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, Union

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, Message
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from .policy import CAPTION_LIMIT, send_with_retry, classify_exc
from .transport import send_text, send_single_media, send_album

_HTML_RE = re.compile(r"<[^>]+>")

def _looks_like_html(s: Optional[str]) -> bool:
    return bool(s) and bool(_HTML_RE.search(s))


# ---------------- классификация входа ----------------

def _split_analyze(media_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Распознаём сценарии:
      - album(+text) → {"kind": "album", "album": [...], "text_html": "..."}
      - single media  → {"kind": "single_media", "item": {...}}   # item = {"type":"media","payload":{...}}
      - text-only     → {"kind": "text", "text_html": "..."}
      - mixed         → {"kind": "mixed", "items": [...]}
    Поддерживаем также исторический одиночный {"type":"photo|video|document","payload":{"file_id": "..."}}
    """
    model: Dict[str, Any] = {"kind": None}
    if not media_items:
        return model

    first = media_items[0]
    if first.get("type") == "album":
        items = (first.get("payload") or {}).get("items") or []
        model["kind"] = "album"
        model["album"] = items
        txt = ""
        if len(media_items) >= 2 and media_items[1].get("type") in {"text", "html"}:
            txt = (media_items[1].get("payload") or {}).get("text") or ""
        model["text_html"] = txt
        return model

    if len(media_items) == 1 and media_items[0].get("type") == "media":
        model["kind"] = "single_media"
        model["item"] = media_items[0]  # целиком узел {"type":"media","payload":{...}}
        return model

    if len(media_items) == 1 and media_items[0].get("type") in {"text", "html"}:
        model["kind"] = "text"
        model["text_html"] = (media_items[0].get("payload") or {}).get("text") or ""
        return model

    # исторический одиночный медиа-тип
    if len(media_items) == 1 and media_items[0].get("type") in {"photo", "video", "document"}:
        t = media_items[0]["type"]
        p = media_items[0].get("payload") or {}
        model["kind"] = "single_media"
        model["item"] = {"type": "media", "payload": {"kind": t, "file_id": p.get("file_id")}}
        return model

    model["kind"] = "mixed"
    model["items"] = media_items
    return model


def _can_one_message_with_kb(model: Dict[str, Any]) -> bool:
    """
    Кнопки можно прикрепить к:
      - тексту,
      - одиночному медиа с подписью, которая укладывается в лимит caption.
    К альбому кнопки не крепятся.
    """
    if model["kind"] == "text":
        return True
    if model["kind"] == "single_media":
        p = (model["item"] or {}).get("payload") or {}
        cap = (p.get("caption") or "").strip()
        # если есть caption_entities — доверяем им; иначе проверяем длину caption
        if cap and len(cap) > CAPTION_LIMIT:
            return False
        return True
    return False  # album/mixed


# ---------------- низкоуровневая отправка ----------------

async def _send_text(
    bot: Bot, chat_id: int, text_html: str, kb: Optional[InlineKeyboardMarkup]
) -> Tuple[bool, Optional[int], Optional[str], Optional[str]]:
    msg, code, err = await send_with_retry(
        send_text(bot, chat_id, text_html, parse_html=_looks_like_html(text_html), reply_markup=kb)
    )
    if code:
        return False, None, code, err
    return True, (msg.message_id if msg else None), None, None


async def _send_single(
    bot: Bot, chat_id: int, item_payload: Dict[str, Any], kb: Optional[InlineKeyboardMarkup]
) -> Tuple[bool, Optional[int], Optional[str], Optional[str]]:
    payload = {
        "file_id": item_payload.get("file_id"),
        "caption": item_payload.get("caption"),
        "caption_entities": item_payload.get("caption_entities"),
    }
    parse_cap_html = bool(payload["caption"] and not payload.get("caption_entities") and _looks_like_html(payload["caption"]))
    msg, code, err = await send_with_retry(
        send_single_media(
            bot,
            chat_id,
            item_payload.get("kind", "document"),
            payload,
            parse_caption_html=parse_cap_html,
            reply_markup=kb,
        )
    )
    if code:
        return False, None, code, err
    return True, (msg.message_id if msg else None), None, None


async def _send_album_split(
    bot: Bot,
    chat_id: int,
    album_items: List[Dict[str, Any]],
    text_html: Optional[str],
    kb_for_text: Optional[InlineKeyboardMarkup],
    preview_mode: bool,
) -> Tuple[bool, Optional[Union[int, List[int]]], Optional[str], Optional[str]]:
    """
    Альбом всегда уходит группой (без кнопок и без caption).
    Затем — текст (если есть) с кнопкой; если текста нет, то:
      - в превью добавляем служебное сообщение с кнопками,
      - в бою — кнопок нет совсем.
    """
    try:
        msgs = await send_album(bot, chat_id, album_items)  # sendMediaGroup
        ids = [m.message_id for m in (msgs or [])]
        last_id: Optional[int] = ids[-1] if ids else None

        txt = (text_html or "").strip()
        if txt:
            ok, mid, code, err = await _send_text(bot, chat_id, txt, kb_for_text)
            if not ok:
                return False, None, code, err
            if isinstance(mid, int):
                ids.append(mid)
                last_id = mid
        elif preview_mode and kb_for_text:
            ok, mid, code, err = await _send_text(bot, chat_id, "Предпросмотр. Подтвердить отправку или исправить?", kb_for_text)
            if not ok:
                return False, None, code, err
            if isinstance(mid, int):
                ids.append(mid)
                last_id = mid

        return True, (ids if ids else last_id), None, None
    except Exception as e:
        return False, None, "SendMediaGroupFailed", str(e)


# ---------------- публичные функции ----------------

async def send_preview(
    bot: Bot,
    chat_id: int,
    media: List[Dict[str, Any]],
    kb: Optional[InlineKeyboardMarkup] = None,
) -> Tuple[bool, Optional[Union[int, List[int]]], Optional[str], Optional[str]]:
    """
    SMART-превью:
      - если можно одним сообщением с кнопкой (text/single c допустимой подписью) → отправляем одним;
      - иначе split: альбом → текст с кнопкой;
        для альбома без текста — в превью добавляем служебное сообщение с кнопками.
    """
    try:
        model = _split_analyze(media)

        # 1) one-message + kb
        if _can_one_message_with_kb(model):
            if model["kind"] == "text":
                return await _send_text(bot, chat_id, model["text_html"], kb)
            else:  # single_media
                return await _send_single(bot, chat_id, (model["item"] or {}).get("payload") or {}, kb)

        # 2) split-ветки
        if model["kind"] == "album":
            return await _send_album_split(bot, chat_id, model.get("album") or [], model.get("text_html"), kb, preview_mode=True)

        if model["kind"] == "single_media":
            # подпись не влазит — split: сначала файл без caption, затем текст с кнопкой
            p = (model["item"] or {}).get("payload") or {}
            file_only = {"kind": p.get("kind"), "file_id": p.get("file_id")}
            ok, _, code, err = await _send_single(bot, chat_id, file_only, kb=None)
            if not ok:
                return False, None, code, err
            return await _send_text(bot, chat_id, (p.get("caption") or ""), kb)

        # 3) mixed: отправляем по одному, кнопку — на последнем
        last_mid: Optional[int] = None
        for idx, el in enumerate(model.get("items") or []):
            last = idx == len(model["items"]) - 1
            t = el.get("type")
            p = el.get("payload") or {}
            if t in {"text", "html"}:
                ok, mid, code, err = await _send_text(bot, chat_id, p.get("text") or "", kb if last else None)
            elif t == "media":
                ok, mid, code, err = await _send_single(bot, chat_id, p, kb if last else None)
            else:
                return False, None, "UnknownItemType", f"type={t}"
            if not ok:
                return False, None, code, err
            if isinstance(mid, int):
                last_mid = mid
        return True, last_mid, None, None

    except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter) as e:
        return False, None, classify_exc(e), str(e)
    except Exception as e:
        return False, None, "Unknown", str(e)


async def send_actual(
    bot: Bot,
    chat_id: int,
    media: List[Dict[str, Any]],
    kb_for_text: Optional[InlineKeyboardMarkup] = None,
) -> Tuple[bool, Optional[Union[int, List[int]]], Optional[str], Optional[str]]:
    """
    SMART-боевая отправка:
      - если можно одним сообщением с кнопкой (text/single) → одним;
      - иначе split: альбом (без кнопок) → текст с кнопкой; если текста нет — только альбом.
    """
    try:
        model = _split_analyze(media)

        if _can_one_message_with_kb(model):
            if model["kind"] == "text":
                return await _send_text(bot, chat_id, model["text_html"], kb_for_text)
            else:
                return await _send_single(bot, chat_id, (model["item"] or {}).get("payload") or {}, kb_for_text)

        if model["kind"] == "album":
            return await _send_album_split(bot, chat_id, model.get("album") or [], model.get("text_html"), kb_for_text, preview_mode=False)

        if model["kind"] == "single_media":
            p = (model["item"] or {}).get("payload") or {}
            file_only = {"kind": p.get("kind"), "file_id": p.get("file_id")}
            ok, _, code, err = await _send_single(bot, chat_id, file_only, kb=None)
            if not ok:
                return False, None, code, err
            return await _send_text(bot, chat_id, (p.get("caption") or ""), kb_for_text)

        # mixed: по одному; кнопка — на последнем
        last_mid: Optional[int] = None
        for idx, el in enumerate(model.get("items") or []):
            last = idx == len(model["items"]) - 1
            t = el.get("type")
            p = el.get("payload") or {}
            if t in {"text", "html"}:
                ok, mid, code, err = await _send_text(bot, chat_id, p.get("text") or "", kb_for_text if last else None)
            elif t == "media":
                ok, mid, code, err = await _send_single(bot, chat_id, p, kb_for_text if last else None)
            else:
                return False, None, "UnknownItemType", f"type={t}"
            if not ok:
                return False, None, code, err
            if isinstance(mid, int):
                last_mid = mid
        return True, last_mid, None, None

    except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter) as e:
        return False, None, classify_exc(e), str(e)
    except Exception as e:
        return False, None, "Unknown", str(e)
