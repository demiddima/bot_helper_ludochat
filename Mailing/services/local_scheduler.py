# services/local_scheduler.py
# Локальный планировщик: спим до времени → POST /send_now → СРАЗУ try_send_now()

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional
from zoneinfo import ZoneInfo

from aiogram import Bot

import config
from common.db_api import db_api_client
from Mailing.services.broadcasts import try_send_now
from common.utils.common import log_and_report  # отчёт в ERROR_LOG_CHANNEL_ID

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


async def _send_when_due(bot: Bot, broadcast_id: int, run_at: datetime) -> None:
    try:
        delay = _seconds_until(run_at)
        if delay > 0:
            try:
                log.info(
                    "[local_scheduler] Уснём до отправки — рассылка=%s, задержка=%.3fs, плановое=%s",
                    broadcast_id, delay, run_at.isoformat(),
                    extra={"user_id": config.BOT_ID},
                )
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                log.info(
                    "[local_scheduler] Отменена до отправки — рассылка=%s",
                    broadcast_id,
                    extra={"user_id": config.BOT_ID},
                )
                return

        # Срок наступил или уже просрочено — запрашиваем отправку на бэке
        try:
            log.info(
                "[local_scheduler] Запрашиваем отправку — рассылка=%s, плановое=%s",
                broadcast_id, run_at.isoformat(),
                extra={"user_id": config.BOT_ID},
            )
            await db_api_client.send_broadcast_now(broadcast_id)
            log.info(
                "[local_scheduler] Запрос на отправку принят — рассылка=%s",
                broadcast_id,
                extra={"user_id": config.BOT_ID},
            )
        except Exception as exc:
            log.error(
                "[local_scheduler] Не удалось отправить — рассылка=%s, ошибка=%s",
                broadcast_id, exc,
                extra={"user_id": config.BOT_ID},
            )
            await log_and_report(exc, f"локальная отправка, id={broadcast_id}")
            return
        finally:
            _tasks.pop(broadcast_id, None)

        # Немедленно пытаемся отправить с клиента, не ждём воркер
        try:
            await try_send_now(bot, broadcast_id)
        except Exception as exc:
            log.error("[local_scheduler] try_send_now failed — id=%s: %s", broadcast_id, exc)

    except Exception as exc:
        log.error(
            "[local_scheduler] Критическая ошибка — рассылка=%s, ошибка=%s",
            broadcast_id, exc,
            extra={"user_id": config.BOT_ID},
        )
        await log_and_report(exc, f"локальная задача, id={broadcast_id}")


def schedule_broadcast_send(bot: Bot, broadcast_id: int, run_at: datetime) -> None:
    """
    Ставит/переставляет локальную задачу на указанное время (aware datetime).
    Если задача уже была — отменяет и ставит заново.
    """
    try:
        old = _tasks.pop(broadcast_id, None)
        if old and not old.done():
            old.cancel()
            log.info(
                "[local_scheduler] Прежняя задача отменена — рассылка=%s",
                broadcast_id,
                extra={"user_id": config.BOT_ID},
            )

        task = asyncio.create_task(_send_when_due(bot, broadcast_id, run_at))
        _tasks[broadcast_id] = task
        log.info(
            "[local_scheduler] Задача запланирована — рассылка=%s, время=%s",
            broadcast_id, run_at.isoformat(),
            extra={"user_id": config.BOT_ID},
        )
    except Exception as exc:
        log.error(
            "[local_scheduler] Ошибка планирования — рассылка=%s, ошибка=%s",
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
            log.info(
                "[local_scheduler] Отменена — рассылка=%s",
                broadcast_id,
                extra={"user_id": config.BOT_ID},
            )
        else:
            log.info(
                "[local_scheduler] Активной задачи нет — рассылка=%s",
                broadcast_id,
                extra={"user_id": config.BOT_ID},
            )
    except Exception as exc:
        log.error(
            "[local_scheduler] Ошибка отмены — рассылка=%s, ошибка=%s",
            broadcast_id, exc,
            extra={"user_id": config.BOT_ID},
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(log_and_report(exc, f"отмена локальной задачи, id={broadcast_id}"))
        except Exception:
            pass
