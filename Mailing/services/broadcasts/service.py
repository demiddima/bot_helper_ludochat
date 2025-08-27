from __future__ import annotations

import asyncio
import logging
import json
from typing import Any, Dict, List, Optional, Tuple

import config
from aiogram import Bot

from common.db_api_client import db_api_client
from common.utils.common import log_and_report
from common.utils.time_msk import now_msk_naive

from Mailing.services.audience import resolve_audience  # резолв аудитории (ids|kind|sql)
from .sender import send_actual

log = logging.getLogger(__name__)

REPORT_BATCH = 200


def _now_msk_iso() -> str:
    """Текущее время (МСК, naive) 'YYYY-MM-DD HH:MM:SS'."""
    return now_msk_naive().strftime("%Y-%m-%d %H:%M:%S")


def _now_msk_iso8601() -> str:
    """Текущее время (МСК, naive) 'YYYY-MM-DDTHH:MM:SS' — безопасный для pydantic формат."""
    return now_msk_naive().strftime("%Y-%m-%dT%H:%M:%S")


def _to_media_items(content: Any) -> List[Dict[str, Any]]:
    """
    Приводим контент к unified-формату для sender.{send_actual,send_preview}.

    Поддерживаем:
    1) Обёрнутый формат: {"media_items": [ ... ]}      ← текущий визард
    2) Чистый список unified-элементов: [ ... ]
    3) Старый dict-формат: {"text": "...", "files": [ {type,file_id}, ... ]}
    4) Старый CSV в dict: {"text":"...", "files":"id1,id2,..."}
    5) Контент строкой JSON (dict или list в виде строки)
       + если строка не JSON, пытаемся трактовать как CSV file_id.
    """
    # --- (5) Если пришла строка — пробуем распарсить как JSON ---
    if isinstance(content, str):
        s = content.strip()
        if s:
            try:
                content = json.loads(s)
            except Exception:
                # Не JSON: трактуем как CSV file_id
                ids = [p.strip() for p in s.split(",") if p.strip()]
                if len(ids) > 1:
                    album_items = [{"type": "photo", "payload": {"file_id": fid}} for fid in ids[:10]]
                    items = [{"type": "album", "payload": {"items": album_items}}]
                    return items
                if len(ids) == 1:
                    return [{"type": "media", "payload": {"kind": "photo", "file_id": ids[0]}}]
                return []
        else:
            return []

    # --- (1) Обёртка {"media_items":[...]} ---
    if isinstance(content, dict) and isinstance(content.get("media_items"), list):
        return content["media_items"]

    # --- (2) Уже список unified-элементов ---
    if isinstance(content, list):
        return content

    # --- (3,4) Старые форматы: словарь с text/files ---
    if not isinstance(content, dict):
        return []

    text = (content.get("text") or "").strip()
    files_any = content.get("files")

    items: List[Dict[str, Any]] = []

    # --- (4) CSV-строка в поле files ---
    if isinstance(files_any, str):
        ids = [s.strip() for s in files_any.split(",") if s.strip()]
        if len(ids) > 1:
            album_items = [{"type": "photo", "payload": {"file_id": fid}} for fid in ids[:10]]  # TG лимит 10
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

    # --- (3) Список словарей файлов ---
    files = files_any or []
    files = files if isinstance(files, list) else []

    # Альбом
    if len(files) > 1:
        album_items: List[Dict[str, Any]] = []
        for f in files[:10]:  # TG лимит 10
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

    # Одиночное медиа
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

    # Только текст
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
    Готовим список для API:
      {"items":[{"user_id": int, "status": "sent|failed|skipped|pending",
                 "attempt_inc": 1, "sent_at": "YYYY-MM-DDTHH:MM:SS",
                 "message_id"?: int, "error_code"?: str, "error_message"?: str}]}
    None-поля не отправляем.
    """
    out: List[Dict[str, Any]] = []
    ts = _now_msk_iso8601()
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
    """Батч-репорт результатов доставки в ожидаемом сервисом формате."""
    if not items:
        return
    payload_items = _build_report_items_strict(items)
    if not payload_items:
        return
    try:
        await db_api_client.deliveries_report(broadcast_id, items=payload_items)
        log.debug("report %s: ok, sent %s items", broadcast_id, len(payload_items))
    except AttributeError:
        log.debug("deliveries_report отсутствует в db_api_client — пропускаю")
    except Exception as e:
        log.warning("report %s: ошибка отправки репорта: %s", broadcast_id, e)


async def send_broadcast(bot: Bot, broadcast: dict, throttle_per_sec: Optional[int] = None) -> Tuple[int, int]:
    """
    Основная отправка: читает broadcast['content'] (любой из поддерживаемых форматов),
    берёт target, резолвит аудиторию и шлёт однотипно каждому.
    Возвращает (sent, failed).
    """
    bid = broadcast["id"]
    rate = throttle_per_sec or getattr(config, "BROADCAST_RATE_PER_SEC", 29)
    rate = max(1, int(rate))
    window = 1.0 / rate

    # 1. Контент
    raw_content = broadcast.get("content")
    media_items = _to_media_items(raw_content)
    if not media_items:
        log.error("Рассылка id=%s не отправлена: content пуст или не распознан", bid)
        return 0, 0

    # 2. Аудитория
    try:
        target = await db_api_client.get_broadcast_target(bid)
    except Exception as e:
        log.error("Не удалось получить аудиторию рассылки id=%s: %s", bid, e)
        return 0, 0

    audience = await resolve_audience(target)
    if not audience:
        log.warning("Рассылка id=%s не отправлена: аудитория пустая", bid)
        return 0, 0

    # 3. Материализуем pending
    await _try_materialize(bid, audience)

    log.info("Начинаю рассылку id=%s: аудитория=%s, скорость=%s msg/с", bid, len(audience), rate)

    # 4. Цикл отправки + батч-репорт
    sent = 0
    failed = 0
    report_buf: List[Dict[str, Any]] = []

    for uid in audience:
        ok, msg_id, err_code, err_msg = await send_actual(bot, uid, media_items, kb_for_text=None)
        if ok:
            sent += 1
            report_buf.append({
                "user_id": uid,
                "status": "sent",
                "message_id": msg_id,
                # далее _try_report соберёт ISO-8601 и attempt_inc сам
            })
            log.debug("Сообщение отправлено пользователю %s (broadcast=%s)", uid, bid)
        else:
            failed += 1
            report_buf.append({
                "user_id": uid,
                "status": "failed",
                "message_id": msg_id,
                "error_code": err_code,
                "error_message": (err_msg[:1000] if err_msg else None),
            })
            log.debug("Ошибка при отправке пользователю %s (broadcast=%s): %s", uid, bid, err_code or "Unknown")

        if len(report_buf) >= REPORT_BATCH:
            await _try_report(bid, report_buf)
            report_buf.clear()

        await asyncio.sleep(window)

    # добросим хвост
    if report_buf:
        await _try_report(bid, report_buf)

    # 5. Итог
    if sent == 0 and failed > 0:
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
    Немедленный запуск рассылки БЕЗ учёта статуса и времени:
      1) выставляем статус 'sending'
      2) вызываем send_broadcast(...)
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
