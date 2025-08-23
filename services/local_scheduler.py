# services/local_scheduler.py
# Локальный планировщик: при создании/переносе рассылки ставим asyncio-таску,
# которая уснёт до назначенного времени и вызовет send_broadcast_now.

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional

from zoneinfo import ZoneInfo

import config
from services.db_api import db_api_client
from utils.common import log_and_report  # отчёт в ERROR_LOG_CHANNEL_ID

log = logging.getLogger(__name__)
MSK = ZoneInfo("Europe/Moscow")

_tasks: Dict[int, asyncio.Task] = {}  # broadcast_id -> task


def _now_tz(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)


def _seconds_until(run_at: datetime, now: Optional[datetime] = None) -> float:
    """
    run_at — aware datetime; считаем задержку до цели (не меньше 0).
    Если пришёл naive — трактуем как МСК.
    """
    if run_at.tzinfo is None:
        run_at = run_at.replace(tzinfo=MSK)
    if now is None:
        now = _now_tz(run_at.tzinfo)
    delta = (run_at - now).total_seconds()
    return max(0.0, delta)


async def _send_when_due(broadcast_id: int, run_at: datetime) -> None:
    try:
        delay = _seconds_until(run_at)
        if delay > 0:
            try:
                logging.info(
                    "Локальная задача: уснём до отправки — рассылка=%s, задержка=%.3fс, плановое=%s",
                    broadcast_id, delay, run_at.isoformat(),
                    extra={"user_id": config.BOT_ID},
                )
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                logging.info(
                    "Локальная задача: отменена до отправки — рассылка=%s",
                    broadcast_id,
                    extra={"user_id": config.BOT_ID},
                )
                return

        # Срок наступил или уже просрочено — запрашиваем отправку
        try:
            logging.info(
                "Локальная задача: запрашиваем отправку — рассылка=%s, плановое=%s",
                broadcast_id, run_at.isoformat(),
                extra={"user_id": config.BOT_ID},
            )
            await db_api_client.send_broadcast_now(broadcast_id)
            logging.info(
                "Локальная задача: запрос на отправку принят — рассылка=%s",
                broadcast_id,
                extra={"user_id": config.BOT_ID},
            )
        except Exception as exc:
            logging.error(
                "Локальная задача: не удалось отправить — рассылка=%s, ошибка=%s",
                broadcast_id, exc,
                extra={"user_id": config.BOT_ID},
            )
            await log_and_report(exc, f"локальная отправка, id={broadcast_id}")

    except Exception as exc:
        logging.error(
            "Локальная задача: критическая ошибка — рассылка=%s, ошибка=%s",
            broadcast_id, exc,
            extra={"user_id": config.BOT_ID},
        )
        await log_and_report(exc, f"локальная задача, id={broadcast_id}")


def schedule_broadcast_send(broadcast_id: int, run_at: datetime) -> None:
    """
    Ставит/переставляет локальную задачу на указанное время (aware datetime).
    Если задача уже была — отменяет и ставит заново.
    """
    try:
        # Отменяем предыдущую задачу, если она есть
        old = _tasks.pop(broadcast_id, None)
        if old and not old.done():
            old.cancel()
            logging.info(
                "Локальная задача: прежняя отменена — рассылка=%s",
                broadcast_id,
                extra={"user_id": config.BOT_ID},
            )

        # Ставим новую
        task = asyncio.create_task(_send_when_due(broadcast_id, run_at))
        _tasks[broadcast_id] = task
        logging.info(
            "Локальная задача: запланирована — рассылка=%s, время=%s",
            broadcast_id, run_at.isoformat(),
            extra={"user_id": config.BOT_ID},
        )
    except Exception as exc:
        logging.error(
            "Локальная задача: ошибка планирования — рассылка=%s, ошибка=%s",
            broadcast_id, exc,
            extra={"user_id": config.BOT_ID},
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(log_and_report(exc, f"планирование локальной задачи, id={broadcast_id}"))
        except Exception:
            pass


def cancel_broadcast_send(broadcast_id: int) -> None:
    """Отменить локальную задачу (если рассылку сняли с расписания)."""
    try:
        old = _tasks.pop(broadcast_id, None)
        if old and not old.done():
            old.cancel()
            logging.info(
                "Локальная задача: отменена — рассылка=%s",
                broadcast_id,
                extra={"user_id": config.BOT_ID},
            )
        else:
            logging.info(
                "Локальная задача: активной задачи нет — рассылка=%s",
                broadcast_id,
                extra={"user_id": config.BOT_ID},
            )
    except Exception as exc:
        logging.error(
            "Локальная задача: ошибка отмены — рассылка=%s, ошибка=%s",
            broadcast_id, exc,
            extra={"user_id": config.BOT_ID},
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(log_and_report(exc, f"отмена локальной задачи, id={broadcast_id}"))
        except Exception:
            pass
