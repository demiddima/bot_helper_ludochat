# handlers/admin/broadcasts_wizard.py
# «Одно окно» для рассылки: контент -> аудитория (ALL/IDs/SQL) -> расписание -> подтверждение

from __future__ import annotations

from typing import Any, Dict, List, Optional
from html import escape as _html_escape
from datetime import datetime

import logging
from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, ContentType, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from services.db_api_client import db_api_client  # <-- ВАЖНО: правильный импорт

router = Router(name="admin_broadcasts_wizard")
log = logging.getLogger(__name__)


class PostWizard(StatesGroup):
    collecting = State()
    choose_audience = State()
    audience_ids_wait = State()
    audience_sql_wait = State()
    choose_schedule = State()
    confirm = State()


def _kb_audience() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Все (ALL)", callback_data="aud_all")],
        [InlineKeyboardButton(text="🧾 IDs вручную", callback_data="aud_ids")],
        [InlineKeyboardButton(text="🧠 SQL-выборка", callback_data="aud_sql")],
        [InlineKeyboardButton(text="🚫 Отмена", callback_data="cancel")],
    ])


def _kb_schedule() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Отправить сейчас", callback_data="sch_now")],
        [InlineKeyboardButton(text="🗓 Ввести дату/время", callback_data="sch_manual")],
        [InlineKeyboardButton(text="🔙 Назад (аудитория)", callback_data="back_audience")],
        [InlineKeyboardButton(text="🚫 Отмена", callback_data="cancel")],
    ])


def _kb_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="post_confirm")],
        [InlineKeyboardButton(text="🔙 Назад (расписание)", callback_data="back_schedule")],
        [InlineKeyboardButton(text="🚫 Отмена", callback_data="cancel")],
    ])


def _normalize_ids(text: str) -> List[int]:
    ids: List[int] = []
    seen = set()
    for chunk in (text or "").replace(",", " ").split():
        if chunk.isdigit():
            v = int(chunk)
            if v not in seen:
                seen.add(v)
                ids.append(v)
    return ids


async def _audience_preview_text(target: Dict[str, Any]) -> str:
    try:
        prev = await db_api_client.audience_preview(target, limit=10000)
        sample_txt = ", ".join(map(str, prev.get("sample", [])[:10])) if prev.get("sample") else ""
        tail = f"\nПример ID: <code>{sample_txt}</code>" if sample_txt else ""
        return f"👤 Всего в аудитории: <b>{prev['total']}</b>{tail}"
    except Exception as e:
        return f"⚠️ Предпросмотр аудитории недоступен: <code>{type(e).__name__}</code>"


def _make_media_items(collected: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if collected.get("text_html"):
        items.append({"type": "html", "payload": {"html": collected["text_html"]}, "position": 0})
    for it in collected.get("single_media", []):
        payload = {"file_id": it["file_id"]}
        if it.get("caption_html"):
            payload["caption_html"] = it["caption_html"]
        items.append({"type": it["type"], "payload": payload, "position": len(items)})
    if collected.get("album"):
        items.append({"type": "album", "payload": {"items": collected["album"]}, "position": len(items)})
    return items


def _parse_dt(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


@router.message(Command("post"))
async def cmd_post(message: Message, state: FSMContext):
    await state.clear()
    await state.update_data(
        collected={"text_html": None, "single_media": [], "album": None},
        target=None,
        schedule={"mode": None, "at": None},
    )
    await state.set_state(PostWizard.collecting)
    await message.answer(
        "Собираем рассылку.\n"
        "— Пришли <b>текст</b> и/или <b>медиа</b> (можно альбом до 10).\n"
        "— Когда закончишь — отправь /done\n\n"
        "Файлы сохраняются по <code>file_id</code>, подписи — как HTML."
    )


@router.message(PostWizard.collecting, Command("done"))
async def collecting_done(message: Message, state: FSMContext):
    data = await state.get_data()
    c = data["collected"]
    if not (c.get("text_html") or c.get("single_media") or c.get("album")):
        return await message.answer("Пока пусто. Добавь текст или медиа, затем /done")
    await state.set_state(PostWizard.choose_audience)
    await message.answer("Выбери аудиторию:", reply_markup=_kb_audience())


@router.callback_query(F.data == "cancel")
async def post_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Отменено.")


# --- аудитория ---

@router.callback_query(PostWizard.choose_audience, F.data == "aud_all")
async def aud_all(cb: CallbackQuery, state: FSMContext):
    target = {"type": "sql", "sql": "SELECT id AS user_id FROM users"}
    await state.update_data(target=target)
    prev = await _audience_preview_text(target)
    await cb.message.edit_text(f"🎯 Аудитория: <b>Все</b>\n{prev}\n\nТеперь выбери расписание:", reply_markup=_kb_schedule())
    await state.set_state(PostWizard.choose_schedule)


@router.callback_query(PostWizard.choose_audience, F.data == "aud_ids")
async def aud_ids(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PostWizard.audience_ids_wait)
    await cb.message.edit_text("Пришли список <b>user_id</b> через пробел/перенос строки.\nПример: <code>123 456 789</code>")


@router.message(PostWizard.audience_ids_wait)
async def aud_ids_input(message: Message, state: FSMContext):
    ids = _normalize_ids(message.text or "")
    if not ids:
        return await message.answer("Не вижу чисел. Пришли ещё раз.")
    target = {"type": "ids", "user_ids": ids}
    await state.update_data(target=target)
    prev = await _audience_preview_text(target)
    await state.set_state(PostWizard.choose_schedule)
    await message.answer(f"🎯 Аудитория: <b>{len(ids)} ID</b>\n{prev}\n\nТеперь выбери расписание:", reply_markup=_kb_schedule())


@router.callback_query(PostWizard.choose_audience, F.data == "aud_sql")
async def aud_sql(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PostWizard.audience_sql_wait)
    await cb.message.edit_text(
        "Пришли <b>SELECT</b>, возвращающий столбец <code>user_id</code>.\n"
        "Пример: <code>SELECT id AS user_id FROM users WHERE ...</code>\n"
        "Белый список: <code>users, user_memberships, user_subscriptions, chats</code>"
    )


@router.message(PostWizard.audience_sql_wait)
async def aud_sql_input(message: Message, state: FSMContext):
    sql = (message.text or "").strip()
    if not sql.lower().startswith("select"):
        return await message.answer("Только SELECT-запросы. Пришли корректный SQL.")
    target = {"type": "sql", "sql": sql}
    await state.update_data(target=target)
    prev = await _audience_preview_text(target)
    await state.set_state(PostWizard.choose_schedule)
    await message.answer(f"🎯 Аудитория: <b>SQL</b>\n<code>{_html_escape(sql)}</code>\n\n{prev}\n\nТеперь выбери расписание:", reply_markup=_kb_schedule())


@router.callback_query(F.data == "back_audience")
async def back_audience(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PostWizard.choose_audience)
    await cb.message.edit_text("Выбери аудиторию:", reply_markup=_kb_audience())


# --- расписание ---

@router.callback_query(PostWizard.choose_schedule, F.data == "sch_now")
async def sch_now(cb: CallbackQuery, state: FSMContext):
    await state.update_data(schedule={"mode": "now", "at": None})
    await _show_confirm(cb, state)


@router.callback_query(PostWizard.choose_schedule, F.data == "sch_manual")
async def sch_manual(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "Введи дату и время в одном из форматов:\n"
        "• <code>YYYY-MM-DD HH:MM</code>\n"
        "• <code>DD.MM.YYYY HH:MM</code>\n\nЧасовой пояс — Europe/Berlin.",
    )


@router.message(PostWizard.choose_schedule)
async def sch_manual_input(message: Message, state: FSMContext):
    dt = _parse_dt(message.text or "")
    if not dt:
        return await message.answer("Не понял дату/время. Пример: <code>2025-08-23 20:30</code>")
    await state.update_data(schedule={"mode": "at", "at": dt})
    await _show_confirm(message, state)


@router.callback_query(F.data == "back_schedule")
async def back_schedule(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PostWizard.choose_schedule)
    await cb.message.edit_text("Выбери расписание:", reply_markup=_kb_schedule())


# --- подтверждение ---

async def _show_confirm(evt: Message | CallbackQuery, state: FSMContext):
    data = await state.get_data()
    target = data.get("target")
    schedule = data.get("schedule") or {}
    t_txt = "Все" if (target and target.get("type") == "sql" and target.get("sql") == "SELECT id AS user_id FROM users") else target.get("type", "—")
    when = "сейчас" if schedule.get("mode") == "now" else (schedule.get("at").strftime("%Y-%m-%d %H:%M") if schedule.get("at") else "—")
    prev = await _audience_preview_text(target) if target else "—"

    text = (
        "Проверь параметры рассылки:\n"
        f"• Аудитория: <b>{t_txt}</b>\n"
        f"• Когда: <b>{when}</b>\n"
        f"{prev}\n\n"
        "Подтвердить?"
    )

    if isinstance(evt, CallbackQuery):
        await evt.message.edit_text(text, reply_markup=_kb_confirm())
    else:
        await evt.answer(text, reply_markup=_kb_confirm())


@router.callback_query(F.data == "post_confirm")
async def post_confirm(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    collected = data["collected"]
    target = data["target"]
    schedule = data["schedule"]

    # 1) создаём черновик
    text_html = collected.get("text_html") or ""
    title = (_html_escape(text_html[:60]) or "Без названия")
    br = await db_api_client.create_broadcast(kind="news", title=title, content_html=text_html)

    # 2) медиа
    items = _make_media_items(collected)
    if items:
        await db_api_client.put_broadcast_media(br["id"], items)

    # 3) таргет
    await db_api_client.put_broadcast_target(br["id"], target)

    # 4) расписание / отправка
    if schedule["mode"] == "now":
        await db_api_client.send_broadcast_now(br["id"])
        await cb.message.edit_text(f"✅ Создано и отправляется: <b>#{br['id']}</b>")
    elif schedule["mode"] == "at":
        iso = schedule["at"].strftime("%Y-%m-%d %H:%M:%S")
        await db_api_client.update_broadcast(br["id"], status="scheduled", scheduled_at=iso)
        await cb.message.edit_text(f"💾 Запланировано: <b>#{br['id']}</b> на {iso}")
    else:
        await cb.message.edit_text(f"💾 Сохранено как черновик: <b>#{br['id']}</b>")

    await state.clear()


# --- сбор контента ---

@router.message(PostWizard.collecting, F.content_type == ContentType.TEXT)
async def on_text(message: Message, state: FSMContext):
    data = await state.get_data()
    data["collected"]["text_html"] = _html_escape(getattr(message, "html_text", None) or message.text or "")
    await state.update_data(collected=data["collected"])
    await message.answer("Текст сохранён. Добавь медиа (если нужно) или жми /done")


@router.message(PostWizard.collecting, F.content_type.in_({ContentType.PHOTO, ContentType.VIDEO, ContentType.DOCUMENT}))
async def on_single_media(message: Message, state: FSMContext):
    data = await state.get_data()
    caption_html = _html_escape(getattr(message, "html_caption", None) or "") if message.caption else None

    if message.photo:
        it = {"type": "photo", "file_id": message.photo[-1].file_id, "caption_html": caption_html}
    elif message.video:
        it = {"type": "video", "file_id": message.video.file_id, "caption_html": caption_html}
    else:
        it = {"type": "document", "file_id": message.document.file_id, "caption_html": caption_html}

    data["collected"]["single_media"].append(it)
    await state.update_data(collected=data["collected"])
    await message.answer("Медиа добавлено. Ещё что-то? Или /done")


@router.message(PostWizard.collecting, F.media_group_id)
async def on_album_piece(message: Message, state: FSMContext):
    data = await state.get_data()
    if data["collected"]["album"] is None:
        data["collected"]["album"] = []

    caption_html = _html_escape(getattr(message, "html_caption", None) or "") if message.caption else None
    if message.photo:
        data["collected"]["album"].append({"type": "photo", "file_id": message.photo[-1].file_id, "caption_html": caption_html})
    elif message.video:
        data["collected"]["album"].append({"type": "video", "file_id": message.video.file_id, "caption_html": caption_html})
    elif message.document:
        data["collected"]["album"].append({"type": "document", "file_id": message.document.file_id, "caption_html": caption_html})

    await state.update_data(collected=data["collected"])
