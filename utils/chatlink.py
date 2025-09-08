# utils/chatlink.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def is_url(v: Any) -> bool:
    """Строка-ссылка?"""
    return isinstance(v, str) and v.startswith("http")


def to_int_or_none(v: Any) -> int | None:
    """
    Приводим chat_id к int, если возможно.
    URL не трогаем. Любой мусор -> None.
    """
    if isinstance(v, int):
        return v
    if isinstance(v, str) and not is_url(v):
        try:
            return int(v)
        except ValueError:
            return None
    return None


def eq_chat_id(a: Any, b: Any) -> bool:
    """Сравнение chat_id, безопасно приводя оба значения к int."""
    ai = to_int_or_none(a)
    bi = to_int_or_none(b)
    return ai is not None and bi is not None and ai == bi


def parse_exp_aware(exp: Any) -> datetime | None:
    """
    Возвращает aware-datetime в UTC или None.
    Понимает ISO, 'Z', datetime без tz.
    """
    if isinstance(exp, datetime):
        return exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)

    if isinstance(exp, str):
        s = exp.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    return None
