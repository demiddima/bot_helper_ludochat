# Mailing/services/broadcasts/sender/transport.py
# Python 3.11+, aiogram v3
# Изменения:
# - Поддержка подписи в альбомах (caption/caption_entities у ПЕРВОГО элемента + parse_mode="HTML" при необходимости)
# - Фолбэк parse_mode="HTML" для document в одиночной отправке (раньше не ставился)
# - Единый детектор HTML (_looks_like_html)

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from aiogram import Bot
from aiogram.types import (
    Message,
    MessageEntity,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
)

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


async def send_text(
    bot: Bot,
    chat_id: int,
    text: str,
    *,
    entities: Optional[Sequence[Any]] = None,
    parse_html: bool = False,
    reply_markup: Optional[Any] = None,
) -> Message:
    ents = _as_entities(entities)
    if ents:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            entities=ents,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    if parse_html:
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
    chat_id: int,
    media_type: str,
    payload: Dict[str, Any],
    *,
    parse_caption_html: bool = False,
    reply_markup: Optional[Any] = None,
) -> Message:
    file_id = str(payload.get("file_id"))
    caption = payload.get("caption")
    caption_entities = _as_entities(payload.get("caption_entities"))

    # Если явно переданы entities — доверяем им, parse_mode не задаём.
    parse_mode = None
    if parse_caption_html and caption and not caption_entities and _looks_like_html(caption):
        parse_mode = "HTML"

    if media_type == "photo":
        return await bot.send_photo(
            chat_id,
            file_id,
            caption=caption,
            caption_entities=caption_entities,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
    if media_type == "video":
        return await bot.send_video(
            chat_id,
            file_id,
            caption=caption,
            caption_entities=caption_entities,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
    # document
    return await bot.send_document(
        chat_id,
        file_id,
        caption=caption,
        caption_entities=caption_entities,
        parse_mode=parse_mode,  # ← раньше не ставилось, HTML не рендерился
        reply_markup=reply_markup,
    )


async def send_album(bot: Bot, chat_id: int, items: List[Dict[str, Any]]) -> List[Message]:
    """
    Отправка альбома (до 10 элементов).
    Подпись (и её caption_entities) ставим у ПЕРВОГО элемента, как требует Bot API.
    Если у подписи нет entities, но она похожа на HTML — применяем parse_mode="HTML".
    """
    if not items:
        return []

    media: List[Any] = []
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

    return await bot.send_media_group(chat_id, media)
