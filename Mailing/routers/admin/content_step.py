# Mailing/routers/admin/conten_step.py
# Commit: feat(wizard): сбор контента в одно сообщение; media_group через middleware; превью = как в проде

from __future__ import annotations

from typing import List, Optional

from aiogram import Router, F
from aiogram.types import Message

from common.middlewares.albums import AlbumsMiddleware
from services.content_builder import make_media_items_from_event
from Mailing.services.broadcasts.sender.facade import send_preview
from Mailing.keyboards import subscriptions_kb

router = Router(name="broadcasts_content_admin")
router.message.middleware(AlbumsMiddleware(wait=0.6))


@router.message(F.photo | F.video | F.document | F.text)
async def broadcasts_content_step(message: Message, album: Optional[List[Message]] = None):
    items = make_media_items_from_event(message, album)
    ok, _, code, reason = await send_preview(
        bot=message.bot,
        chat_id=message.chat.id,
        media=items,
        kb=subscriptions_kb(),  # превью ровно как в проде: если кнопка допустима — она будет
    )
    if not ok:
        await message.answer(f"❌ Предпросмотр отклонён: {reason or code}")
