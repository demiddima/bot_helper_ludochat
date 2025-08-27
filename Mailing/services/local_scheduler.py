# Mailing/services/local_scheduler.py
# commit: style(logs): человеко-понятные русские логи без названий функций

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, List

from aiogram import Bot

from common.db_api_client import db_api_client
from common.utils.common import log_and_report
from common.utils.time_msk import MSK
from Mailing.services.schedule import parse_and_preview, ScheduleError, is_oneoff_text
from Mailing.services.broadcasts.service import try_send_now

log = logging.getLogger(__name__)


@dataclass
class _Planned:
    task: asyncio.Task
    next_dt: datetime
    schedule_text: Optional[str]  # None — если задача поставлена по run_at (совместимость)


# Активные локальные задачи: broadcast_id → _Planned
_tasks: Dict[int, _Planned] = {}


# ---------- helpers ----------

def _now_aw() -> datetime:
    return datetime.now(MSK)

def _secs_until(dt: datetime) -> float:
    return max(0.0, (dt - _now_aw()).total_seconds())

async def _load_broadcast(bid: int) -> Optional[dict]:
    try:
        return await db_api_client.get_broadcast(bid)
    except Exception as e:
        log.warning("Не удалось загрузить рассылку #%s: %s", bid, e)
        return None

def _next_dt_from_text(schedule_text: str) -> Optional[datetime]:
    try:
        kind, dates = parse_and_preview(schedule_text, count=1)
        if not dates:
            return None
        return dates[0]
    except ScheduleError as e:
        log.warning("Некорректное расписание '%s': %s", schedule_text, e)
        return None


# ---------- публичный API ----------

async def schedule_after_create(bot: Bot, broadcast_id: int) -> None:
    """Вызвать сразу после создания рассылки: планируем ближайший запуск."""
    br = await _load_broadcast(broadcast_id)
    if br:
        await ensure_task_for(bot, br)


async def cancel(broadcast_id: int) -> None:
    """Отменить локальную задачу (если есть)."""
    planned = _tasks.pop(broadcast_id, None)
    if planned and not planned.task.done():
        planned.task.cancel()
        try:
            await planned.task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        log.info("Задача для рассылки #%s отменена", broadcast_id)


async def ensure_task_for(bot: Bot, br: dict) -> None:
    """Поставить или обновить ближайшую задачу для рассылки."""
    bid = int(br.get("id"))
    schedule_text = (br.get("schedule") or "").strip()
    enabled = bool(br.get("enabled", br.get("is_enabled", True)))

    if not schedule_text or not enabled:
        if bid in _tasks:
            await cancel(bid)
        return

    next_dt = _next_dt_from_text(schedule_text)
    if not next_dt:
        if bid in _tasks:
            await cancel(bid)
        return

    existed = _tasks.get(bid)
    if existed and existed.schedule_text == schedule_text and abs((existed.next_dt - next_dt).total_seconds()) < 1:
        return
    if existed:
        await cancel(bid)

    async def _runner():
        try:
            sleep_s = _secs_until(next_dt)
            if sleep_s > 0:
                try:
                    await asyncio.sleep(sleep_s)
                except asyncio.CancelledError:
                    log.info("Задача для рассылки #%s отменена до запуска", bid)
                    return

            fresh = await _load_broadcast(bid)
            if not fresh:
                return
            fresh_enabled = bool(fresh.get("enabled", fresh.get("is_enabled", True)))
            fresh_schedule = (fresh.get("schedule") or "").strip()
            if not fresh_enabled or fresh_schedule != schedule_text:
                log.info("Перед запуском параметры рассылки #%s изменились — запуск отменён", bid)
                return

            try:
                await db_api_client.send_broadcast_now(bid)
            except Exception as exc:
                log.warning("Бэкенд не смог запустить рассылку #%s: %s", bid, exc)
            try:
                await try_send_now(bot, bid)
            except Exception as exc:
                log.error("Локальный запуск рассылки #%s не удался: %s", bid, exc)

            if not is_oneoff_text(schedule_text):
                nxt = _next_dt_from_text(schedule_text)
                if nxt:
                    await ensure_task_for(bot, dict(id=bid, schedule=schedule_text, enabled=True))
                else:
                    await cancel(bid)
            else:
                await cancel(bid)

        except Exception as e:
            log.exception("Ошибка при выполнении задачи для рассылки #%s: %s", bid, e)

    task = asyncio.create_task(_runner(), name=f"broadcast_plan_{bid}")
    _tasks[bid] = _Planned(task=task, next_dt=next_dt, schedule_text=schedule_text)
    log.info("Запланирована рассылка #%s на %s (МСК)", bid, next_dt.strftime("%Y-%m-%d %H:%M:%S"))


async def refresh_all(bot: Bot) -> None:
    """Синхронизировать локальные задачи с БД (для воркера)."""
    broadcasts: List[dict] = []
    try:
        broadcasts = await db_api_client.list_broadcasts()
    except AttributeError:
        try:
            broadcasts = await db_api_client.get_broadcasts()
        except AttributeError:
            log.warning("В API нет метода для списка рассылок — синхронизация невозможна")
            return
    except Exception as e:
        log.warning("Ошибка при получении списка рассылок: %s", e)
        return

    seen = set()
    for br in broadcasts or []:
        bid = int(br.get("id"))
        seen.add(bid)
        await ensure_task_for(bot, br)

    for bid in list(_tasks.keys()):
        if bid not in seen:
            await cancel(bid)


async def run_refresh_loop(bot: Bot, interval_seconds: int) -> None:
    """Фоновая петля синхронизации с БД каждые interval_seconds секунд."""
    log.info("Фоновая синхронизация рассылок запущена (интервал %s сек)", interval_seconds)
    try:
        while True:
            await refresh_all(bot)
            await asyncio.sleep(max(5, int(interval_seconds)))
    except asyncio.CancelledError:
        log.info("Фоновая синхронизация остановлена")
        raise
    except Exception as e:
        log.exception("Фоновая синхронизация аварийно завершилась: %s", e)


# ---------- совместимость: старый API run_at ----------

async def _send_when_due_run_at(bot: Bot, broadcast_id: int, run_at: datetime) -> None:
    try:
        delay = _secs_until(run_at if run_at.tzinfo else run_at.replace(tzinfo=MSK))
        if delay > 0:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return

        try:
            await db_api_client.send_broadcast_now(broadcast_id)
        except Exception as exc:
            await log_and_report(exc, f"локальная отправка, id={broadcast_id}")
            return
        finally:
            _tasks.pop(broadcast_id, None)

        try:
            await try_send_now(bot, broadcast_id)
        except Exception:
            pass

    except Exception as exc:
        await log_and_report(exc, f"локальная задача, id={broadcast_id}")


def schedule_broadcast_send(bot: Bot, broadcast_id: int, run_at: datetime) -> None:
    try:
        old = _tasks.pop(broadcast_id, None)
        if old and not old.task.done():
            old.task.cancel()

        task = asyncio.create_task(_send_when_due_run_at(bot, broadcast_id, run_at))
        _tasks[broadcast_id] = _Planned(
            task=task,
            next_dt=run_at if run_at.tzinfo else run_at.replace(tzinfo=MSK),
            schedule_text=None,
        )
    except Exception:
        pass


def cancel_broadcast_send(broadcast_id: int) -> None:
    try:
        old = _tasks.pop(broadcast_id, None)
        if old and not old.task.done():
            old.task.cancel()
    except Exception:
        pass
