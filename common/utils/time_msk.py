from __future__ import annotations
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

# utils/time_msk.py
MSK = ZoneInfo("Europe/Moscow")

def from_iso_naive(s: str) -> Optional[datetime]:
    """Строка из API → naive datetime (ожидаем 'YYYY-MM-DD HH:MM:SS' или ISO)."""
    if not s:
        return None
    s = s.replace("T", " ")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None

def now_msk_naive() -> datetime:
    """Текущее московское время без tzinfo (naive)."""
    return datetime.now(MSK).replace(tzinfo=None)

def parse_msk(text: str) -> Optional[datetime]:
    """
    Парсим строку как московское время и возвращаем aware datetime (Europe/Moscow).
    Поддержка форматов:
    - YYYY-MM-DD HH:MM
    - DD.MM.YYYY HH:MM
    """
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M"):
        try:
            naive = datetime.strptime(text, fmt)
            return naive.replace(tzinfo=MSK)
        except ValueError:
            continue
    return None

def to_msk_naive(dt: datetime) -> datetime:
    """Любой datetime → московское naive (обрезаем tz)."""
    if dt.tzinfo is None:
        # Считаем, что уже МСК, просто возвращаем как есть
        return dt
    return dt.astimezone(MSK).replace(tzinfo=None)
