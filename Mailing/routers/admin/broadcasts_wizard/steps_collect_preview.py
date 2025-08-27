# Mailing/routers/admin/broadcasts_wizard/steps_collect_preview.py
# Коммит: feat(wizard/text): Шаг 1 — понятные инструкции по контенту; дружелюбные ошибки/подсказки
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ContentType, MessageEntity
from aiogram.fsm.context import FSMContext

from . import PostWizard
from Mailing.keyboards.broadcasts_wizard import kb_preview
from Mailing.services.broadcasts.sender import send_preview, CAPTION_LIMIT

# Если у тебя AlbumsMiddleware в другом модуле — оставь актуальный импорт
from common.middlewares.albums import AlbumsMiddleware

log = logging.getLogger(__name__)

router = Router(name="admin_broadcasts_wizard.collect_preview")
# Один вызов хендлера на всю медиа-группу
router.message.middleware(AlbumsMiddleware(wait=0.6))


# ---------- helpers: приводим вход к единому media_items ----------

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


def _from_single_message(msg: Message) -> List[Dict[str, Any]]:
    """
    Нормализуем одиночный апдейт в unified media_items:
    - текст -> {"type":"text","payload":{"text":...}}
    - одно медиа -> {"type":"media","payload":{"kind","file_id","caption","caption_entities"}}
    """
    if msg.content_type == ContentType.TEXT:
        text_html = _text_html(msg)
        return [{"type": "text", "payload": {"text": text_html}}] if text_html else []

    if msg.content_type in {ContentType.PHOTO, ContentType.VIDEO, ContentType.DOCUMENT}:
        if msg.photo:
            kind, fid = "photo", msg.photo[-1].file_id
        elif msg.video:
            kind, fid = "video", msg.video.file_id
        elif msg.document:
            kind, fid = "document", msg.document.file_id
        else:
            return []
        cap = _caption_html(msg)
        ents = _dump_entities(msg.caption_entities)
        payload: Dict[str, Any] = {"kind": kind, "file_id": fid}
        if cap:
            payload["caption"] = cap
        if ents:
            payload["caption_entities"] = ents
        return [{"type": "media", "payload": payload}]

    return []


def _from_album(messages: List[Message]) -> List[Dict[str, Any]]:
    """
    Альбом: собираем file_id’ы в {"type":"album","payload":{"items":[...]}}
    Общий текст берём из последней непустой подписи.
    """
    items: List[Dict[str, Any]] = []
    last_text = ""
    for m in messages[:10]:  # лимит Telegram на sendMediaGroup
        if m.photo:
            items.append({"type": "photo", "payload": {"file_id": m.photo[-1].file_id}})
        elif m.video:
            items.append({"type": "video", "payload": {"file_id": m.video.file_id}})
        elif m.document:
            items.append({"type": "document", "payload": {"file_id": m.document.file_id}})
        cap = _caption_html(m)
        if cap:
            last_text = cap

    out: List[Dict[str, Any]] = [{"type": "album", "payload": {"items": items}}] if items else []
    if last_text:
        out.append({"type": "text", "payload": {"text": last_text}})
    return out


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
    )
    await state.set_state(PostWizard.collecting)
    await message.answer(
        "<b>Шаг 1. Контент</b>\n"
        "Отправь пост <u>одним сообщением</u>. Подойдёт: текст (HTML), одно медиа или альбом (до 10 файлов).\n"
        "• Если отправляешь альбом — прикрепи все файлы сразу. Текст можно добавить в подпись к первому файлу.\n"
        f"• Лимит подписи у медиа: <b>{CAPTION_LIMIT}</b> символов. При превышении остаток пойдёт отдельным текстом.\n"
        "• Отмена — команда /cancel."
    )


@router.message(PostWizard.collecting, ~F.text.regexp(r"^/"))
async def on_content(message: Message, state: FSMContext, album: Optional[List[Message]] = None):
    """
    Единая точка приёма: либо одиночное сообщение, либо уже собранный альбом (список Message) из AlbumsMiddleware.
    """
    media_items = _from_album(album) if album else _from_single_message(message)

    if not media_items:
        await message.answer("Я не распознал сообщение. Пришли текст, одно медиа или альбом (группой).")
        return

    ok, _, code, err = await send_preview(message.bot, message.chat.id, media_items, kb=kb_preview())
    if not ok:
        await message.answer(f"❌ Не получилось показать предпросмотр: {code or 'Unknown'} — {err or ''}")
        return

    await state.update_data(content_media=media_items)
    await state.set_state(PostWizard.preview)


@router.message(PostWizard.preview, ~F.text.regexp(r"^/"))
async def on_content_replace(message: Message, state: FSMContext, album: Optional[List[Message]] = None):
    """
    Замена контента на этапе превью — повторяем сбор и превью.
    """
    await state.set_state(PostWizard.collecting)
    await on_content(message, state, album=album)


@router.callback_query(PostWizard.preview, F.data == "post:preview_edit")
async def preview_edit(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(content_media=None)
    await state.set_state(PostWizard.collecting)
    await cb.message.answer(
        "<b>Исправление контента</b>\n"
        "Пришли заново: текст (HTML), медиа или альбом. Напомню: альбом — до 10 файлов, подпись — в пределах лимита Telegram."
    )


@router.callback_query(PostWizard.preview, F.data == "post:preview_ok")
async def preview_ok(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=None)
    await state.set_state(PostWizard.title_wait)
    await cb.message.answer(
        "<b>Шаг 2. Название</b>\n"
        "Введи короткое имя рассылки. Это видно только администраторам — для списка и поиска."
    )
