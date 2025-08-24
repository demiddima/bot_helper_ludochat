# services/broadcasts/worker.py
# Выбор «пора» и фоновый воркер.

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import List, Optional

import config
from aiogram import Bot

from common.db_api import db_api_client
from common.utils.time_msk import now_msk_naive, from_iso_naive
from common.utils.common import log_and_report
from .service import send_broadcast, mark_broadcast_sent

log = logging.getLogger(__name__)


def _now_msk() -> datetime:
    """Текущее время в МСК (naive)."""
    return now_msk_naive()


def _parse_dt_msk(dt_str: Optional[str]) -> Optional[datetime]:
    """Парсим дату/время в МСК из строки ISO (без таймзоны)."""
    if not dt_str:
        return None
    try:
        return from_iso_naive(dt_str.rstrip("Z"))
    except Exception:
        return None


async def get_due_broadcasts(limit: int = 200) -> List[dict]:
    """
    Получаем рассылки, которые пора отправить:
      - статус = scheduled
      - время планирования <= сейчас
    """
    items = await db_api_client.list_broadcasts(limit=limit, offset=0)
    now = _now_msk()
    due: List[dict] = []

    for b in items:
        if b.get("status") != "scheduled":
            continue

        sch_raw = b.get("scheduled_at")
        sch = _parse_dt_msk(sch_raw)

        if sch is None:
            log.warning(
                "У рассылки id=%s пустое или некорректное scheduled_at (%s) — считаем, что пора отправлять",
                b.get("id"), sch_raw, extra={"user_id": config.BOT_ID}
            )
            due.append(b)
            continue

        if sch <= now:
            due.append(b)

    due.sort(key=lambda x: _parse_dt_msk(x.get("scheduled_at")) or now)
    return due


async def run_broadcast_worker(bot: Bot, interval_seconds: int = 20):
    """
    Фоновый воркер:
      - раз в interval_seconds проверяет список рассылок
      - если есть "пора" — запускает их отправку
    """
    log.info("Воркер рассылок запущен (интервал проверки %s секунд)", interval_seconds, extra={"user_id": config.BOT_ID})

    while True:
        try:
            due = await get_due_broadcasts(limit=200)

            if due:
                log.info(
                    "Найдено рассылок к отправке: %s (id=%s)",
                    len(due), [b.get("id") for b in due], extra={"user_id": config.BOT_ID}
                )

            for b in due:
                bid = b["id"]
                try:
                    sent, failed = await send_broadcast(bot, b)

                    if sent > 0:
                        log.info(
                            "Рассылка id=%s завершена: доставлено=%s, ошибок=%s. Помечаем как отправленную.",
                            bid, sent, failed, extra={"user_id": config.BOT_ID}
                        )
                        await mark_broadcast_sent(bid)
                    else:
                        log.error(
                            "Рассылка id=%s не доставлена ни одному пользователю (sent=%s, failed=%s). Статус не меняем.",
                            bid, sent, failed, extra={"user_id": config.BOT_ID}
                        )

                except Exception as exc:
                    log.error(
                        "Ошибка при отправке рассылки id=%s: %s",
                        bid, exc, extra={"user_id": config.BOT_ID}
                    )
                    try:
                        await log_and_report(exc, f"Ошибка воркера при отправке рассылки id={bid}")
                    except Exception:
                        pass

            await asyncio.sleep(interval_seconds)

        except Exception as exc:
            log.error(
                "Критическая ошибка цикла воркера: %s", exc, extra={"user_id": config.BOT_ID}
            )
            try:
                await log_and_report(exc, "Критическая ошибка цикла воркера")
            except Exception:
                pass
            await asyncio.sleep(interval_seconds)


__all__ = ["run_broadcast_worker", "get_due_broadcasts", "_parse_dt_msk", "_now_msk"]
