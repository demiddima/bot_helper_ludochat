# Mailing/routers/admin/broadcasts_manager.py
# Коммит: feat(manager/schedule): после изменения даты и при включении — сразу планировать локально (schedule_after_create)
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ContentType
from aiogram.exceptions import TelegramBadRequest

from common.db_api_client import db_api_client
from Mailing.keyboards.broadcasts_manager import kb_bm_list, kb_bm_item
from Mailing.services.schedule import (
    parse_and_preview,
    format_preview,
    is_oneoff_text,
    ScheduleError,
)
from Mailing.services.broadcasts import try_send_now
from Mailing.services.local_scheduler import schedule_after_create  # ← локальное планирование (немедленно)

log = logging.getLogger(__name__)
router = Router(name="admin_broadcasts_manager")


# ---------- Вспомогательный state для редактирования расписания ----------
@dataclass
class BMEditState:
    broadcast_id: int
    card_chat_id: Optional[int] = None
    card_message_id: Optional[int] = None


# ---------- Текстовые шаблоны ----------
def _item_header(b: Dict[str, Any]) -> str:
    bid = b.get("id")
    ttl = (b.get("title") or "").strip() or "Без названия"
    sch = (b.get("schedule") or "").strip() or "—"
    en = "🟢 Включена" if b.get("enabled") else "🔴 Выключена"
    return (
        f"<b>Рассылка #{bid}</b>\n"
        f"Название: <i>{ttl}</i>\n"
        f"Schedule: <code>{sch}</code>\n"
        f"Статус: {en}"
    )


async def _item_preview_text(b: Dict[str, Any]) -> str:
    sch = (b.get("schedule") or "").strip()
    if not sch:
        return _item_header(b) + "\n\n(расписание не задано)"
    try:
        kind, dates = parse_and_preview(sch, count=5)
        return _item_header(b) + "\n\n" + format_preview(kind, dates)
    except ScheduleError as e:
        return _item_header(b) + f"\n\n❌ Ошибка расписания: {e}"


# ---------- Список ближайших (7 дней) ----------
@router.message(Command("broadcasts"))
async def bm_list(message: Message, state: FSMContext):
    await _show_page(message, offset=0, limit=50)


@router.callback_query(F.data.startswith("bm:page:"))
async def bm_page(cb: CallbackQuery, state: FSMContext):
    offset = int(cb.data.split(":")[2])
    await cb.answer()
    await _show_page(cb.message, offset=offset, limit=50)


async def _show_page(target_message: Message, *, offset: int, limit: int):
    """
    Показываем только те рассылки, у которых ближайший запуск попадает
    в окно [сейчас .. +7 дней] по МСК. Пагинация — после фильтра.
    """
    now_msk = datetime.now(ZoneInfo("Europe/Moscow"))
    horizon = now_msk + timedelta(days=7)

    try:
        # Берём запасом и фильтруем локально — API не знает про «7 дней».
        all_items: List[Dict[str, Any]] = await db_api_client.list_broadcasts(
            status="scheduled",   # только запланированные
            enabled=None,         # и включённые, и выключенные
            limit=500,            # широкий лимит, чтобы локально отфильтровать на 7 дней
            offset=0,
        )
    except Exception as e:
        log.error("bm: list_broadcasts error: %s", e)
        await target_message.answer("Не удалось получить список рассылок.")
        return

    # Фильтрация по ближайшей дате запуска
    filtered: List[Dict[str, Any]] = []
    for b in all_items:
        schedule_text = (b.get("schedule") or "").strip()
        if not schedule_text:
            continue
        try:
            # Берём ближайший запуск (count=1)
            _kind, dates = parse_and_preview(schedule_text, count=1)
            next_dt = dates[0]
            if now_msk <= next_dt <= horizon:
                b = dict(b)
                b["_next_dt"] = next_dt
                filtered.append(b)
        except ScheduleError:
            continue

    # Сортируем по реальному ближайшему запуску
    filtered.sort(key=lambda it: it.get("_next_dt"))

    page_items = filtered[offset: offset + limit]
    has_more = (offset + limit) < len(filtered)

    if not page_items and offset > 0:
        await target_message.answer("Больше нет записей.")
        return

    if not page_items:
        await target_message.answer("За ближайшие 7 дней нет запланированных рассылок.")
        return

    await target_message.answer(
        "<b>Ближайшие рассылки (7 дней)</b>\nВыбери нужную:",
        reply_markup=kb_bm_list(page_items, offset=offset, limit=limit, has_more=has_more),
        disable_web_page_preview=True,
    )


# ---------- Карточка рассылки ----------
@router.callback_query(F.data.startswith("bm:open:"))
async def bm_open(cb: CallbackQuery, state: FSMContext):
    bid = int(cb.data.split(":")[2])
    await cb.answer()
    try:
        b = await db_api_client.get_broadcast(bid)
    except Exception as e:
        log.error("bm: get_broadcast(%s) error: %s", bid, e)
        await cb.message.answer("Не удалось получить рассылку.")
        return

    await _safe_edit_card(cb.message, bid, b)


# ---------- Toggle enabled ----------
@router.callback_query(F.data.startswith("bm:toggle:"))
async def bm_toggle(cb: CallbackQuery, state: FSMContext):
    bid = int(cb.data.split(":")[2])
    await cb.answer()
    try:
        b = await db_api_client.get_broadcast(bid)
        new_enabled = not bool(b.get("enabled"))
        await db_api_client.update_broadcast(bid, enabled=new_enabled)
        b = await db_api_client.get_broadcast(bid)
        # Немедленное планирование при включении
        if b.get("enabled") and (b.get("status") == "scheduled") and (b.get("schedule") or "").strip():
            try:
                await schedule_after_create(cb.message.bot, bid)
            except Exception as e:
                log.warning("bm: toggle schedule_after_create warn id=%s: %s", bid, e)
    except Exception as e:
        log.error("bm: toggle enabled error id=%s: %s", bid, e)
        await cb.message.answer("Не удалось изменить статус включения.")
        return

    await _safe_edit_card(cb.message, bid, b)


# ---------- Изменить расписание (ввод строкой) ----------
@router.callback_query(F.data.startswith("bm:edit:"))
async def bm_edit(cb: CallbackQuery, state: FSMContext):
    bid = int(cb.data.split(":")[2])
    await cb.answer()
    # сохраняем, КАКУЮ карточку нужно будет обновить после ввода даты
    await state.update_data(
        bm_edit=BMEditState(
            broadcast_id=bid,
            card_chat_id=cb.message.chat.id,
            card_message_id=cb.message.message_id,
        ).__dict__
    )
    await cb.message.edit_text(
        "Пришли новое расписание.\n"
        "Варианты:\n"
        "• разовая дата — <code>ДД.ММ.ГГГГ HH:MM</code> (МСК)\n"
        "• cron — 5 полей, напр. <code>0 15 * * 1</code>",
        reply_markup=None,
        disable_web_page_preview=True,
    )


@router.message(F.content_type == ContentType.TEXT, ~F.text.regexp(r"^/"))
async def bm_edit_input(message: Message, state: FSMContext):
    data = await state.get_data()
    st_raw = data.get("bm_edit")
    if not st_raw:
        return  # не в режиме редактирования

    st = BMEditState(**st_raw)
    bid = int(st.broadcast_id)
    schedule_text = (message.text or "").strip()

    # локальная валидация и превью (как в визарде)
    try:
        kind, dates = parse_and_preview(schedule_text, count=5)
        _ = format_preview(kind, dates)
    except ScheduleError as e:
        await message.answer(f"❌ {e}\n\nПопробуй ещё раз.")
        return

    try:
        await db_api_client.update_broadcast(bid, schedule=schedule_text)
        b = await db_api_client.get_broadcast(bid)
        # Немедленно планируем обновлённую рассылку, если она включена
        if b.get("enabled") and (b.get("status") == "scheduled") and (b.get("schedule") or "").strip():
            try:
                await schedule_after_create(message.bot, bid)
            except Exception as e:
                log.warning("bm: edit schedule_after_create warn id=%s: %s", bid, e)
    except Exception as e:
        log.error("bm: update schedule error id=%s: %s", bid, e)
        await message.answer("Не удалось сохранить новое расписание.")
        return

    await message.answer(f"✅ Сохранено.\n\n{await _item_preview_text(b)}")

    # Обновляем ИМЕННО ту карточку, которую просили изменить (по id)
    if st.card_chat_id and st.card_message_id:
        await _safe_edit_card_by_id(
            bot=message.bot,
            chat_id=st.card_chat_id,
            message_id=st.card_message_id,
            bid=bid,
            b=b,
        )
    else:
        # на крайний случай — пришлём новую карточку
        await message.answer(
            await _item_preview_text(b),
            reply_markup=kb_bm_item(bid, enabled=bool(b.get("enabled"))),
            disable_web_page_preview=True,
        )

    # очищаем состояние редактирования
    await state.update_data(bm_edit=None)


# ---------- Отправить сейчас ----------
async def _materialize_cron_child_and_send(bot, tpl: Dict[str, Any]) -> None:
    tpl_id = int(tpl["id"])
    title = tpl.get("title") or ""
    kind = tpl.get("kind") or "news"
    content = tpl.get("content") or {"text": "", "files": ""}

    child = await db_api_client.create_broadcast(
        kind=kind,
        title=title,
        content=content,
        status="draft",     # отправим немедленно
        schedule=None,      # у экземпляра нет расписания
        enabled=False,      # и не планируется
    )
    child_id = int(child["id"])

    try:
        tgt = await db_api_client.get_broadcast_target(tpl_id)
    except Exception as e:
        log.warning("bm: send_now cron — нет/не удалось получить таргет шаблона id=%s: %s", tpl_id, e)
        tgt = None

    if tgt:
        try:
            await db_api_client.put_broadcast_target(child_id, tgt)
        except Exception as e:
            log.warning("bm: send_now cron — не удалось сохранить таргет для child id=%s: %s", child_id, e)

    await try_send_now(bot=bot, broadcast_id=child_id)


@router.callback_query(F.data.startswith("bm:send:"))
async def bm_send_now(cb: CallbackQuery, state: FSMContext):
    bid = int(cb.data.split(":")[2])
    await cb.answer()

    sent_ok = False
    try:
        b = await db_api_client.get_broadcast(bid)
    except Exception as e:
        log.error("bm: send_now get_broadcast id=%s error=%s", bid, e)
        await cb.message.answer("Не удалось загрузить рассылку.")
        return

    schedule_text = (b.get("schedule") or "").strip()
    if not schedule_text:
        await cb.message.answer("У рассылки нет расписания. Создайте разовую или cron.")
        return

    # 1) Отправляем
    try:
        if is_oneoff_text(schedule_text):
            # try_send_now сам отметит статус; мы только выключим запись
            await try_send_now(cb.message.bot, bid)
            sent_ok = True
            try:
                await db_api_client.update_broadcast(bid, enabled=False)
            except Exception as e:
                log.warning("bm: send_now oneoff — не удалось выключить запись id=%s: %s", bid, e)
        else:
            await _materialize_cron_child_and_send(cb.message.bot, b)
            sent_ok = True
    except Exception as e:
        log.error("bm: send_now отправка упала id=%s: %s", bid, e)

    # 2) Сообщаем пользователю по факту отправки
    if sent_ok:
        if is_oneoff_text(schedule_text):
            await cb.message.answer(f"✅ Отправлено как one-off и запись выключена: #{bid}")
        else:
            await cb.message.answer(f"✅ Cron-шаблон #{bid}: создан экземпляр и выполнен немедленный запуск.")
    else:
        await cb.message.answer("Не удалось отправить сейчас.")
        return

    # 3) Пытаемся обновить карточку (не критично)
    try:
        b2 = await db_api_client.get_broadcast(bid)
    except Exception as e:
        log.warning("bm: send_now — не удалось перечитать запись id=%s: %s", bid, e)
        return

    await _safe_edit_card(cb.message, bid, b2)


# ---------- Безопасное обновление карточки по объекту Message ----------
async def _safe_edit_card(msg: Message, bid: int, b: Dict[str, Any]) -> None:
    """
    Обновляем карточку «мягко» через Message API.
    Если нельзя редактировать — шлём новую карточку вместо WARN.
    """
    await _safe_edit_card_by_id(
        bot=msg.bot,
        chat_id=msg.chat.id,
        message_id=msg.message_id,
        bid=bid,
        b=b,
    )


# ---------- Безопасное обновление карточки по chat_id/message_id ----------
async def _safe_edit_card_by_id(bot, chat_id: int, message_id: int, bid: int, b: Dict[str, Any]) -> None:
    new_text = await _item_preview_text(b)
    new_markup = kb_bm_item(bid, enabled=bool(b.get("enabled")))

    try:
        # Пытаемся заменить текст + клавиатуру
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=new_text,
                reply_markup=new_markup,
                disable_web_page_preview=True,
            )
            return
        except TelegramBadRequest as e:
            low = str(e).lower()
            if "message is not modified" in low:
                # Попробуем только markup
                try:
                    await bot.edit_message_reply_markup(
                        chat_id=chat_id,
                        message_id=message_id,
                        reply_markup=new_markup,
                    )
                    return
                except TelegramBadRequest as e2:
                    if "message is not modified" in str(e2).lower():
                        return
                    raise
            # Пробросим дальше — сработает фолбэк
            raise

    except TelegramBadRequest as e:
        low = str(e).lower()
        if "message can't be edited" in low or "message to edit not found" in low:
            # Фолбэк — отправим новую карточку
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=new_text,
                    reply_markup=new_markup,
                    disable_web_page_preview=True,
                )
                return
            except Exception as ee:
                log.warning("bm: fallback send failed id=%s: %s", bid, ee)
                return
        if "message is not modified" in low:
            return
        log.warning("bm: edit_text warn id=%s: %s", bid, e)
    except Exception as e:
        log.warning("bm: edit_text unexpected id=%s: %s", bid, e)
