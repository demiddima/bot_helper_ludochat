# handlers/admin/broadcasts_wizard.py
# Админ: «одно окно» для рассылки — /post. Текст + вложения (file_id), без хранения файлов.
# Шаги: Контент → Название → Тип → Аудитория → Расписание (МСК) → Подтверждение.

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from html import escape as _html_escape
from datetime import datetime
from zoneinfo import ZoneInfo

import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ContentType
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from services.local_scheduler import schedule_broadcast_send

# ВАЖНО: правильный импорт клиента
from services.db_api import db_api_client

log = logging.getLogger(__name__)
router = Router(name="admin_broadcasts_wizard")

MSK = ZoneInfo("Europe/Moscow")


class PostWizard(StatesGroup):
    collecting = State()
    title_wait = State()
    choose_kind = State()
    choose_audience = State()
    audience_ids_wait = State()
    audience_sql_wait = State()
    choose_schedule = State()
    confirm = State()


# ---------- helpers ----------

def _kb_kinds() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="📰 Новости", callback_data="kind:news")
    kb.button(text="📅 Встречи", callback_data="kind:meetings")
    kb.button(text="⚡️ Важные послания", callback_data="kind:important")
    kb.button(text="🚫 Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb

def _kb_audience() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Все (ALL)", callback_data="aud:all")
    kb.button(text="🧾 IDs вручную", callback_data="aud:ids")
    kb.button(text="🧠 SQL-выборка", callback_data="aud:sql")
    kb.button(text="🔙 Назад (тип)", callback_data="back:kind")
    kb.button(text="🚫 Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb

def _kb_schedule() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Отправить сейчас", callback_data="sch:now")
    kb.button(text="🗓 Ввести дату/время (МСК)", callback_data="sch:manual")
    kb.button(text="🔙 Назад (аудитория)", callback_data="back:aud")
    kb.button(text="🚫 Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb

def _kb_confirm() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data="post:confirm")
    kb.button(text="🔙 Назад (расписание)", callback_data="back:sch")
    kb.button(text="🚫 Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb

def _normalize_ids(text: str) -> List[int]:
    out: List[int] = []
    seen = set()
    for chunk in (text or "").replace(",", " ").split():
        if chunk.isdigit():
            v = int(chunk)
            if v not in seen:
                seen.add(v)
                out.append(v)
    return out

async def _audience_preview_text(target: Dict[str, Any]) -> str:
    try:
        prev = await db_api_client.audience_preview(target, limit=10000)
        total = prev.get("total", 0)
        sample = prev.get("sample") or []
        sample_txt = ", ".join(map(str, sample[:10])) if sample else ""
        tail = f"\nПример ID: <code>{sample_txt}</code>" if sample_txt else ""
        return f"👤 Всего в аудитории: <b>{total}</b>{tail}"
    except Exception as e:
        log.exception("audience_preview error: %s", e)
        return "⚠️ Предпросмотр аудитории недоступен."

def _parse_dt_msk(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M"):
        try:
            naive = datetime.strptime(s, fmt)
            return naive.replace(tzinfo=MSK)
        except ValueError:
            continue
    return None

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


# ---------- /post ----------

@router.message(Command("post"))
async def cmd_post(message: Message, state: FSMContext):
    await state.clear()
    await state.update_data(
        collected={"text_html": None, "single_media": [], "album": None},
        title=None,
        kind=None,
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
        await message.answer("Пока пусто. Добавь текст или медиа, затем /done")
        return
    await state.set_state(PostWizard.title_wait)
    await message.answer("Введи <b>название рассылки</b> (коротко).")

@router.message(PostWizard.title_wait, F.content_type == ContentType.TEXT)
async def title_input(message: Message, state: FSMContext):
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название пустое. Введи ещё раз.")
        return
    await state.update_data(title=title)
    await state.set_state(PostWizard.choose_kind)
    await message.answer("Выбери <b>тип рассылки</b>:", reply_markup=_kb_kinds().as_markup())

@router.callback_query(PostWizard.choose_kind, F.data.startswith("kind:"))
async def kind_pick(cb: CallbackQuery, state: FSMContext):
    kind = cb.data.split(":", 1)[1]  # news/meetings/important
    await state.update_data(kind=kind)
    await state.set_state(PostWizard.choose_audience)
    await cb.message.edit_text("Выбери аудиторию:", reply_markup=_kb_audience().as_markup())

@router.callback_query(F.data == "back:kind")
async def back_to_kind(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PostWizard.choose_kind)
    await cb.message.edit_text("Выбери <b>тип рассылки</b>:", reply_markup=_kb_kinds().as_markup())

@router.callback_query(F.data == "cancel")
async def post_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Отменено.")


# ---- аудитория ----

@router.callback_query(PostWizard.choose_audience, F.data == "aud:all")
async def aud_all(cb: CallbackQuery, state: FSMContext):
    target = {"type": "sql", "sql": "SELECT id AS user_id FROM users"}
    await state.update_data(target=target)
    prev = await _audience_preview_text(target)
    await state.set_state(PostWizard.choose_schedule)
    await cb.message.edit_text(f"🎯 Аудитория: <b>Все</b>\n{prev}\n\nТеперь выбери расписание:", reply_markup=_kb_schedule().as_markup())

@router.callback_query(PostWizard.choose_audience, F.data == "aud:ids")
async def aud_ids(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PostWizard.audience_ids_wait)
    await cb.message.edit_text("Пришли список <b>user_id</b> через пробел/перенос строки.\nПример: <code>123 456 789</code>")

@router.message(PostWizard.audience_ids_wait)
async def aud_ids_input(message: Message, state: FSMContext):
    ids = _normalize_ids(message.text or "")
    if not ids:
        await message.answer("Не вижу чисел. Пришли ещё раз.")
        return
    target = {"type": "ids", "user_ids": ids}
    await state.update_data(target=target)
    prev = await _audience_preview_text(target)
    await state.set_state(PostWizard.choose_schedule)
    await message.answer(f"🎯 Аудитория: <b>{len(ids)} ID</b>\n{prev}\n\nТеперь выбери расписание:", reply_markup=_kb_schedule().as_markup())

@router.callback_query(PostWizard.choose_audience, F.data == "aud:sql")
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
        await message.answer("Только SELECT-запросы. Пришли корректный SQL.")
        return
    target = {"type": "sql", "sql": sql}
    await state.update_data(target=target)
    prev = await _audience_preview_text(target)
    await state.set_state(PostWizard.choose_schedule)
    await message.answer(f"🎯 Аудитория: <b>SQL</b>\n<code>{_html_escape(sql)}</code>\n\n{prev}\n\nТеперь выбери расписание:", reply_markup=_kb_schedule().as_markup())

@router.callback_query(F.data == "back:aud")
async def back_audience(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PostWizard.choose_audience)
    await cb.message.edit_text("Выбери аудиторию:", reply_markup=_kb_audience().as_markup())


# ---- расписание ----

@router.callback_query(PostWizard.choose_schedule, F.data == "sch:now")
async def sch_now(cb: CallbackQuery, state: FSMContext):
    await state.update_data(schedule={"mode": "now", "at": None})
    await _show_confirm(cb, state)

@router.callback_query(PostWizard.choose_schedule, F.data == "sch:manual")
async def sch_manual(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "Введи дату и время <b>в МСК</b> в одном из форматов:\n"
        "• <code>YYYY-MM-DD HH:MM</code>\n"
        "• <code>DD.MM.YYYY HH:MM</code>\n\n"
        "Часовой пояс: Europe/Moscow."
    )

@router.message(PostWizard.choose_schedule)
async def sch_manual_input(message: Message, state: FSMContext):
    dt = _parse_dt_msk(message.text or "")
    if not dt:
        await message.answer("Не понял дату/время. Пример: <code>2025-08-23 20:30</code> (МСК)")
        return
    await state.update_data(schedule={"mode": "at", "at": dt})
    await _show_confirm(message, state)

@router.callback_query(F.data == "back:sch")
async def back_schedule(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PostWizard.choose_schedule)
    await cb.message.edit_text("Выбери расписание:", reply_markup=_kb_schedule().as_markup())


# ---- подтверждение и финал ----

async def _show_confirm(evt: Union[Message, CallbackQuery], state: FSMContext):
    data = await state.get_data()
    title = data.get("title") or "—"
    kind = data.get("kind") or "—"
    target = data.get("target")
    schedule = data.get("schedule") or {}

    if target and target.get("type") == "sql" and target.get("sql") == "SELECT id AS user_id FROM users":
        t_txt = "Все"
    else:
        t_txt = target.get("type", "—") if target else "—"

    when_txt = "сейчас (МСК)"
    if schedule.get("mode") == "at" and schedule.get("at"):
        at: datetime = schedule["at"]
        when_txt = f"{at.strftime('%Y-%m-%d %H:%M %z')} (МСК)"

    prev = await _audience_preview_text(target) if target else "—"

    text = (
        "Проверь параметры рассылки:\n"
        f"• Название: <b>{_html_escape(title)}</b>\n"
        f"• Тип: <b>{kind}</b>\n"
        f"• Аудитория: <b>{t_txt}</b>\n"
        f"• Когда: <b>{when_txt}</b>\n"
        f"{prev}\n\n"
        "Подтвердить?"
    )

    if isinstance(evt, CallbackQuery):
        await evt.message.edit_text(text, reply_markup=_kb_confirm().as_markup())
    else:
        await evt.answer(text, reply_markup=_kb_confirm().as_markup())

@router.callback_query(F.data == "post:confirm")
async def post_confirm(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    collected = data["collected"]
    title = data["title"]
    kind = data["kind"]
    target = data["target"]
    schedule = data["schedule"]

    # 1) черновик
    text_html = collected.get("text_html") or ""
    br = await db_api_client.create_broadcast(
        kind=kind,
        title=title,
        content_html=text_html,
    )

    # 2) медиа
    items = _make_media_items(collected)
    if items:
        await db_api_client.put_broadcast_media(br["id"], items)

    # 3) таргет
    await db_api_client.put_broadcast_target(br["id"], target)

    # 4) расписание / отправка
    if schedule["mode"] == "now":
        # Мгновенная отправка: без выставления времени, сразу send_now (бэк сам поставит МСК)
        await db_api_client.send_broadcast_now(br["id"])
        await cb.message.edit_text(f"✅ Создано и отправляется: <b>#{br['id']}</b>")
    elif schedule["mode"] == "at":
        # Сохраняем МСК как NAIVE 'YYYY-MM-DD HH:MM:SS' и ставим локальную задачу
        at: datetime = schedule["at"]  # aware (MSK)
        # делаем naive МСК для API
        msk_naive = at.astimezone(MSK).replace(tzinfo=None)
        iso_naive = msk_naive.strftime("%Y-%m-%d %H:%M:%S")
        await db_api_client.update_broadcast(br["id"], status="scheduled", scheduled_at=iso_naive)

        # Мгновенно планируем локально (без ожидания воркера)
        schedule_broadcast_send(br["id"], at)

        await cb.message.edit_text(f"💾 Запланировано и поставлено локально: <b>#{br['id']}</b> на {iso_naive} (МСК)")
    else:
        await cb.message.edit_text(f"💾 Сохранено как черновик: <b>#{br['id']}</b>")

    await state.clear()

# ---- сбор контента ----

@router.message(PostWizard.collecting, F.content_type == ContentType.TEXT)
async def on_text(msg: Message, state: FSMContext):
    data = await state.get_data()
    data["collected"]["text_html"] = _html_escape(msg.html_text or msg.text or "")
    await state.update_data(collected=data["collected"])
    await msg.answer("Текст сохранён. Добавь медиа (если нужно) или жми /done")

@router.message(PostWizard.collecting, F.content_type.in_({ContentType.PHOTO, ContentType.VIDEO, ContentType.DOCUMENT}))
async def on_single_media(msg: Message, state: FSMContext):
    data = await state.get_data()
    caption_html = _html_escape(msg.html_caption or "") if msg.caption else None
    if msg.photo:
        it = {"type": "photo", "file_id": msg.photo[-1].file_id, "caption_html": caption_html}
    elif msg.video:
        it = {"type": "video", "file_id": msg.video.file_id, "caption_html": caption_html}
    else:
        it = {"type": "document", "file_id": msg.document.file_id, "caption_html": caption_html}
    data["collected"]["single_media"].append(it)
    await state.update_data(collected=data["collected"])
    await msg.answer("Медиа добавлено. Ещё что-то? Или /done")

@router.message(PostWizard.collecting, F.media_group_id)
async def on_album_piece(msg: Message, state: FSMContext):
    data = await state.get_data()
    if data["collected"]["album"] is None:
        data["collected"]["album"] = []
    caption_html = _html_escape(msg.html_caption or "") if msg.caption else None
    if msg.photo:
        data["collected"]["album"].append({"type": "photo", "file_id": msg.photo[-1].file_id, "caption_html": caption_html})
    elif msg.video:
        data["collected"]["album"].append({"type": "video", "file_id": msg.video.file_id, "caption_html": caption_html})
    elif msg.document:
        data["collected"]["album"].append({"type": "document", "file_id": msg.document.file_id, "caption_html": caption_html})
    await state.update_data(collected=data["collected"])
