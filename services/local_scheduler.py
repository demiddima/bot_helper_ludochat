# services/local_scheduler.py
# Локальный планировщик: при создании/переносе рассылки ставим asyncio-таску,
# которая уснёт до назначенного времени и вызовет send_broadcast_now.
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from zoneinfo import ZoneInfo
from services.db_api import db_api_client

log = logging.getLogger(__name__)
MSK = ZoneInfo("Europe/Moscow")

_tasks: Dict[int, asyncio.Task] = {}  # broadcast_id -> task


def _now_tz(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)


def _seconds_until(run_at: datetime, now: Optional[datetime] = None) -> float:
    """run_at — aware datetime; считаем задержку до цели (не меньше 0)."""
    if run_at.tzinfo is None:
        # трактуем как МСК, если вдруг прислали naive
        run_at = run_at.replace(tzinfo=MSK)
    if now is None:
        now = _now_tz(run_at.tzinfo)
    delta = (run_at - now).total_seconds()
    return max(0.0, delta)


async def _send_when_due(broadcast_id: int, run_at: datetime) -> None:
    delay = _seconds_until(run_at)
    if delay > 0:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            log.info("[local_scheduler] task cancelled for #%s", broadcast_id)
            return

    # Пора отправлять (или уже просрочено): вызываем send_now
    try:
        log.info("[local_scheduler] sending now #%s (scheduled_at=%s)", broadcast_id, run_at.isoformat())
        await db_api_client.send_broadcast_now(broadcast_id)
    except Exception as e:
        log.exception("[local_scheduler] failed to send_now #%s: %s", broadcast_id, e)


def schedule_broadcast_send(broadcast_id: int, run_at: datetime) -> None:
    """
    Ставит/переставляет локальную задачу на точное время (aware datetime).
    Если задача уже была — отменяет и ставит заново.
    """
    # Отменяем прежнюю
    old = _tasks.pop(broadcast_id, None)
    if old and not old.done():
        old.cancel()

    # Создаём новую
    task = asyncio.create_task(_send_when_due(broadcast_id, run_at))
    _tasks[broadcast_id] = task
    log.info("[local_scheduler] scheduled local task for #%s at %s", broadcast_id, run_at.isoformat())


def cancel_broadcast_send(broadcast_id: int) -> None:
    """Отменить локальную задачу (если рассылку сняли с расписания)."""
    old = _tasks.pop(broadcast_id, None)
    if old and not old.done():
        old.cancel()
        log.info("[local_scheduler] cancelled local task for #%s", broadcast_id)
