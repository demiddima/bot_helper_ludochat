# handlers/admin/broadcasts_wizard/steps_audience_kind.py
# commit: extract title/kind + audience steps
from __future__ import annotations

from html import escape as _html_escape
from typing import Dict, List
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ContentType
from aiogram.fsm.context import FSMContext

from . import PostWizard
from Mailing.keyboards.broadcasts_wizard import kb_kinds, kb_audience, kb_schedule
from Mailing.services.audience import normalize_ids, audience_preview_text

router = Router(name="admin_broadcasts_wizard.audience_kind")


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
