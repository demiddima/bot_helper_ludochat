# services/broadcasts/service.py
# Оркестрация рассылок: сбор контента, аудитория, троттлинг, статусы, try-send-now.

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

import config
from aiogram import Bot

from services.db_api import db_api_client
from utils.common import log_and_report
from services.audience import resolve_audience  # единый аудит-сервис
from .sender import send_media

log = logging.getLogger(__name__)

# сколько результатов копим в буфере перед /deliveries/report
REPORT_BATCH = 200


async def _try_materialize(broadcast_id: int, user_ids: List[int]) -> None:
    """
    Создаём pending-записи в broadcast_deliveries.
    Если метод клиента пока не реализован — пропускаем, не ломая поток.
    """
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
        # мягкий fallback: метод ещё не добавлен в клиент
        log.debug("deliveries_materialize отсутствует в db_api_client — шаг пропускаю")
    except Exception as e:
        log.warning("materialize %s: ошибка %s", broadcast_id, e)


async def _try_report(broadcast_id: int, items: List[Dict[str, Any]]) -> None:
    """
    Батч-репорт результатов доставки (sent/failed/…).
    Если метод клиента пока не реализован — пропускаем.
    """
    if not items:
        return
    try:
        res = await db_api_client.deliveries_report(broadcast_id, items=items)
        log.debug(
            "report %s: processed=%s updated=%s inserted=%s",
            broadcast_id, res.get("processed"), res.get("updated"), res.get("inserted")
        )
    except AttributeError:
        log.debug("deliveries_report отсутствует в db_api_client — шаг пропускаю")
    except Exception as e:
        log.warning("report %s: ошибка %s", broadcast_id, e)


async def send_broadcast(bot: Bot, broadcast: dict, throttle_per_sec: Optional[int] = None) -> Tuple[int, int]:
    """Основная отправка рассылки по её описанию из БД."""
    bid = broadcast["id"]
    rate = throttle_per_sec or getattr(config, "BROADCAST_RATE_PER_SEC", 29)
    rate = max(1, int(rate))
    window = 1.0 / rate

    # 1. Загружаем контент
    try:
        media = await db_api_client.get_broadcast_media(bid)
        log.info("Загружен контент рассылки id=%s (%s элементов)", bid, len(media))
    except Exception as e:
        log.error("Не удалось загрузить медиа для рассылки id=%s: %s", bid, e)
        media = []

    try:
        target = await db_api_client.get_broadcast_target(bid)
        log.info("Загружена аудитория рассылки id=%s", bid)
    except Exception as e:
        log.error("Не удалось получить аудиторию рассылки id=%s: %s", bid, e)
        target = None

    # 2. Чистим пустые HTML-элементы
    if media:
        cleaned: List[Dict[str, Any]] = []
        for it in media:
            if it.get("type") == "html":
                txt = ((it.get("payload") or {}).get("text") or "").strip()
                if not txt:
                    log.warning("Удалён пустой html-элемент из рассылки id=%s", bid)
                    continue
            cleaned.append(it)
        media = cleaned

    # 3. Fallback — контент из broadcast["content_html"]
    if not media:
        html = (broadcast.get("content_html") or "").strip()
        if html:
            media = [{"type": "html", "payload": {"text": html}}]

    if not media:
        log.error("Рассылка id=%s не отправлена: нет контента", bid)
        return 0, 0

    # 4. Формируем аудиторию
    audience = await resolve_audience(target)
    if not audience:
        log.warning("Рассылка id=%s не отправлена: аудитория пустая", bid)
        return 0, 0

    # 4.1 Материализуем pending (идемпотентно; если метод ещё не добавлен — шаг тихо пропустится)
    await _try_materialize(bid, audience)

    log.info("Начинаю рассылку id=%s: аудитория=%s, скорость=%s msg/с", bid, len(audience), rate)

    # 5. Цикл отправки + батч-репорт
    sent = 0
    failed = 0
    report_buf: List[Dict[str, Any]] = []

    for uid in audience:
        ok = await send_media(bot, uid, media)
        if ok:
            sent += 1
            report_buf.append({"user_id": uid, "status": "sent"})
            log.debug("Сообщение отправлено пользователю %s (id рассылки=%s)", uid, bid)
        else:
            failed += 1
            report_buf.append({"user_id": uid, "status": "failed"})
            log.debug("Ошибка при отправке пользователю %s (id рассылки=%s)", uid, bid)

        if len(report_buf) >= REPORT_BATCH:
            await _try_report(bid, report_buf)
            report_buf.clear()

        await asyncio.sleep(window)

    # добросим хвост буфера
    if report_buf:
        await _try_report(bid, report_buf)

    # 6. Итог
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
    """Помечаем рассылку как 'sent' в БД."""
    log.info("Помечаем рассылку id=%s как доставленную", broadcast_id)
    return await db_api_client.update_broadcast(broadcast_id, status="sent")


# --- Немедленная попытка отправки конкретной рассылки ---
from .worker import _parse_dt_msk, _now_msk  # функции времени в МСК


async def try_send_now(bot: Bot, broadcast_id: int) -> None:
    """Принудительная проверка и запуск рассылки."""
    try:
        b = await db_api_client.get_broadcast(broadcast_id)
        log.info("Получена рассылка id=%s для немедленной проверки", broadcast_id)
    except Exception as e:
        log.error("Не удалось загрузить рассылку id=%s: %s", broadcast_id, e)
        return

    if b.get("status") != "scheduled":
        log.info("Рассылка id=%s не в статусе scheduled (status=%s) — пропускаем", broadcast_id, b.get("status"))
        return

    sch = _parse_dt_msk(b.get("scheduled_at"))
    now = _now_msk()
    if sch and sch > now:
        log.info("Рассылка id=%s запланирована на будущее (%s) — пока не отправляем", broadcast_id, b.get("scheduled_at"))
        return

    try:
        sent, failed = await send_broadcast(bot, b)
        if sent > 0:
            await mark_broadcast_sent(broadcast_id)
    except Exception as e:
        log.error("Ошибка при немедленной отправке рассылки id=%s: %s", broadcast_id, e)


__all__ = ["send_broadcast", "try_send_now", "mark_broadcast_sent"]
