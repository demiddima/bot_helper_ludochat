# handlers/admin/broadcasts_wizard/steps_schedule_finalize.py
# commit: extract schedule + finalize; save content as text/files; no invalid 'queued' status
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple, Union
from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ContentType
from aiogram.fsm.context import FSMContext

from . import PostWizard
from Mailing.keyboards.broadcasts_wizard import kb_schedule
from common.utils.time_msk import parse_msk
from common.db_api import db_api_client
from Mailing.services.broadcasts.service import try_send_now
from Mailing.services.local_scheduler import schedule_broadcast_send

log = logging.getLogger(__name__)
router = Router(name="admin_broadcasts_wizard.schedule_finalize")
MSK = ZoneInfo("Europe/Moscow")


def _media_items_to_text_files(media: List[Dict[str, Any]]) -> Tuple[str, str]:
    text_html: str = ""
    file_ids: List[str] = []
    last_caption: Optional[str] = None

    for item in media or []:
        t = (item.get("type") or "").lower()
        payload = item.get("payload") or {}

        if t in {"text", "html"}:
            txt = (payload.get("text") or "").strip()
            if txt and not text_html:
                text_html = txt
        elif t in {"photo", "video", "document"}:
            fid = str(payload.get("file_id") or "").strip()
            if fid:
                file_ids.append(fid)
            cap = (payload.get("caption") or "").strip()
            if cap:
                last_caption = cap
        elif t == "album":
            for sub in (payload.get("items") or []):
                sp = sub.get("payload") or {}
                fid = str(sp.get("file_id") or "").strip()
                if fid:
                    file_ids.append(fid)
                cap = (sp.get("caption") or "").strip()
                if cap:
                    last_caption = cap

    if not text_html and last_caption:
        text_html = last_caption

    return text_html, ",".join(file_ids)


@router.callback_query(PostWizard.choose_schedule, F.data == "sch:now")
async def sch_now(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await _finalize_and_start(cb, state, mode="now", at=None)


@router.callback_query(PostWizard.choose_schedule, F.data == "sch:manual")
async def sch_manual(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await cb.message.edit_text(
        "Введи дату и время <b>в МСК</b> в одном из форматов:\n"
        "• <code>YYYY-MM-DD HH:MM</code>\n"
        "• <code>DD.MM.YYYY HH:MM</code>\n\n"
        "Часовой пояс: Europe/Moscow."
    )


@router.message(PostWizard.choose_schedule, F.content_type == ContentType.TEXT, ~F.text.regexp(r"^/"))
async def sch_manual_input(message: Message, state: FSMContext):
    dt = parse_msk(message.text or "")
    if not dt:
        await message.answer("Не понял дату/время. Пример: <code>2025-08-23 20:30</code> (МСК)")
        return
    await _finalize_and_start(message, state, mode="at", at=dt)


async def _finalize_and_start(evt: Union[Message, CallbackQuery], state: FSMContext, *, mode: str, at: Optional[datetime]):
    data = await state.get_data()
    media_items = data.get("content_media")
    title = data.get("title")
    kind = data.get("kind")
    target = data.get("target")

    if not media_items or not title or not kind or not target:
        txt = "Не хватает данных для рассылки. Начни заново: /post"
        if isinstance(evt, CallbackQuery):
            await evt.message.answer(txt)
        else:
            await evt.answer(txt)
        await state.clear()
        return

    # Создаём черновик в старом формате {text, files}
    text_html, files_csv = _media_items_to_text_files(media_items)
    br = await db_api_client.create_broadcast(
        kind=kind,
        title=title,
        content={"text": text_html, "files": files_csv},
        status="draft",
    )
    await db_api_client.put_broadcast_target(br["id"], target)

    # Отправка / планирование
    bot = evt.message.bot if isinstance(evt, CallbackQuery) else evt.bot
    if mode == "now":
        await try_send_now(bot, br["id"])
        txt = f"✅ Создано и отправляется: <b>#{br['id']}</b>"
    else:
        at_msk = at.astimezone(MSK)
        msk_naive = at_msk.replace(tzinfo=None)
        iso_naive = msk_naive.strftime("%Y-%m-%d %H:%M:%S")
        await db_api_client.update_broadcast(br["id"], status="scheduled", scheduled_at=iso_naive)
        schedule_broadcast_send(bot, br["id"], at_msk)
        txt = f"💾 Запланировано и поставлено локально: <b>#{br['id']}</b> на {iso_naive} (МСК)"

    if isinstance(evt, CallbackQuery):
        await evt.message.answer(txt)
    else:
        await evt.answer(txt)
    await state.clear()
