# handlers/admin/broadcasts_wizard.py
# Админ-визард рассылки: собираем текст/медиа → тип → аудитория → расписание → подтверждение.
# Фиксы:
#  - текст сохраняется как HTML без экранирования (msg.html_text)
#  - “СЕЙЧАС” — сразу пинаем try_send_now(), не ждём воркер
#  - “НА ВРЕМЯ” — local scheduler вызывается с bot (новая сигнатура)
#  - текстовые хэндлеры не перехватывают команды (например, /done)

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union
from html import escape as _html_escape
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ContentType, MessageEntity
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from services.local_scheduler import schedule_broadcast_send
from services.broadcasts import try_send_now
from services.db_api import db_api_client
from keyboards.broadcasts_wizard import kb_kinds, kb_audience, kb_schedule, kb_confirm

# ⬇️ ЕДИНЫЙ аудит-сервис (вместо services.audience_service)
from services.audience import (
    normalize_ids,
    audience_preview_text,
    materialize_all_user_ids,
)

from services.content_builder import make_media_items
from utils.time_msk import parse_msk  # парсер aware(MSK)

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


# ---------- /post (старт) ----------

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
        "Файлы сохраняются по <code>file_id</code>, подписи — через entities (без parse_mode)."
    )


# ---------- /done — ПРИОРИТЕТНЫЙ хэндлер ----------

@router.message(PostWizard.collecting, Command("done"))
async def collecting_done(message: Message, state: FSMContext):
    data = await state.get_data()
    c = data.get("collected") or {}
    if not (c.get("text_html") or c.get("single_media") or c.get("album")):
        await message.answer("Пока пусто. Добавь текст или медиа, затем /done")
        return
    await state.set_state(PostWizard.title_wait)
    await message.answer("Введи <b>название рассылки</b> (коротко).")


# ---------- контент ----------

def _dump_entities(entities: Optional[List[MessageEntity]]) -> Optional[List[dict]]:
    if not entities:
        return None
    return [e.model_dump(mode="json") for e in entities]


# ВАЖНО: текстовый хэндлер не должен ловить команды (например, /done)
@router.message(
    PostWizard.collecting,
    F.content_type == ContentType.TEXT,
    ~F.text.regexp(r"^/")  # исключаем /команды
)
async def on_text(msg: Message, state: FSMContext):
    data = await state.get_data()
    # Админский ввод с разметкой — используем готовый HTML от Telegram
    data["collected"]["text_html"] = (msg.html_text or msg.text or "")
    await state.update_data(collected=data["collected"])
    await msg.answer("Текст сохранён. Добавь медиа (если нужно) или жми /done")


@router.message(
    PostWizard.collecting,
    F.content_type.in_({ContentType.PHOTO, ContentType.VIDEO, ContentType.DOCUMENT}),
    ~F.media_group_id  # одиночное медиа
)
async def on_single_media(msg: Message, state: FSMContext):
    data = await state.get_data()

    cap_text = msg.caption or None
    cap_entities = _dump_entities(msg.caption_entities or None)

    if msg.photo:
        it = {"type": "photo", "file_id": msg.photo[-1].file_id,
              "caption": cap_text, "caption_entities": cap_entities}
    elif msg.video:
        it = {"type": "video", "file_id": msg.video.file_id,
              "caption": cap_text, "caption_entities": cap_entities}
    else:
        it = {"type": "document", "file_id": msg.document.file_id,
              "caption": cap_text, "caption_entities": cap_entities}

    data["collected"]["single_media"].append(it)
    await state.update_data(collected=data["collected"])
    await msg.answer("Медиа добавлено. Ещё что-то? Или /done")


@router.message(PostWizard.collecting, F.media_group_id)
async def on_album_piece(msg: Message, state: FSMContext):
    data = await state.get_data()
    if data["collected"]["album"] is None:
        data["collected"]["album"] = []

    cap_text = msg.caption or None
    cap_entities = _dump_entities(msg.caption_entities or None)

    if msg.photo:
        data["collected"]["album"].append({"type": "photo", "file_id": msg.photo[-1].file_id,
                                           "caption": cap_text, "caption_entities": cap_entities})
    elif msg.video:
        data["collected"]["album"].append({"type": "video", "file_id": msg.video.file_id,
                                           "caption": cap_text, "caption_entities": cap_entities})
    elif msg.document:
        data["collected"]["album"].append({"type": "document", "file_id": msg.document.file_id,
                                           "caption": cap_text, "caption_entities": cap_entities})

    await state.update_data(collected=data["collected"])


# ---------- тип рассылки ----------

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
    kind = cb.data.split(":", 1)[1]  # news/meetings/important
    await state.update_data(kind=kind)
    await state.set_state(PostWizard.choose_audience)
    await cb.message.edit_text("Выбери аудиторию:", reply_markup=kb_audience())


@router.callback_query(F.data == "back:kind")
async def back_to_kind(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PostWizard.choose_kind)
    await cb.message.edit_text("Выбери <b>тип рассылки</b>:", reply_markup=kb_kinds())


@router.callback_query(F.data == "cancel")
async def post_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Отменено.")


# ---------- аудитория ----------

@router.callback_query(PostWizard.choose_audience, F.data == "aud:all")
async def aud_all(cb: CallbackQuery, state: FSMContext):
    try:
        ids = await materialize_all_user_ids()
    except Exception as e:
        await cb.answer("Ошибка получения пользователей", show_alert=True)
        log.error("Аудитория ALL: ошибка=%s", e, extra={"user_id": cb.from_user.id})
        return
    target = {"type": "ids", "user_ids": ids}
    await state.update_data(target=target)
    prev = await audience_preview_text(target)
    await state.set_state(PostWizard.choose_schedule)
    await cb.message.edit_text(f"{prev}\n\nТеперь выбери расписание.", reply_markup=kb_schedule())


@router.callback_query(PostWizard.choose_audience, F.data == "aud:ids")
async def aud_ids(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PostWizard.audience_ids_wait)
    await cb.message.edit_text("Пришли список <b>user_id</b> через пробел/перенос строки.\nПример: <code>123 456 789</code>")


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


@router.callback_query(PostWizard.choose_audience, F.data == "aud:sql")
async def aud_sql(cb: CallbackQuery, state: FSMContext):
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
    await state.set_state(PostWizard.choose_audience)
    await cb.message.edit_text("Выбери аудиторию:", reply_markup=kb_audience())


# ---------- расписание ----------

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


@router.message(PostWizard.choose_schedule, F.content_type == ContentType.TEXT, ~F.text.regexp(r"^/"))
async def sch_manual_input(message: Message, state: FSMContext):
    dt = parse_msk(message.text or "")
    if not dt:
        await message.answer("Не понял дату/время. Пример: <code>2025-08-23 20:30</code> (МСК)")
        return
    await state.update_data(schedule={"mode": "at", "at": dt})
    await _show_confirm(message, state)


@router.callback_query(F.data == "back:sch")
async def back_schedule(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PostWizard.choose_schedule)
    await cb.message.edit_text("Выбери расписание:", reply_markup=kb_schedule())


# ---------- подтверждение и финал ----------

async def _show_confirm(evt: Union[Message, CallbackQuery], state: FSMContext):
    data = await state.get_data()
    title = data.get("title") or "—"
    kind = data.get("kind") or "—"
    target = data.get("target")
    schedule = data.get("schedule") or {}

    t_txt = "IDs" if (target and target.get("type") == "ids") else (target.get("type", "—") if target else "—")
    when_txt = "сейчас (МСК)"
    if schedule.get("mode") == "at" and schedule.get("at"):
        at: datetime = schedule["at"]
        when_txt = f"{at.strftime('%Y-%m-%d %H:%M %z')} (МСК)"

    prev = await audience_preview_text(target) if target else "—"

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
        await evt.message.edit_text(text, reply_markup=kb_confirm())
    else:
        await evt.answer(text, reply_markup=kb_confirm())


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
    items = make_media_items(collected)
    if items:
        await db_api_client.put_broadcast_media(br["id"], items)

    # 3) таргет
    await db_api_client.put_broadcast_target(br["id"], target)

    # 4) расписание / отправка
    if schedule["mode"] == "now":
        await db_api_client.send_broadcast_now(br["id"])
        # МГНОВЕННЫЙ пуш (не ждём воркер)
        await try_send_now(cb.message.bot, br["id"])
        await cb.message.edit_text(f"✅ Создано и отправляется: <b>#{br['id']}</b>")

    elif schedule["mode"] == "at":
        at: datetime = schedule["at"]  # aware (МСК)
        msk_naive = at.astimezone(MSK).replace(tzinfo=None)
        iso_naive = msk_naive.strftime("%Y-%m-%d %H:%M:%S")
        await db_api_client.update_broadcast(br["id"], status="scheduled", scheduled_at=iso_naive)
        # Новая сигнатура: передаём bot
        schedule_broadcast_send(cb.message.bot, br["id"], at)
        await cb.message.edit_text(f"💾 Запланировано и поставлено локально: <b>#{br['id']}</b> на {iso_naive} (МСК)")

    else:
        await cb.message.edit_text(f"💾 Сохранено как черновик: <b>#{br['id']}</b>")

    await state.clear()
