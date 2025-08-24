# handlers/admin/broadcasts_wizard/steps_collect_preview.py
# commit: extract collecting & preview flow; album debounce, preview send
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ContentType, MessageEntity
from aiogram.fsm.context import FSMContext

from . import PostWizard
from Mailing.keyboards.broadcasts_wizard import kb_preview
from Mailing.services.broadcasts.sender import send_preview, CAPTION_LIMIT
from Mailing.services.content_builder import make_media_items

log = logging.getLogger(__name__)
router = Router(name="admin_broadcasts_wizard.collect_preview")


# ---------- helpers ----------

def _dump_entities(ents: Optional[List[MessageEntity]]) -> Optional[List[Dict[str, Any]]]:
    if not ents:
        return None
    try:
        return [e.model_dump() for e in ents]
    except Exception:
        return None

def _text_html(msg: Message) -> str:
    return (getattr(msg, "html_text", None) or msg.text or "").strip()

def _caption_html(msg: Message) -> str:
    return (getattr(msg, "caption_html", None) or msg.caption or "").strip()

def _collected_from_single_message(msg: Message) -> Dict[str, Any]:
    if msg.content_type == ContentType.TEXT:
        text_html = _text_html(msg)
        return {"text_html": text_html} if text_html else {}

    if msg.content_type in {ContentType.PHOTO, ContentType.VIDEO, ContentType.DOCUMENT}:
        if msg.photo:
            t, fid = "photo", msg.photo[-1].file_id
        elif msg.video:
            t, fid = "video", msg.video.file_id
        elif msg.document:
            t, fid = "document", msg.document.file_id
        else:
            return {}

        cap = _caption_html(msg)
        ents = _dump_entities(msg.caption_entities)
        return {
            "single_media": [{
                "type": t,
                "file_id": fid,
                "caption": cap if cap else None,
                "caption_entities": ents if ents else None,
            }]
        }

    return {}

def _append_album_piece(bucket: Dict[str, Any], msg: Message) -> None:
    if msg.photo:
        t, fid = "photo", msg.photo[-1].file_id
    elif msg.video:
        t, fid = "video", msg.video.file_id
    elif msg.document:
        t, fid = "document", msg.document.file_id
    else:
        return

    cap = _caption_html(msg)
    ents = _dump_entities(msg.caption_entities)

    bucket.setdefault("items", []).append({
        "type": t,
        "file_id": fid,
        "caption": cap if cap else None,
        "caption_entities": ents if ents else None,
    })

async def _safe_clear_kb(cb: CallbackQuery) -> None:
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

async def _finalize_album_preview(message: Message, state: FSMContext, media_group_id: str) -> None:
    await asyncio.sleep(0.8)
    data = await state.get_data()
    bucket = (data or {}).get("album_bucket")
    if not bucket or bucket.get("id") != media_group_id:
        return

    album_items: List[Dict[str, Any]] = []
    for el in bucket.get("items", [])[:10]:
        entry = {"type": el["type"], "payload": {"file_id": el["file_id"]}}
        if el.get("caption"):
            entry["payload"]["caption"] = el["caption"]
        if el.get("caption_entities"):
            entry["payload"]["caption_entities"] = el["caption_entities"]
        album_items.append(entry)

    media_items = [{"type": "album", "payload": {"items": album_items}, "position": 0}]

    ok, _, code, err = await send_preview(message.bot, message.chat.id, media_items, kb=kb_preview())
    if not ok:
        if code == "CaptionTooLong":
            await message.answer(f"❌ Подпись в альбоме длиннее {CAPTION_LIMIT} символов. Сократи текст и пришли заново.")
        else:
            await message.answer(f"❌ Превью не отправилось: {code or 'Unknown'} — {err or ''}")
        await state.update_data(album_bucket=None)
        return

    await state.update_data(content_media=media_items, album_bucket=None)
    await state.set_state(PostWizard.preview)


# ---------- handlers ----------

@router.message(Command("post"))
async def cmd_post(message: Message, state: FSMContext):
    await state.clear()
    await state.update_data(
        content_media=None,
        title=None,
        kind=None,
        target=None,
        schedule={"mode": None, "at": None},
        album_bucket=None,
    )
    await state.set_state(PostWizard.collecting)
    await message.answer(
        "Пришли контент ОДНИМ сообщением: текст (HTML) или медиа (фото/видео/док) — либо альбом (несколько файлов). "
        f"Сразу покажу предпросмотр с кнопками. Лимит подписи к медиа: <b>{CAPTION_LIMIT}</b> символов."
    )


@router.message(PostWizard.collecting, ~F.text.regexp(r"^/"))
async def on_content_any(message: Message, state: FSMContext):
    if message.media_group_id:
        data = await state.get_data()
        bucket = (data or {}).get("album_bucket")
        if not bucket or bucket.get("id") != message.media_group_id:
            bucket = {"id": message.media_group_id, "items": []}
        _append_album_piece(bucket, message)
        await state.update_data(album_bucket=bucket)
        asyncio.create_task(_finalize_album_preview(message, state, message.media_group_id))
        return

    collected = _collected_from_single_message(message)
    media_items = make_media_items(collected)

    if not media_items:
        await message.answer("Не понял формат. Пришли текст или медиа (photo/video/document).")
        return

    ok, _, code, err = await send_preview(message.bot, message.chat.id, media_items, kb=kb_preview())
    if not ok:
        if code == "CaptionTooLong":
            await message.answer(f"❌ Подпись длиннее {CAPTION_LIMIT} символов. Сократи текст и пришли заново.")
        else:
            await message.answer(f"❌ Превью не отправилось: {code or 'Unknown'} — {err or ''}")
        return

    await state.update_data(content_media=media_items)
    await state.set_state(PostWizard.preview)


@router.message(PostWizard.preview, ~F.text.regexp(r"^/"))
async def on_content_replace(message: Message, state: FSMContext):
    await state.set_state(PostWizard.collecting)
    await on_content_any(message, state)


@router.callback_query(PostWizard.preview, F.data == "post:preview_edit")
async def preview_edit(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await _safe_clear_kb(cb)
    await state.update_data(content_media=None, album_bucket=None)
    await state.set_state(PostWizard.collecting)
    await cb.message.answer("Ок, пришли новый контент: текст/медиа или альбом.")


@router.callback_query(PostWizard.preview, F.data == "post:preview_ok")
async def preview_ok(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await _safe_clear_kb(cb)
    await state.set_state(PostWizard.title_wait)
    await cb.message.answer("Введи <b>название рассылки</b> (коротко).")
