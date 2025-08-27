# Mailing/routers/admin/broadcasts_wizard/steps_schedule_finalize.py
# Коммит: feat(wizard/text): уточнённые подсказки по CRON/разовой дате, дружелюбные ошибки, ясные итоги; без изменения логики
from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional, Union

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ContentType
from aiogram.fsm.context import FSMContext

from . import PostWizard
from Mailing.keyboards.broadcasts_wizard import kb_schedule, kb_schedule_confirm
from Mailing.services.schedule import parse_and_preview, format_preview, ScheduleError
from common.db_api_client import db_api_client
from Mailing.services.broadcasts.service import try_send_now  # «Отправить сейчас» остаётся
from Mailing.services.local_scheduler import schedule_after_create  # ⬅️ добавлено

log = logging.getLogger(__name__)
router = Router(name="admin_broadcasts_wizard.schedule_finalize")


# -------- utils: media_items → backend content {"text": "...", "files": "id1,id2"} --------

def _to_csv_content(media_items: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Преобразуем unified media_items в ожидаемый backend-формат:
      {"text": "<html...>", "files": "id1,id2,..."}
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
            if not text:
                cap = (p.get("caption") or "").strip()
                if cap:
                    text = cap

        elif t == "album":
            items = (p.get("items") or [])[:10]  # TG limit 10
            for it in items:
                it_fid = ((it.get("payload") or {}).get("file_id") or "").strip()
                if it_fid:
                    ids.append(it_fid)

    return {"text": text, "files": ",".join(ids)}


# -------- FSM helpers --------

async def _get_draft(state: FSMContext) -> dict:
    data = await state.get_data()
    return dict(data.get("broadcast_draft") or {})


async def _save_draft(state: FSMContext, draft: dict) -> None:
    data = await state.get_data()
    data["broadcast_draft"] = draft
    await state.update_data(**data)


def _pull(keys: List[str], *sources: Dict[str, Any], default: Any = None) -> Any:
    """
    Достаём первое непустое значение по списку ключей из набора словарей (data, draft, ...).
    """
    for src in sources:
        if not isinstance(src, dict):
            continue
        for k in keys:
            if k in src:
                v = src.get(k)
                if v or v == 0 or v is False:
                    return v
    return default


def _as_media_items(val: Any) -> Optional[List[Dict[str, Any]]]:
    """
    Принять media_items в одном из форматов:
      - уже список unified-элементов
      - {"media_items":[...]}
      - {"text":..., "files":[{type,file_id}, ...]}  (старый вид)
    """
    if isinstance(val, list):
        return val

    if isinstance(val, dict):
        if isinstance(val.get("media_items"), list):
            return val["media_items"]
        # Старый формат
        text = (val.get("text") or "").strip()
        files = val.get("files") or []
        files = files if isinstance(files, list) else []
        out: List[Dict[str, Any]] = []
        if len(files) > 1:
            album = []
            for f in files[:10]:
                ftype = (f.get("type") or "photo").lower()
                fid = f.get("file_id")
                if not fid:
                    continue
                album.append({"type": ftype, "payload": {"file_id": fid}})
            if album:
                out.append({"type": "album", "payload": {"items": album}})
                if text:
                    out.append({"type": "text", "payload": {"text": text}})
                return out
        if len(files) == 1:
            f = files[0]
            ftype = (f.get("type") or "photo").lower()
            fid = f.get("file_id")
            if fid:
                payload: Dict[str, Any] = {"kind": ftype, "file_id": fid}
                if text:
                    payload["caption"] = text
                if isinstance(f.get("caption_entities"), list):
                    payload["caption_entities"] = f["caption_entities"]
                out.append({"type": "media", "payload": payload})
                return out
        if text:
            out.append({"type": "text", "payload": {"text": text}})
            return out
        return []
    return None


async def _create_broadcast_compat(*, kind: str, title: str, content_csv: Dict[str, str],
                                   status: str, schedule: Optional[str] = None,
                                   enabled: Optional[bool] = None) -> Dict[str, Any]:
    """
    Совместимый вызов: сперва пытаемся kwargs-вариант, при TypeError/AttributeError — payload-вариант.
    """
    try:
        return await db_api_client.create_broadcast(
            kind=kind, title=title, content=content_csv, status=status,
            schedule=schedule, enabled=enabled
        )
    except (TypeError, AttributeError):
        payload = {
            "kind": kind,
            "title": title,
            "content": content_csv,
            "status": status,
        }
        if schedule is not None:
            payload["schedule"] = schedule
        if enabled is not None:
            payload["enabled"] = enabled
        return await db_api_client.create_broadcast(payload=payload)


async def _put_target_compat(bid: int, target: Dict[str, Any]) -> None:
    """
    Совместимая запись таргета: put_broadcast_target → set_broadcast_target → update_broadcast_target.
    """
    try:
        await db_api_client.put_broadcast_target(bid, target)
        return
    except AttributeError:
        pass
    try:
        await db_api_client.set_broadcast_target(bid, target)
        return
    except AttributeError:
        pass
    try:
        await db_api_client.update_broadcast_target(bid, target=target)
    except AttributeError:
        # если ни один метод не найден — логируем, но не валим визард
        log.warning("Не найден метод записи таргета для broadcast_id=%s", bid)


# ================= Режимы расписания =================

@router.callback_query(PostWizard.choose_schedule, F.data == "sch:now")
async def sch_now(cb: CallbackQuery, state: FSMContext):
    """
    «Отправить сейчас»: создаём broadcast (status=draft), пишем target и пинаем try_send_now().
    Берём данные как из корня FSM, так и из draft — что есть.
    """
    await cb.answer()
    data = await state.get_data()
    draft = dict(data.get("broadcast_draft") or {})

    media_raw = _pull(["content_media", "media_items", "content_media_items", "content"], data, draft)
    media_items = _as_media_items(media_raw) or []
    title = _pull(["title", "post_title"], data, draft, default="Без названия")
    kind = _pull(["kind", "post_kind", "type"], data, draft)
    target = _pull(["target", "audience", "audience_target"], data, draft)

    if not media_items or not title or not kind or not target:
        await cb.message.answer("Не хватает данных для рассылки. Начни заново: /post")
        await state.clear()
        return

    content_csv = _to_csv_content(media_items)
    try:
        br = await _create_broadcast_compat(kind=kind, title=title, content_csv=content_csv, status="draft")
        await _put_target_compat(br["id"], target)
    except Exception as e:
        log.error("Не удалось создать рассылку: %s", e)
        await cb.message.answer("❌ Не удалось создать рассылку. Проверь соединение с бэком.")
        return

    await try_send_now(cb.message.bot, br["id"])
    await cb.message.answer(
        f"✅ Создано и отправляется: <b>#{br['id']}</b>\n"
        f"Если нужно, вернись и поправь расписание в менеджере рассылок."
    )
    await state.clear()


@router.callback_query(PostWizard.choose_schedule, F.data == "sch:cron")
async def sch_mode_cron(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    draft = await _get_draft(state)
    draft["__sch_mode"] = "cron"
    await _save_draft(state, draft)
    await cb.message.edit_text(
        "<b>CRON-расписание</b> — 5 полей. Пары примеров:\n"
        "• <code>0 15 * * 1</code> — по понедельникам в 15:00\n"
        "• <code>0 10 * * 1,3,5</code> — Пн/Ср/Пт в 10:00\n"
        "• <code>30 9 * * *</code> — каждый день в 09:30\n\n"
        "Пришли строку cron. Я проверю формат и покажу 5 ближайших запусков.",
        reply_markup=None,
        disable_web_page_preview=True,
    )


@router.callback_query(PostWizard.choose_schedule, F.data == "sch:oneoff")
async def sch_mode_oneoff(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    draft = await _get_draft(state)
    draft["__sch_mode"] = "oneoff"
    await _save_draft(state, draft)
    await cb.message.edit_text(
        "<b>Разовая отправка</b> — укажи дату и время в формате <b>ДД.ММ.ГГГГ HH:MM</b> (МСК).\n"
        "Можно без ведущих нулей: <code>7.9.2025 9:05</code>. Пример с нулями: <code>27.08.2025 15:00</code>.\n\n"
        "Пришли строку даты/времени — я проверю и покажу превью.",
        reply_markup=None,
        disable_web_page_preview=True,
    )


@router.message(PostWizard.choose_schedule, F.content_type == ContentType.TEXT, ~F.text.regexp(r"^/"))
async def sch_input(message: Message, state: FSMContext):
    """
    Принимаем строку cron или 'ДД.ММ.ГГГГ HH:MM', делаем превью и предлагаем сохранить.
    """
    draft = await _get_draft(state)
    if draft.get("__sch_mode") not in {"cron", "oneoff"}:
        return

    schedule_text = (message.text or "").strip()
    try:
        kind, dates = parse_and_preview(schedule_text, count=5)
        preview = format_preview(kind, dates)
    except ScheduleError as e:
        await message.answer(
            f"❌ {e}\n\n"
            f"Исправь строку и пришли снова. Подсказка: для cron нужно 5 полей, для разовой даты — формат ДД.ММ.ГГГГ HH:MM (МСК)."
        )
        return

    draft["schedule"] = schedule_text
    if "enabled" not in draft:
        draft["enabled"] = True
    draft.pop("__sch_mode", None)
    await _save_draft(state, draft)

    await message.answer(
        f"<b>Расписание сохранено</b>\n{preview}",
        reply_markup=kb_schedule_confirm(enabled=bool(draft.get("enabled", True))),
        disable_web_page_preview=True,
    )


@router.callback_query(PostWizard.choose_schedule, F.data == "sch:toggle")
async def sch_toggle(cb: CallbackQuery, state: FSMContext):
    draft = await _get_draft(state)
    draft["enabled"] = not bool(draft.get("enabled", True))
    await _save_draft(state, draft)

    schedule = (draft.get("schedule") or "").strip()
    txt = "<b>Шаг: Расписание</b>\n"
    if schedule:
        try:
            k, ds = parse_and_preview(schedule, count=5)
            txt += "\n" + format_preview(k, ds)
        except ScheduleError as e:
            txt += f"\nТекущее значение некорректно: <i>{e}</i>"
    else:
        txt += "\nРасписание ещё не задано."

    await cb.message.edit_text(
        txt,
        reply_markup=kb_schedule_confirm(enabled=bool(draft.get("enabled", True))),
        disable_web_page_preview=True,
    )
    await cb.answer("Статус изменён.")


@router.callback_query(PostWizard.choose_schedule, F.data == "sch:edit")
async def sch_edit(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "<b>Шаг: Расписание</b>\nВыбери режим ввода:",
        reply_markup=kb_schedule(),
        disable_web_page_preview=True
    )
    await cb.answer()


@router.callback_query(PostWizard.choose_schedule, F.data == "sch:save")
async def sch_save(cb: CallbackQuery, state: FSMContext):
    """
    Финализируем шаг: создаём broadcast со schedule и enabled, привязываем target.
    Затем сразу планируем ближайший запуск.
    """
    await cb.answer()
    data = await state.get_data()
    draft = dict(data.get("broadcast_draft") or {})

    media_raw = _pull(["content_media", "media_items", "content_media_items", "content"], draft, data)
    media_items = _as_media_items(media_raw) or []

    title = _pull(["title", "post_title"], draft, data, default="Без названия")
    kind = _pull(["kind", "post_kind", "type"], draft, data)
    target = _pull(["target", "audience", "audience_target"], draft, data)
    schedule = (_pull(["schedule", "schedule_text"], draft, data) or "").strip()
    enabled = bool(_pull(["enabled", "is_enabled"], draft, data, default=True))

    if not media_items or not title or not kind or not target or not schedule:
        await cb.message.answer("Не хватает данных для рассылки. Начни заново: /post")
        await state.clear()
        return

    # финальная валидация расписания
    try:
        parse_and_preview(schedule, count=1)
    except ScheduleError as e:
        await cb.message.answer(f"Некорректное расписание: {e}")
        return

    # сборка контента в формат бэкенда
    content_csv = _to_csv_content(media_items)

    try:
        br = await _create_broadcast_compat(
            kind=kind,
            title=title,
            content_csv=content_csv,
            status="scheduled",
            schedule=schedule,
            enabled=enabled,
        )
        await _put_target_compat(br["id"], target)
    except Exception as e:
        log.error("Не удалось создать запланированную рассылку: %s", e)
        await cb.message.answer("❌ Не удалось создать запланированную рассылку. Проверь соединение с бэком и корректность данных.")
        return

    # сразу ставим ближайшую задачу
    try:
        await schedule_after_create(cb.message.bot, br["id"])
    except Exception as e:
        log.warning("Не удалось поставить ближайший запуск для #%s: %s", br.get("id"), e)

    await cb.message.answer(
        f"💾 Создано: <b>#{br['id']}</b>\n"
        f"Статус: {'включена' if enabled else 'выключена'}\n"
        f"Расписание: <code>{schedule}</code>\n"
        f"Ранее я показал 5 ближайших запусков."
    )
    await state.clear()
