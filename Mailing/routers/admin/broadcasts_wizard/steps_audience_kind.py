# Mailing/routers/admin/broadcasts_wizard/steps_audience_kind.py
# Коммит: fix(wizard/audience): target(type='kind', kind=<selected>) вместо несуществующего 'all' — чинит 422 на превью
from __future__ import annotations

from html import escape as _html_escape
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ContentType
from aiogram.fsm.context import FSMContext

from . import PostWizard
from Mailing.keyboards.broadcasts_wizard import kb_kinds, kb_audience, kb_schedule
from Mailing.services.audience import normalize_ids, audience_preview_text

router = Router(name="admin_broadcasts_wizard.audience_kind")


# ---------- Название ----------
@router.message(PostWizard.title_wait, F.content_type == ContentType.TEXT, ~F.text.regexp(r"^/"))
async def title_input(message: Message, state: FSMContext):
    """
    Принимаем короткое имя рассылки (видно только админам в списках/поиске).
    """
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название пустое. Введи короткое имя рассылки.")
        return
    await state.update_data(title=title)
    await state.set_state(PostWizard.choose_kind)
    await message.answer(
        "<b>Шаг 3. Тип рассылки</b>\n"
        "Выбери, что это за пост — влияет только на подписки пользователей:",
        reply_markup=kb_kinds(),
    )


# ---------- Тип ----------
@router.callback_query(PostWizard.choose_kind, F.data.startswith("kind:"))
async def choose_kind(cb: CallbackQuery, state: FSMContext):
    """
    Фиксируем тип (news / meetings / important) и переходим к выбору аудитории.
    """
    await cb.answer()
    kind = cb.data.split(":", 1)[1]
    await state.update_data(kind=kind)
    await state.set_state(PostWizard.choose_audience)
    await cb.message.edit_text(
        "<b>Шаг 4. Аудитория</b>\n"
        "Кому отправляем? Выбери вариант ниже:",
        reply_markup=kb_audience(),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "back:kind")
async def back_kind(cb: CallbackQuery, state: FSMContext):
    """
    Возврат к выбору типа.
    """
    await cb.answer()
    await state.set_state(PostWizard.choose_kind)
    await cb.message.edit_text(
        "Вернёмся к выбору типа рассылки:",
        reply_markup=kb_kinds(),
    )


# ---------- Аудитория: KIND (все подписчики выбранного типа) ----------
@router.callback_query(PostWizard.choose_audience, F.data == "aud:all")
async def aud_all(cb: CallbackQuery, state: FSMContext):
    """
    Все подписчики выбранного типа.
    ВАЖНО: backend (см. /audiences/preview и put_target) поддерживает type ∈ {ids, sql, kind}.
    Поэтому здесь формируем target с type='kind' и конкретным kind.
    """
    await cb.answer()
    data = await state.get_data()
    kind = (data.get("kind") or "news").strip()

    # ← ключевая правка: используем type='kind'
    target = {"type": "kind", "kind": kind}
    await state.update_data(target=target)

    # Предпросмотр (чтобы словить возможные проблемы сразу)
    prev = await audience_preview_text(target)
    await state.set_state(PostWizard.choose_schedule)
    await cb.message.edit_text(
        f"🎯 Аудитория: <b>все подписчики типа «{kind}»</b>\n{prev}\n\nТеперь выбери режим отправки:",
        reply_markup=kb_schedule(),
        disable_web_page_preview=True,
    )


# ---------- Аудитория: IDs ----------
@router.callback_query(PostWizard.choose_audience, F.data == "aud:ids")
async def aud_ids(cb: CallbackQuery, state: FSMContext):
    """
    Ручной список Telegram user_id (числа) — через пробел/перенос строки.
    """
    await cb.answer()
    await state.set_state(PostWizard.audience_ids_wait)
    await cb.message.edit_text(
        "<b>Введи список числовых user_id</b> — через пробел или с новой строки.\n"
        "Пример: <code>123 456 789</code>",
        reply_markup=None,
        disable_web_page_preview=True,
    )


@router.message(PostWizard.audience_ids_wait, F.content_type == ContentType.TEXT, ~F.text.regexp(r"^/"))
async def aud_ids_input(message: Message, state: FSMContext):
    """
    Нормализуем и валидируем список ID → превью аудитории → выбор расписания.
    """
    ids = normalize_ids(message.text or "")
    if not ids:
        await message.answer("Не вижу чисел. Пришли ещё раз.")
        return
    target = {"type": "ids", "user_ids": ids}
    await state.update_data(target=target)
    prev = await audience_preview_text(target)
    await state.set_state(PostWizard.choose_schedule)
    await message.answer(
        f"🎯 Аудитория: <b>{len(ids)} ID</b>\n{prev}\n\nТеперь выбери режим отправки:",
        reply_markup=kb_schedule(),
        disable_web_page_preview=True,
    )


# ---------- Аудитория: SQL ----------
@router.callback_query(PostWizard.choose_audience, F.data == "aud:sql")
async def aud_sql(cb: CallbackQuery, state: FSMContext):
    """
    Пользовательский SELECT, возвращающий столбец user_id.
    """
    await cb.answer()
    await state.set_state(PostWizard.audience_sql_wait)
    await cb.message.edit_text(
        "<b>Введи SELECT</b>, который возвращает столбец <code>user_id</code>.\n"
        "Примеры:\n"
        "• <code>SELECT user_id FROM users WHERE city = 'Moscow'</code>\n"
        "• <code>SELECT id AS user_id FROM leads WHERE subscribed=1</code>",
        reply_markup=None,
        disable_web_page_preview=True,
    )


@router.message(PostWizard.audience_sql_wait, F.content_type == ContentType.TEXT, ~F.text.regexp(r"^/"))
async def aud_sql_input(message: Message, state: FSMContext):
    """
    Принимаем SQL (минимальная валидация: начинается с SELECT), строим превью, затем расписание.
    """
    sql = (message.text or "").strip()
    if not sql.lower().startswith("select"):
        await message.answer("Ожидаю запрос, начинающийся с SELECT.")
        return
    target = {"type": "sql", "query": sql}
    await state.update_data(target=target)
    prev = await audience_preview_text(target)
    await state.set_state(PostWizard.choose_schedule)
    await message.answer(
        f"🎯 Аудитория: <b>SQL</b>\n<code>{_html_escape(sql)}</code>\n\n{prev}\n\nТеперь выбери режим отправки:",
        reply_markup=kb_schedule(),
        disable_web_page_preview=True,
    )


# ---------- Назад к выбору аудитории ----------
@router.callback_query(F.data == "back:aud")
async def back_audience(cb: CallbackQuery, state: FSMContext):
    """
    Возврат к выбору аудитории.
    """
    await cb.answer()
    await state.set_state(PostWizard.choose_audience)
    await cb.message.edit_text("Выбери аудиторию:", reply_markup=kb_audience())
