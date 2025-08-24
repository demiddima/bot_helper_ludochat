# handlers/admin/broadcasts_wizard.py
# Админ-визард рассылки: /post → ввод контента → автопревью (тем же Sender)
# → Подтвердить/Исправить → заголовок → тип → аудитория → дата → создание и запуск/планирование.

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union
from html import escape as _html_escape
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    ContentType,
    MessageEntity,
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

# Клавиатуры в отдельном модуле
from keyboards.broadcasts_wizard import kb_kinds, kb_audience, kb_schedule, kb_preview

# Отправка/предпросмотр контента
from services.broadcasts.sender import send_preview, CAPTION_LIMIT
from services.content_builder import make_media_items

# Бэкенд и запуск
from services.db_api import db_api_client
from services.broadcasts.service import try_send_now
from services.local_scheduler import schedule_broadcast_send

# Аудитории и время
from services.audience import normalize_ids, audience_preview_text
from utils.time_msk import parse_msk  # aware(MSK)

log = logging.getLogger(__name__)
router = Router(name="admin_broadcasts_wizard")

MSK = ZoneInfo("Europe/Moscow")


# ====================== FSM ======================

class PostWizard(StatesGroup):
    collecting = State()        # ждём контент (в т.ч. альбом)
    preview = State()           # показали предпросмотр, ждём ОК/исправить
    title_wait = State()
    choose_kind = State()
    choose_audience = State()
    audience_ids_wait = State()
    audience_sql_wait = State()
    choose_schedule = State()


# ====================== Утилиты сборки ======================

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
    """
    Приводим одиночное сообщение к collected-формату для ContentBuilder:
      - TEXT → {"text_html": "<HTML>"}
      - PHOTO/VIDEO/DOCUMENT → {"single_media": [{"type","file_id","caption","caption_entities"}]}
    """
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
    """Кладём элемент альбома в bucket['items']."""
    if msg.photo:
        t, fid = "photo", msg.photo[-1].file_id
    elif msg.video:
        t, fid = "video", msg.video.file_id
    elif msg.document:
        t, fid = "document", msg.document.file_id
    else:
        return  # пропускаем неизвестные типы

    cap = _caption_html(msg)
    ents = _dump_entities(msg.caption_entities)

    bucket.setdefault("items", []).append({
        "type": t,
        "file_id": fid,
        "caption": cap if cap else None,
        "caption_entities": ents if ents else None,
    })


async def _safe_clear_kb(cb: CallbackQuery) -> None:
    """Пытаемся снять inline-клавиатуру у сообщения предпросмотра (медиа/альбом)."""
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


# ====================== Обработка альбомов ======================

async def _finalize_album_preview(message: Message, state: FSMContext, media_group_id: str) -> None:
    """
    Дебаунс: ждём остальные элементы альбома, строим media_items и шлём предпросмотр.
    """
    await asyncio.sleep(0.8)  # даём догрузиться остальным частям

    data = await state.get_data()
    bucket = (data or {}).get("album_bucket")
    if not bucket or bucket.get("id") != media_group_id:
        return  # уже сброшено/заменено

    # Собираем album → media_items
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

    # Сохраняем контент и сбрасываем bucket
    await state.update_data(content_media=media_items, album_bucket=None)
    await state.set_state(PostWizard.preview)


# ====================== Команды/хендлеры ======================

@router.message(Command("post"))
async def cmd_post(message: Message, state: FSMContext):
    await state.clear()
    await state.update_data(
        content_media=None,     # подтверждённый нормализованный контент (список media items)
        title=None,
        kind=None,
        target=None,
        schedule={"mode": None, "at": None},
        album_bucket=None,      # временный сборщик альбома
    )
    await state.set_state(PostWizard.collecting)
    await message.answer(
        "Пришли контент ОДНИМ сообщением: текст (HTML) или медиа (фото/видео/док) — либо альбом (несколько файлов). "
        f"Сразу покажу предпросмотр с кнопками. Лимит подписи к медиа: <b>{CAPTION_LIMIT}</b> символов."
    )


# Любой контент в состоянии collecting
@router.message(PostWizard.collecting, ~F.text.regexp(r"^/"))
async def on_content_any(message: Message, state: FSMContext):
    # Альбом: собираем чанки по media_group_id
    if message.media_group_id:
        data = await state.get_data()
        bucket = (data or {}).get("album_bucket")
        if not bucket or bucket.get("id") != message.media_group_id:
            bucket = {"id": message.media_group_id, "items": []}
        _append_album_piece(bucket, message)
        await state.update_data(album_bucket=bucket)

        # Дебаунс-финализация
        asyncio.create_task(_finalize_album_preview(message, state, message.media_group_id))
        return

    # Одиночное сообщение → соберём media_items через ContentBuilder
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


# Если в состоянии PREVIEW пользователь шлёт новое сообщение — считаем это «исправлением»
@router.message(PostWizard.preview, ~F.text.regexp(r"^/"))
async def on_content_replace(message: Message, state: FSMContext):
    await state.set_state(PostWizard.collecting)
    await on_content_any(message, state)


# Кнопка «Исправить»
@router.callback_query(PostWizard.preview, F.data == "post:preview_edit")
async def preview_edit(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await _safe_clear_kb(cb)  # снимем клавиатуру с медиа/альбома
    await state.update_data(content_media=None, album_bucket=None)
    await state.set_state(PostWizard.collecting)
    await cb.message.answer("Ок, пришли новый контент: текст/медиа или альбом.")


# Кнопка «Подтвердить»
@router.callback_query(PostWizard.preview, F.data == "post:preview_ok")
async def preview_ok(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await _safe_clear_kb(cb)  # снимем клавиатуру с медиа/альбома
    await state.set_state(PostWizard.title_wait)
    # ВНИМАНИЕ: это новое сообщение, не edit_text по медиа
    await cb.message.answer("Введи <b>название рассылки</b> (коротко).")


# Ввод заголовка
@router.message(PostWizard.title_wait, F.content_type == ContentType.TEXT, ~F.text.regexp(r"^/"))
async def title_input(message: Message, state: FSMContext):
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название пустое. Введи ещё раз.")
        return
    await state.update_data(title=title)
    await state.set_state(PostWizard.choose_kind)
    await message.answer("Выбери <b>тип рассылки</b>:", reply_markup=kb_kinds())


@router.callback_query(PostWizard.choose_kind, F.data.startswith("kind:"))
async def kind_pick(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    kind = cb.data.split(":", 1)[1]
    await state.update_data(kind=kind)
    await state.set_state(PostWizard.choose_audience)
    await cb.message.edit_text("Выбери аудиторию:", reply_markup=kb_audience())


@router.callback_query(F.data == "back:kind")
async def back_to_kind(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(PostWizard.choose_kind)
    await cb.message.edit_text("Выбери <b>тип рассылки</b>:", reply_markup=kb_kinds())


# Отмена
@router.callback_query(F.data == "cancel")
async def post_cancel(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    # здесь может быть медиа — поэтому не edit_text
    await _safe_clear_kb(cb)
    await cb.message.answer("Отменено.")


# Аудитория: все по типу
@router.callback_query(PostWizard.choose_audience, F.data == "aud:all")
async def aud_all(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    kind = (data or {}).get("kind")
    if not kind:
        await cb.answer("Сначала выбери тип рассылки", show_alert=True)
        return

    target = {"type": "kind", "kind": kind}
    await state.update_data(target=target)

    prev = await audience_preview_text(target)
    await state.set_state(PostWizard.choose_schedule)
    await cb.message.edit_text(f"{prev}\n\nТеперь выбери расписание.", reply_markup=kb_schedule())


# Аудитория: вручную ID
@router.callback_query(PostWizard.choose_audience, F.data == "aud:ids")
async def aud_ids(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(PostWizard.audience_ids_wait)
    await cb.message.edit_text(
        "Пришли список <b>user_id</b> через пробел или перенос строки.\nПример: <code>123 456 789</code>"
    )


@router.message(PostWizard.audience_ids_wait, F.content_type == ContentType.TEXT, ~F.text.regexp(r"^/"))
async def aud_ids_input(message: Message, state: FSMContext):
    ids = normalize_ids(message.text or "")
    if not ids:
        await message.answer("Не вижу чисел. Пришли ещё раз.")
        return
    target = {"type": "ids", "user_ids": ids}
    await state.update_data(target=target)
    prev = await audience_preview_text(target)
    await state.set_state(PostWizard.choose_schedule)
    await message.answer(
        f"🎯 Аудитория: <b>{len(ids)} ID</b>\n{prev}\n\nТеперь выбери расписание:",
        reply_markup=kb_schedule(),
    )


# Аудитория: SQL
@router.callback_query(PostWizard.choose_audience, F.data == "aud:sql")
async def aud_sql(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(PostWizard.audience_sql_wait)
    await cb.message.edit_text(
        "Пришли <b>SELECT</b>, возвращающий столбец <code>user_id</code>.\n"
        "Пример: <code>SELECT id AS user_id FROM users WHERE ...</code>\n"
        "Белый список: <code>users, user_memberships, user_subscriptions, chats</code>"
    )


@router.message(PostWizard.audience_sql_wait, F.content_type == ContentType.TEXT, ~F.text.regexp(r"^/"))
async def aud_sql_input(message: Message, state: FSMContext):
    sql = (message.text or "").strip()
    if not sql.lower().startswith("select"):
        await message.answer("Только SELECT-запросы. Пришли корректный SQL.")
        return
    target = {"type": "sql", "sql": sql}
    await state.update_data(target=target)
    prev = await audience_preview_text(target)
    await state.set_state(PostWizard.choose_schedule)
    await message.answer(
        f"🎯 Аудитория: <b>SQL</b>\n<code>{_html_escape(sql)}</code>\n\n{prev}\n\nТеперь выбери расписание:",
        reply_markup=kb_schedule(),
    )


@router.callback_query(F.data == "back:aud")
async def back_audience(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(PostWizard.choose_audience)
    await cb.message.edit_text("Выбери аудиторию:", reply_markup=kb_audience())


# Расписание
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


# Финал: создаём запись и запускаем/планируем
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

    # 1) создаём черновик на бэке (контент — нормализованный список media items)
    br = await db_api_client.create_broadcast(
        kind=kind,
        title=title,
        content={"media": media_items},
        status="draft",
    )
    await db_api_client.put_broadcast_target(br["id"], target)

    # 2) режим отправки
    bot = evt.message.bot if isinstance(evt, CallbackQuery) else evt.bot
    if mode == "now":
        try:
            await db_api_client.update_broadcast(br["id"], status="queued")
        except Exception:
            pass
        await try_send_now(bot, br["id"])
        txt = f"✅ Создано и отправляется: <b>#{br['id']}</b>"
    else:
        at_msk = at.astimezone(MSK)
        msk_naive = at_msk.replace(tzinfo=None)
        iso_naive = msk_naive.strftime("%Y-%m-%d %H:%M:%S")
        await db_api_client.update_broadcast(br["id"], status="scheduled", scheduled_at=iso_naive)
        schedule_broadcast_send(bot, br["id"], at_msk)
        txt = f"💾 Запланировано и поставлено локально: <b>#{br['id']}</b> на {iso_naive} (МСК)"

    # 3) ответ и сброс состояния
    if isinstance(evt, CallbackQuery):
        await evt.message.answer(txt)
    else:
        await evt.answer(txt)
    await state.clear()
