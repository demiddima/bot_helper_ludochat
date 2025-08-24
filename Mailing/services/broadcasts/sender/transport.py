# Mailing/services/broadcasts/sender/transport.py
# Транспортный слой: строгий маппинг типов на методы Bot.

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from aiogram import Bot
from aiogram.types import (
    Message,
    MessageEntity,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
)


def _as_entities(seq: Optional[Sequence[Any]]) -> Optional[List[MessageEntity]]:
    if not seq:
        return None
    out: List[MessageEntity] = []
    for e in seq:
        if isinstance(e, MessageEntity):
            out.append(e)
        else:
            out.append(MessageEntity.model_validate(e))
    return out


async def send_text(
    bot: Bot,
    chat_id: int,
    text: str,
    *,
    entities: Optional[Sequence[Any]] = None,
    parse_html: bool = False,
) -> Message:
    if parse_html:
        return await bot.send_message(
            chat_id,
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    return await bot.send_message(
        chat_id,
        text,
        entities=_as_entities(entities),
        disable_web_page_preview=True,
    )


async def send_single_media(
    bot: Bot,
    chat_id: int,
    media_type: str,
    payload: Dict[str, Any],
    *,
    parse_caption_html: bool = False,
) -> Message:
    """
    media_type: 'photo' | 'video' | 'document'
    payload: {'file_id': str, 'caption'?: str, 'caption_entities'?: list[MessageEntity|dict]}
    """
    file_id = str(payload.get("file_id"))
    caption = payload.get("caption")
    caption_entities = _as_entities(payload.get("caption_entities"))

    if media_type == "photo":
        return await bot.send_photo(
            chat_id,
            file_id,
            caption=caption,
            caption_entities=None if parse_caption_html else caption_entities,
            parse_mode="HTML" if parse_caption_html else None,
        )
    if media_type == "video":
        return await bot.send_video(
            chat_id,
            file_id,
            caption=caption,
            caption_entities=None if parse_caption_html else caption_entities,
            parse_mode="HTML" if parse_caption_html else None,
        )
    if media_type == "document":
        return await bot.send_document(
            chat_id,
            file_id,
            caption=caption,
            caption_entities=None if parse_caption_html else caption_entities,
            parse_mode="HTML" if parse_caption_html else None,
        )

    # Неподдерживаемый тип — безопасный fallback как документ
    return await bot.send_document(
        chat_id,
        file_id,
        caption=caption,
        caption_entities=None if parse_caption_html else caption_entities,
        parse_mode="HTML" if parse_caption_html else None,
    )


async def send_album(bot: Bot, chat_id: int, items: List[Dict[str, Any]]) -> List[Message]:
    """
    items: список элементов формата {'type': 'photo'|'video'|'document', 'payload': {...}}
    Telegram принимает до 10 элементов в альбоме.
    Особенности совместимости:
      - caption у DOCUMENT в альбоме НЕ ставим (как в старом монолите);
      - если у элемента нет caption_entities и есть caption «с HTML» — используем parse_mode=HTML.
    """
    if not items:
        return []

    media: List[Any] = []
    for it in items[:10]:
        t = (it.get("type") or "document").lower()
        p = it.get("payload") or {}
        file_id = str(p.get("file_id"))
        caption = p.get("caption")
        caption_entities = _as_entities(p.get("caption_entities"))

        # parse_mode=HTML только при отсутствии entities и наличии "похожего на HTML" текста
        parse_mode = None
        if caption and not caption_entities and ("<" in caption and ">" in caption):
            parse_mode = "HTML"

        if t == "photo":
            media.append(InputMediaPhoto(media=file_id, caption=caption, caption_entities=caption_entities, parse_mode=parse_mode))
        elif t == "video":
            media.append(InputMediaVideo(media=file_id, caption=caption, caption_entities=caption_entities, parse_mode=parse_mode))
        else:
            # Для документа в альбоме подпись убираем (совместимость)
            media.append(InputMediaDocument(media=file_id))

    return await bot.send_media_group(chat_id, media)
