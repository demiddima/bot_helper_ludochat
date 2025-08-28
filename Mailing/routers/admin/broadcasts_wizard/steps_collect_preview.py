# Mailing/routers/admin/broadcasts_wizard/steps_collect_preview.py
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ContentType
from aiogram.fsm.context import FSMContext

from . import PostWizard
from Mailing.keyboards.broadcasts_wizard import kb_preview
# ВАЖНО: для превью используем send_preview (он сам умеет слать отдельное сообщение с кнопками при необходимости)
from Mailing.services.broadcasts.sender import send_preview, CAPTION_LIMIT
from common.middlewares.albums import AlbumsMiddleware

log = logging.getLogger(__name__)

router = Router(name="admin_broadcasts_wizard.collect_preview")
router.message.middleware(AlbumsMiddleware(wait=0.6))


# ---------- helpers: нормализуем вход (без entities) ----------

def _make_text_item(text: str) -> Dict[str, Any]:
    return {"type": "text", "payload": {"text": (text or "").strip()}}

def _make_media_item(kind: str, file_id: str, caption: Optional[str]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"kind": kind, "file_id": str(file_id)}
    if caption:
        payload["caption"] = caption
    return {"type": "media", "payload": payload}

def _from_single_message(msg: Message) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if msg.content_type == ContentType.TEXT:
        text = (msg.text or "").strip()
        if text:
            items.append(_make_text_item(text))
        return items
    if msg.photo:
        items.append(_make_media_item("photo", msg.photo[-1].file_id, msg.caption or None)); return items
    if msg.video:
        items.append(_make_media_item("video", msg.video.file_id, msg.caption or None)); return items
    if msg.document:
        items.append(_make_media_item("document", msg.document.file_id, msg.caption or None)); return items
    return items

def _from_album(messages: List[Message]) -> List[Dict[str, Any]]:
    if not messages:
        return []
    album_items: List[Dict[str, Any]] = []
    for idx, m in enumerate(messages[:10]):
        cap = (m.caption or None) if idx == 0 else None
        if m.photo:
            album_items.append({"type": "photo", "payload": {"file_id": m.photo[-1].file_id, "caption": cap}})
        elif m.video:
            album_items.append({"type": "video", "payload": {"file_id": m.video.file_id, "caption": cap}})
        elif m.document:
            album_items.append({"type": "document", "payload": {"file_id": m.document.file_id, "caption": cap}})
    if not album_items:
        return []
    return [{"type": "album", "payload": {"items": album_items}}]


# ---------- handlers ----------

@router.message(Command("post"))
async def cmd_post(message: Message, state: FSMContext):
    await state.clear()
    await state.update_data(
        content_media=None,
        title=None,            # это просто поле в data, НЕ state
        kind=None,
        target=None,
        schedule={"mode": None, "at": None},
    )
    await state.set_state(PostWizard.collecting)
    await message.answer(
        "<b>Шаг 1. Контент</b>\n"
        "Отправь пост <u>одним сообщением</u>. Допустимо: текст (HTML), одно медиа или альбом (до 10 файлов).\n"
        f"• Лимит подписи к медиа: <b>{CAPTION_LIMIT}</b> символов. Сверх лимита уйдёт отдельным сообщением.\n"
        "• Отмена — /cancel."
    )


@router.message(PostWizard.collecting, ~F.text.regexp(r"^/"))
async def on_content(message: Message, state: FSMContext, album: Optional[List[Message]] = None):
    media_items = _from_album(album) if album else _from_single_message(message)
    if not media_items:
        await message.answer("Я не распознал сообщение. Пришли текст, одно медиа или альбом (группой).")
        return

    # В превью: если можно — к самому сообщению; если нельзя — фасад сам вышлет отдельное сообщение с кнопками.
    kb = kb_preview()

    ok, _, code, err = await send_preview(message.bot, message.chat.id, media_items, kb=kb)
    if not ok:
        await message.answer(f"❌ Не удалось показать предпросмотр: {code or 'Unknown'} — {err or ''}")
        return

    await state.update_data(content_media=media_items)
    await state.set_state(PostWizard.preview)


# ----- callbacks -----

@router.callback_query(PostWizard.preview, F.data.in_({"post:preview_edit", "post:edit", "post:fix"}))
async def cb_preview_edit(cb: CallbackQuery, state: FSMContext):
    await cb.answer("Исправляем")
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await state.update_data(content_media=None)
    await state.set_state(PostWizard.collecting)
    await cb.message.answer(
        "<b>Исправление контента</b>\n"
        "Пришли заново: текст (HTML), медиа или альбом. Напомню: альбом — до 10 файлов; подпись будет у первого элемента."
    )

@router.callback_query(PostWizard.preview, F.data.in_({"post:preview_ok", "post:ok", "post:next", "post:continue"}))
async def cb_preview_ok(cb: CallbackQuery, state: FSMContext):
    await cb.answer("Ок")
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await state.set_state(PostWizard.title_wait)  # следующий реальный стейт из рабочего архива
    await cb.message.answer("<b>Шаг 2. Название</b>\nПришли короткое название рассылки (видно только админам).")

@router.callback_query(F.data.in_({"cancel", "post:cancel", "wizard:cancel"}))
async def cb_cancel(cb: CallbackQuery, state: FSMContext):
    await cb.answer("Отменено")
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await state.clear()
    await cb.message.answer("Окей, отменил визард рассылки.")
