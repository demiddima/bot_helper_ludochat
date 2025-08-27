# Mailing/services/broadcasts/worker.py
# commit: refactor(worker): оставлена только фоновая синхронизация планировщика; без due и отправок

from __future__ import annotations

import logging
from typing import Optional

import config
from aiogram import Bot

from Mailing.services.local_scheduler import run_refresh_loop

log = logging.getLogger(__name__)


async def run_broadcast_worker(bot: Bot, interval_seconds: Optional[int] = None) -> None:
    """
    Фоновая задача: периодически сверяет список рассылок в БД и
    обновляет локальные задачи планировщика.
    """
    interval = int(interval_seconds or getattr(config, "BROADCAST_WORKER_INTERVAL", 900))
    interval = max(5, interval)  # минимальная пауза — 5 сек
    log.info("Фоновая синхронизация рассылок запущена (каждые %s секунд)", interval)
    await run_refresh_loop(bot, interval_seconds=interval)


# Совместимость со старым интерфейсом: планирование и отправка теперь не здесь.
async def get_due_broadcasts() -> list:
    return []


__all__ = ["run_broadcast_worker", "get_due_broadcasts"]
