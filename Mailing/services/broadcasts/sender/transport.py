# Mailing/services/broadcasts/sender/transport.py
# Commit: fix(transport): единый маппинг типов, reply_markup, корректные альбомы

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
    if entities:
        return await bot.send_message(chat_id=chat_id, text=text, entities=entities, reply_markup=reply_markup)
    if parse_html:
        return await bot.send_message(
            chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=reply_markup, disable_web_page_preview=True
        )
    return await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, disable_web_page_preview=True)


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

    parse_mode = None
    if parse_caption_html and caption and not caption_entities and ("<" in caption and ">" in caption):
        parse_mode = "HTML"

    if media_type == "photo":
        return await bot.send_photo(
            chat_id, file_id, caption=caption, caption_entities=caption_entities, reply_markup=reply_markup, parse_mode=parse_mode
        )
    if media_type == "video":
        return await bot.send_video(
            chat_id, file_id, caption=caption, caption_entities=caption_entities, reply_markup=reply_markup, parse_mode=parse_mode
        )
    return await bot.send_document(
        chat_id, file_id, caption=caption, caption_entities=caption_entities, reply_markup=reply_markup
    )


async def send_album(bot: Bot, chat_id: int, items: List[Dict[str, Any]]) -> List[Message]:
    if not items:
        return []

    media: List[Any] = []
    for it in items[:10]:
        t = (it.get("type") or "document").lower()
        p = it.get("payload") or {}
        file_id = str(p.get("file_id"))
        if t == "photo":
            media.append(InputMediaPhoto(media=file_id))
        elif t == "video":
            media.append(InputMediaVideo(media=file_id))
        else:
            media.append(InputMediaDocument(media=file_id))
    return await bot.send_media_group(chat_id, media)
