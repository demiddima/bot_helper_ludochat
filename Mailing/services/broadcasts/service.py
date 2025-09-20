# Mailing/services/broadcasts/service.py

from __future__ import annotations

import asyncio
import logging
import json
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple, Set

import config
from aiogram import Bot

from common.db_api_client import db_api_client
from common.utils.common import log_and_report
from common.utils.time_msk import now_msk_naive

from Mailing.services.audience import resolve_audience  # резолв аудитории (ids|kind|sql)
from storage import remove_membership  # <- обёртка для membership
from .sender import send_actual

log = logging.getLogger(__name__)

# Меньший батч, чтобы чаще фиксировать прогресс
REPORT_BATCH = 50


def _now_msk_sql() -> str:
    """'YYYY-MM-DD HH:MM:SS' (МСК, naive) — безопасно для БД/сериализаторов."""
    return now_msk_naive().strftime("%Y-%m-%d %H:%M:%S")


def _to_media_items(content: Any) -> List[Dict[str, Any]]:
    """
    Приводим контент к unified-формату для sender.{send_actual,send_preview}.

    Поддерживаем:
    1) Обёрнутый формат: {"media_items": [ ... ]}
    2) Чистый список unified-элементов: [ ... ]
    3) Старый dict-формат: {"text": "...", "files": [ {type,file_id}, ... ]}
    4) Старый CSV в dict: {"text":"...", "files":"id1,id2,..."}
    5) Контент строкой JSON (dict или list в виде строки)
       + если строка не JSON, пытаемся трактовать как CSV file_id.
    """
    if isinstance(content, str):
        s = content.strip()
        if s:
            try:
                content = json.loads(s)
            except Exception:
                ids = [p.strip() for p in s.split(",") if p.strip()]
                if len(ids) > 1:
                    album_items = [{"type": "photo", "payload": {"file_id": fid}} for fid in ids[:10]]
                    return [{"type": "album", "payload": {"items": album_items}}]
                if len(ids) == 1:
                    return [{"type": "media", "payload": {"kind": "photo", "file_id": ids[0]}}]
                return []
        else:
            return []

    if isinstance(content, dict) and isinstance(content.get("media_items"), list):
        return content["media_items"]

    if isinstance(content, list):
        return content

    if not isinstance(content, dict):
        return []

    text = (content.get("text") or "").strip()
    files_any = content.get("files")
    items: List[Dict[str, Any]] = []

    if isinstance(files_any, str):
        ids = [s.strip() for s in files_any.split(",") if s.strip()]
        if len(ids) > 1:
            album_items = [{"type": "photo", "payload": {"file_id": fid}} for fid in ids[:10]]
            items.append({"type": "album", "payload": {"items": album_items}})
            if text:
                items.append({"type": "text", "payload": {"text": text}})
            return items
        if len(ids) == 1:
            payload: Dict[str, Any] = {"kind": "photo", "file_id": ids[0]}
            if text:
                payload["caption"] = text
            items.append({"type": "media", "payload": payload})
            return items
        files_any = []

    files = files_any or []
    files = files if isinstance(files, list) else []

    if len(files) > 1:
        album_items: List[Dict[str, Any]] = []
        for f in files[:10]:
            ftype = (f.get("type") or "photo").lower()
            fid = f.get("file_id")
            if not fid:
                continue
            album_items.append({"type": ftype, "payload": {"file_id": fid}})
        if album_items:
            items.append({"type": "album", "payload": {"items": album_items}})
            if text:
                items.append({"type": "text", "payload": {"text": text}})
        return items

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
            items.append({"type": "media", "payload": payload})
            return items

    if text:
        items.append({"type": "text", "payload": {"text": text}})
    return items


async def _try_materialize(broadcast_id: int, user_ids: List[int]) -> None:
    """Создаём pending-записи в broadcast_deliveries (мягкий noop, если метод не реализован)."""
    if not user_ids:
        return
    try:
        limit = min(max(1000, len(user_ids)), 200_000)
        res = await db_api_client.deliveries_materialize(
            broadcast_id, payload={"ids": user_ids, "limit": limit}
        )
        log.info(
            "materialize: id=%s total=%s created=%s existed=%s",
            broadcast_id, res.get("total"), res.get("created"), res.get("existed")
        )
    except AttributeError:
        log.debug("deliveries_materialize отсутствует в db_api_client — шаг пропускаю")
    except Exception as e:
        log.warning("materialize %s: ошибка %s", broadcast_id, e)


# ---- STRICT REPORT BUILDER ----

def _build_report_items_strict(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Формат для API:
      {"items":[{"user_id": int, "status": "sent|failed|skipped|pending",
                 "attempt_inc": 1, "sent_at": "YYYY-MM-DD HH:MM:SS",
                 "message_id"?: int, "error_code"?: str, "error_message"?: str}]}
    None-поля не отправляем.
    """
    out: List[Dict[str, Any]] = []
    ts = _now_msk_sql()
    for it in items or []:
        try:
            uid = int(it.get("user_id"))
        except Exception:
            continue
        status = it.get("status")
        if uid <= 0 or status not in ("sent", "failed", "skipped", "pending"):
            continue

        obj: Dict[str, Any] = {"user_id": uid, "status": status, "attempt_inc": 1, "sent_at": ts}

        mid = it.get("message_id")
        if isinstance(mid, int):
            obj["message_id"] = mid

        ec = it.get("error_code")
        if ec:
            obj["error_code"] = str(ec)[:64]

        em = it.get("error_message")
        if em:
            obj["error_message"] = str(em)[:500]

        out.append(obj)
    return out


async def _try_report(broadcast_id: int, items: List[Dict[str, Any]]) -> None:
    """Батч-репорт результатов доставки."""
    if not items:
        return
    payload_items = _build_report_items_strict(items)
    if not payload_items:
        return
    try:
        res = await db_api_client.deliveries_report(broadcast_id, items=payload_items)
        # чтобы было видно в обычных логах
        log.info("report %s: ok, sent %s items", broadcast_id, len(payload_items))
        if res:
            # не у всех бекендов есть тело; если есть — логируем компактно
            total = res.get("updated") or res.get("count") or None
            if total is not None:
                log.info("report %s: backend updated=%s", broadcast_id, total)
    except AttributeError:
        log.debug("deliveries_report отсутствует в db_api_client — пропускаю")
    except Exception as e:
        log.warning("report %s: ошибка отправки репорта: %s", broadcast_id, e)


# ---- AUTO-CLEANUP FOR BLOCKED USERS ----

def _is_blocked_error(err_code: Optional[str], err_msg: Optional[str]) -> bool:
    s1 = (err_code or "").lower()
    s2 = (err_msg or "").lower()
    if "forbidden" in s1 and "blocked" in s1:
        return True
    return "bot was blocked by the user" in s2 or ("forbidden" in s2 and "blocked" in s2)


async def _cleanup_after_block(user_id: int) -> None:
    """Удаляем membership только по BOT_ID и запись в user_subscriptions."""
    # 1) membership (только бот)
    try:
        await remove_membership(user_id, config.BOT_ID)
        m_ok = True
    except Exception as exc:
        m_ok = False
        log.error("user_id=%s – Ошибка remove_membership(bot): %s", user_id, exc, extra={"user_id": user_id})

    # 2) user_subscriptions
    try:
        await db_api_client.delete_user_subscriptions(user_id)
        s_ok = True
    except Exception as exc:
        s_ok = False
        log.error("user_id=%s – Ошибка delete_user_subscriptions: %s", user_id, exc, extra={"user_id": user_id})

    log.info(
        "user_id=%s – Автоочистка после Forbidden: %s, %s",
        user_id,
        "membership(bot)=OK" if m_ok else "membership(bot)=ERR",
        "subscriptions=OK" if s_ok else "subscriptions=ERR",
        extra={"user_id": user_id},
    )


async def _notify_admins_about_broadcast(
    bot: Bot,
    *,
    b: dict,
    total: int,
    sent: int,
    failed: int,
    started_ts: float,
    errors_counter: Counter,
) -> None:
    admins = getattr(config, "ID_ADMIN_USER", set()) or set()
    if not admins:
        return
    dur = max(0.0, time.time() - started_ts)
    title = (b.get("title") or "").strip() or "Без названия"
    bid = b.get("id")

    parts = [
        f"📨 <b>Рассылка #{bid}</b>",
        f"Название: <i>{title}</i>",
        f"Аудитория: <b>{total}</b>",
        f"Отправлено: <b>{sent}</b>",
        f"Ошибок: <b>{failed}</b>",
        f"Длительность: <code>{dur:.1f}с</code>",
    ]

    if errors_counter:
        top = ", ".join(f"{k or 'Unknown'}={v}" for k, v in errors_counter.most_common(5))
        parts.append(f"Ошибки (топ): {top}")

    text = "\n".join(parts)
    for uid in admins:
        try:
            await bot.send_message(uid, text, disable_web_page_preview=True)
        except Exception as e:
            log.warning("admin notify failed user_id=%s: %s", uid, e)


async def send_broadcast(bot: Bot, broadcast: dict, throttle_per_sec: Optional[int] = None) -> Tuple[int, int]:
    """
    Основная отправка: читает broadcast['content'], резолвит аудиторию и шлёт каждому.
    Возвращает (sent, failed).
    """
    bid = broadcast["id"]
    rate = throttle_per_sec or getattr(config, "BROADCAST_RATE_PER_SEC", 29)
    rate = max(1, int(rate))
    window = 1.0 / rate

    raw_content = broadcast.get("content")
    media_items = _to_media_items(raw_content)
    if not media_items:
        log.error("Рассылка id=%s не отправлена: content пуст или не распознан", bid)
        return 0, 0

    # 2) Аудитория
    try:
        target = await db_api_client.get_broadcast_target(bid)
    except Exception as e:
        log.error("Не удалось получить аудиторию рассылки id=%s: %s", bid, e)
        return 0, 0

    audience = await resolve_audience(target)
    if not audience:
        log.warning("Рассылка id=%s не отправлена: аудитория пустая", bid)
        return 0, 0

    # 3) Материализуем pending
    await _try_materialize(bid, audience)

    log.info("Начинаю рассылку id=%s: аудитория=%s, скорость=%s msg/с", bid, len(audience), rate)

    sent = 0
    failed = 0
    report_buf: List[Dict[str, Any]] = []

    cleaned_blocked: Set[int] = set()
    blocked_failed_count = 0
    errors_counter: Counter = Counter()
    started_ts = time.time()

    async def _flush():
        nonlocal report_buf
        if report_buf:
            await _try_report(bid, report_buf)
            report_buf.clear()

    # 4) Цикл отправки + периодический репорт
    try:
        for uid in audience:
            ok, msg_id, err_code, err_msg = await send_actual(bot, uid, media_items, kb_for_text=None)
            if ok:
                sent += 1
                report_buf.append({"user_id": uid, "status": "sent", "message_id": msg_id})
            else:
                failed += 1
                errors_counter.update([err_code or "Unknown"])
                report_buf.append({
                    "user_id": uid,
                    "status": "failed",
                    "message_id": msg_id,
                    "error_code": err_code,
                    "error_message": (err_msg[:1000] if err_msg else None),
                })

                # Автоочистка на Forbidden (bot blocked)
                if uid not in cleaned_blocked and _is_blocked_error(err_code, err_msg):
                    await _cleanup_after_block(uid)
                    cleaned_blocked.add(uid)
                    blocked_failed_count += 1

            if len(report_buf) >= REPORT_BATCH:
                await _flush()

            await asyncio.sleep(window)
    finally:
        # добросим хвост при любом исходе
        await _flush()
        # уведомление админам — по факту завершения цикла/ошибки
        try:
            await _notify_admins_about_broadcast(
                bot,
                b=broadcast,
                total=len(audience),
                sent=sent,
                failed=failed,
                started_ts=started_ts,
                errors_counter=errors_counter,
            )
        except Exception as e:
            log.warning("notify admins failed for broadcast %s: %s", bid, e)

    # 5) Итоговые логи
    if sent == 0 and failed > 0:
        if blocked_failed_count == failed:
            log.info(
                "Рассылка id=%s: аудитория недоступна (все адресаты заблокировали бота). "
                "Ошибок не создаём, автоочистка выполнена.", bid
            )
        else:
            log.error("Рассылка id=%s не доставлена никому (ошибок=%s)", bid, failed)
            try:
                await log_and_report(Exception("broadcast failed"), f"Рассылка {bid} не доставлена: ошибок={failed}")
            except Exception:
                pass
    elif failed > 0:
        log.warning("Рассылка id=%s доставлена частично: отправлено=%s, ошибок=%s", bid, sent, failed)
    else:
        log.info("Рассылка id=%s доставлена полностью: отправлено=%s", bid, sent)

    return sent, failed


async def mark_broadcast_sent(broadcast_id: int) -> dict:
    log.info("Помечаем рассылку id=%s как доставленную", broadcast_id)
    return await db_api_client.update_broadcast(broadcast_id, status="sent")


async def try_send_now(bot: Bot, broadcast_id: int) -> None:
    """
    Немедленный запуск:
      1) статус 'sending'
      2) send_broadcast(...)
      3) если что-то отправили — 'sent', иначе 'failed'
    """
    try:
        b = await db_api_client.get_broadcast(broadcast_id)
        log.info("Получена рассылка id=%s для немедленного запуска", broadcast_id)
    except Exception as e:
        log.error("Не удалось загрузить рассылку id=%s: %s", broadcast_id, e)
        return

    try:
        await db_api_client.update_broadcast(broadcast_id, status="sending")
    except Exception as e:
        log.warning("Не удалось выставить статус 'sending' для id=%s: %s", broadcast_id, e)

    try:
        sent, failed = await send_broadcast(bot, b)
        if sent > 0:
            await mark_broadcast_sent(broadcast_id)
        else:
            try:
                await db_api_client.update_broadcast(broadcast_id, status="failed")
            except Exception as e2:
                log.warning("Не удалось пометить 'failed' id=%s: %s", broadcast_id, e2)
    except Exception as e:
        log.error("Ошибка при немедленной отправке рассылки id=%s: %s", broadcast_id, e)
        try:
            await db_api_client.update_broadcast(broadcast_id, status="failed")
        except Exception as e2:
            log.warning("Не удалось пометить 'failed' id=%s после ошибки: %s", broadcast_id, e2)


__all__ = ["send_broadcast", "try_send_now", "mark_broadcast_sent"]
