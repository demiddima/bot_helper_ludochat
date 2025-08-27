# Mailing/services/schedule.py
# Коммит: fix(schedule/oneoff): принимать часы/минуты без ведущих нулей (например, 27.08.2025 1:56)

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import List, Tuple, Literal
from zoneinfo import ZoneInfo

try:
    from croniter import croniter
except Exception:
    croniter = None  # при использовании cron-превью/проверок дадим понятную ошибку

_TZ = ZoneInfo("Europe/Moscow")
# Было: ^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})$
# Стало мягче: допускаем 1–2 цифры для дня/месяца/часов/минут
_ONEOFF_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{1,2})\s*$")

Kind = Literal["oneoff", "cron"]


class ScheduleError(ValueError):
    pass


def is_oneoff_text(s: str) -> bool:
    return bool(_ONEOFF_RE.match(s or ""))


def parse_oneoff_msk(s: str) -> datetime:
    m = _ONEOFF_RE.match(s or "")
    if not m:
        # подчёркиваем, что допускаем вариант без нулей
        raise ScheduleError("Формат: <b>ДД.ММ.ГГГГ HH:MM</b> (МСК). Допустимо без ведущих нулей, например <code>27.8.2025 1:56</code>.")
    dd, mm, yyyy, hh, mi = map(int, m.groups())
    try:
        return datetime(yyyy, mm, dd, hh, mi, 0, tzinfo=_TZ)
    except Exception:
        raise ScheduleError("Неверная дата/время.")


def ensure_future(dt: datetime) -> datetime:
    if dt <= datetime.now(_TZ):
        raise ScheduleError("Время уже прошло.")
    return dt


def is_valid_cron(s: str) -> bool:
    parts = (s or "").split()
    if len(parts) != 5:
        return False
    if croniter is not None:
        try:
            return croniter.is_valid(s)
        except Exception:
            return False
    import re as _re
    return all(bool(_re.match(r"^[\d\*,/\-]+$", p)) for p in parts)


def preview_cron(s: str, count: int = 5) -> List[datetime]:
    if croniter is None:
        raise ScheduleError("Для cron-превью добавьте зависимость <code>croniter</code>.")
    it = croniter(s, datetime.now(_TZ))
    return [it.get_next(datetime).astimezone(_TZ) for _ in range(max(1, int(count)))]


def parse_and_preview(schedule: str, count: int = 5) -> Tuple[Kind, List[datetime]]:
    schedule = (schedule or "").strip()
    if not schedule:
        raise ScheduleError("Пустое расписание. Введите дату/время или cron.")
    # one-off — распознаём мягко (1–2 цифры)
    if is_oneoff_text(schedule):
        return "oneoff", [ensure_future(parse_oneoff_msk(schedule))]
    # иначе — это cron
    if not is_valid_cron(schedule):
        raise ScheduleError("Неверный cron (5 полей). Пример: <code>0 15 * * 1,3,5</code>")
    return "cron", preview_cron(schedule, count=count)


def format_preview(kind: str, dates: List[datetime]) -> str:
    if kind == "oneoff":
        dt = dates[0]
        return f"Разовая рассылка: <b>{dt:%d.%m.%Y %H:%M}</b> (МСК)"
    rows = [f"{i+1}. {dt:%d.%m.%Y %H:%M} (МСК)" for i, dt in enumerate(dates)]
    return "Ближайшие запуски:\n" + "\n".join(rows)


# -------- due-проверки для тикового воркера --------

def due_oneoff_now(schedule: str, *, window_sec: int = 60) -> bool:
    """
    True, если 'ДД.ММ.ГГГГ HH:MM' попадает в текущее минутное окно [now-window, now].
    """
    try:
        dt = parse_oneoff_msk(schedule)
    except ScheduleError:
        return False
    now = datetime.now(_TZ)
    window_start = now - timedelta(seconds=max(1, int(window_sec)))
    return window_start < dt <= now


def due_cron_now(schedule: str, *, window_sec: int = 60) -> bool:
    """
    True, если cron «выстреливает» в текущем минутном окне.
    """
    if not is_valid_cron(schedule) or croniter is None:
        return False
    now = datetime.now(_TZ)
    window_start = now - timedelta(seconds=max(1, int(window_sec)))
    it = croniter(schedule, window_start)
    nxt = it.get_next(datetime).astimezone(_TZ)
    return window_start < nxt <= now
