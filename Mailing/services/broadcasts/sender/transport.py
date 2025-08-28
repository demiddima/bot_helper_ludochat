# Mailing/services/broadcasts/sender/transport.py
# Python 3.11+, aiogram v3
# feat(sender): авто-кнопка «Настроить рассылки» (callback) для одиночных сообщений.
# Альбомы (sendMediaGroup) — без кнопки (Bot API не поддерживает).
# Дополнительно: единый детектор HTML и аккуратная работа с entities.

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Union

from aiogram import Bot
from aiogram.types import (
    Message,
    MessageEntity,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
)

# --- imports проекта ---
from Mailing.keyboards.subscriptions import subscriptions_kb  # ← callback 'subs:open'

# --- helpers: HTML / entities ---

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

# --- subscriptions keyboard injection ---

def _with_subscriptions_markup(
    current_markup: Optional[InlineKeyboardMarkup],
    *,
    enabled: bool = True,
) -> Optional[InlineKeyboardMarkup]:
    """
    Если разметка уже есть — уважаем её.
    Иначе (enabled=True) — подмешиваем одну кнопку «Настроить рассылки» (callback 'subs:open').
    """
    if current_markup is not None or not enabled:
        return current_markup
    return subscriptions_kb()

# --- API отправки ---

async def send_text(
    bot: Bot,
    chat_id: Union[int, str],
    text: str,
    *,
    entities: Optional[Sequence[Any]] = None,
    parse_html: bool = False,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    attach_subscriptions: bool = True,
) -> Message:
    """
    Одиночное текстовое сообщение рассылки.
    Если reply_markup не передан и attach_subscriptions=True — добавляем кнопку «Настроить рассылки».
    """
    reply_markup = _with_subscriptions_markup(reply_markup, enabled=attach_subscriptions)
    ents = _as_entities(entities)

    if ents:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            entities=ents,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    if parse_html or _looks_like_html(text):
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    return await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )

async def send_single_media(
    bot: Bot,
    chat_id: Union[int, str],
    media_type: str,
    payload: Dict[str, Any],
    *,
    parse_caption_html: bool = False,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    attach_subscriptions: bool = True,
) -> Message:
    """
    Одна медиа: photo|video|document.
    Если reply_markup не передан и attach_subscriptions=True — добавляем кнопку «Настроить рассылки».
    """
    reply_markup = _with_subscriptions_markup(reply_markup, enabled=attach_subscriptions)

    file_id = str(payload.get("file_id"))
    caption = payload.get("caption")
    caption_entities = _as_entities(payload.get("caption_entities"))

    parse_mode = None
    if parse_caption_html and caption and not caption_entities and _looks_like_html(caption):
        parse_mode = "HTML"

    if media_type == "photo":
        return await bot.send_photo(
            chat_id=chat_id,
            photo=file_id,
            caption=caption,
            caption_entities=caption_entities,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )

    if media_type == "video":
        return await bot.send_video(
            chat_id=chat_id,
            video=file_id,
            caption=caption,
            caption_entities=caption_entities,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )

    # document и «прочее» сводим к document
    return await bot.send_document(
        chat_id=chat_id,
        document=file_id,
        caption=caption,
        caption_entities=caption_entities,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
    )

async def send_album(
    bot: Bot,
    chat_id: Union[int, str],
    items: List[Dict[str, Any]],
) -> List[Message]:
    """
    Альбом до 10 элементов (photo|video|document).
    Подпись (и caption_entities/HTML) ставим у ПЕРВОГО элемента.
    ВАЖНО: reply_markup у sendMediaGroup НЕ поддерживается — кнопку не добавляем.
    """
    if not items:
        return []

    media: List[Union[InputMediaPhoto, InputMediaVideo, InputMediaDocument]] = []

    for idx, it in enumerate(items[:10]):
        t = (it.get("type") or "document").lower()
        p = it.get("payload") or {}
        file_id = str(p.get("file_id"))

        caption = p.get("caption") if idx == 0 else None
        caption_entities = _as_entities(p.get("caption_entities")) if idx == 0 else None
        parse_mode = "HTML" if (idx == 0 and caption and not caption_entities and _looks_like_html(caption)) else None

        if t == "photo":
            media.append(
                InputMediaPhoto(
                    media=file_id,
                    caption=caption,
                    caption_entities=caption_entities,
                    parse_mode=parse_mode,
                )
            )
        elif t == "video":
            media.append(
                InputMediaVideo(
                    media=file_id,
                    caption=caption,
                    caption_entities=caption_entities,
                    parse_mode=parse_mode,
                )
            )
        else:
            media.append(
                InputMediaDocument(
                    media=file_id,
                    caption=caption,
                    caption_entities=caption_entities,
                    parse_mode=parse_mode,
                )
            )

    return await bot.send_media_group(chat_id=chat_id, media=media)
