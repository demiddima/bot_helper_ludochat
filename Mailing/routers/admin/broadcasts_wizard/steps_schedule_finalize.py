# Mailing/routers/admin/broadcasts_wizard/steps_schedule_finalize.py
# commit: fix(wizard/finalize): сохраняем content как {"text": "...", "files": "id1,id2,..."} из media_items

from __future__ import annotations

import logging
from typing import Optional, Union, List, Dict, Any
from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ContentType
from aiogram.fsm.context import FSMContext

from . import PostWizard
from Mailing.keyboards.broadcasts_wizard import kb_schedule  # на будущее
from common.utils.time_msk import parse_msk
from common.db_api import db_api_client
from Mailing.services.broadcasts.service import try_send_now
from Mailing.services.local_scheduler import schedule_broadcast_send

log = logging.getLogger(__name__)
router = Router(name="admin_broadcasts_wizard.schedule_finalize")
MSK = ZoneInfo("Europe/Moscow")


def _to_csv_content(media_items: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Преобразуем unified media_items в ожидаемый backend-формат:
      {"text": "<html...>", "files": "id1,id2,..."}
    Правила:
      - text берём из ПОСЛЕДНЕГО элемента {"type":"text"|"html"} или caption у single media, если текст отсутствует.
      - file_id собираем из:
         * {"type":"media"} → payload.file_id
         * {"type":"album"} → из каждого items[i].payload.file_id (до 10 шт — лимит TG)
      - порядок сохраняем.
    """
    text = ""
    ids: List[str] = []

    for el in media_items or []:
        t = (el.get("type") or "").lower()
        p = el.get("payload") or {}

        if t in {"text", "html"}:
            txt = (p.get("text") or "").strip()
            if txt:
                text = txt

        elif t == "media":
            fid = (p.get("file_id") or "").strip()
            if fid:
                ids.append(fid)
            # если текста ещё не было — можно взять caption как текст
            if not text:
                cap = (p.get("caption") or "").strip()
                if cap:
                    text = cap

        elif t == "album":
            items = (p.get("items") or [])[:10]  # лимит TG 10
            for it in items:
                it_fid = ((it.get("payload") or {}).get("file_id") or "").strip()
                if it_fid:
                    ids.append(it_fid)

    return {"text": text, "files": ",".join(ids)}


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
    media_items = data.get("content_media")  # unified формат превью
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

    # ВАЖНО: backend ожидает {"text": "...", "files": "id1,id2,..."}
    content_csv = _to_csv_content(media_items)

    br = await db_api_client.create_broadcast(
        kind=kind,
        title=title,
        content=content_csv,
        status="draft",
    )
    await db_api_client.put_broadcast_target(br["id"], target)

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
