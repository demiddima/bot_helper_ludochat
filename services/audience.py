# services/audience.py
# ЕДИНЫЙ модуль аудиторий:
#  - normalize_ids(text) — парсинг строк в список user_id
#  - audience_preview_text(target, limit) — превью аудитории (ALL/IDs/kind/SQL)
#  - materialize_all_user_ids(limit) — материализация "ALL" по membership’ам бота
#  - resolve_audience(target) — материализация таргета рассылки в список ID
#  - iter_audience_kind(kind) — пользователи, подписанные на тип (news/meetings/important)

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, AsyncIterator, Iterable

import config
from services.db_api import db_api_client
from utils.common import log_and_report  # отчёт в ERROR_LOG_CHANNEL_ID

log = logging.getLogger(__name__)

# Флаги подписок → поля в user_subscriptions
KIND_FLAG: Dict[str, str] = {
    "news": "news_enabled",
    "meetings": "meetings_enabled",
    "important": "important_enabled",
}


# ---------- НОРМАЛИЗАЦИЯ ID ----------

def normalize_ids(text: str) -> List[int]:
    """
    Парсит строку с ID: допускает пробелы/переносы/запятые/точки с запятой/табуляции/знаки пунктуации.
    Сохраняет порядок, удаляет дубли, отбрасывает нечисловые.
    """
    if not text:
        return []
    seps = ",;|\n\t\r"
    t = text
    for ch in seps:
        t = t.replace(ch, " ")
    t = t.replace("  ", " ")
    raw = t.split()
    out: List[int] = []
    seen = set()
    for chunk in raw:
        try:
            v = int(chunk)
        except Exception:
            continue
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _normalize_ids_list(val: Any) -> List[int]:
    """
    Универсальная нормализация набора ID:
      - принимает list/tuple/set/str/int/None;
      - строки парсим через normalize_ids();
      - удаляет дубликаты, сохраняет порядок.
    """
    if val is None:
        return []
    if isinstance(val, str):
        return normalize_ids(val)
    parts: Iterable[Any]
    if isinstance(val, (list, tuple, set)):
        parts = val
    else:
        parts = [val]
    out: List[int] = []
    seen = set()
    for p in parts:
        try:
            v = int(p)
        except Exception:
            continue
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


# ---------- PREVIEW / MATERIALIZE ALL ----------

async def audience_preview_text(target: Dict[str, Any], limit: int = 30) -> str:
    """
    Превью аудитории «в человекочитаемом виде».
    target поддерживает типы: ids/kind/sql/all (all мапится на kind|ids снаружи).
    """
    try:
        res = await db_api_client.audience_preview(target, limit=limit)
        total = int(res.get("total") or 0)
        sample = res.get("sample") or []
        lines = "\n".join(f"• <code>{row}</code>" for row in sample)
        tail = f"\n{lines}" if lines else ""
        logging.info(
            "Предпросмотр аудитории: тип=%s, total=%s, sample=%s",
            target.get("type"), total, len(sample),
            extra={"user_id": config.BOT_ID},
        )
        return f"👤 Всего в аудитории: <b>{total}</b>{tail}"
    except Exception as exc:
        logging.error(
            "Предпросмотр аудитории не выполнен: тип=%s, лимит=%s, ошибка=%s",
            target.get("type"), limit, exc,
            extra={"user_id": config.BOT_ID},
        )
        await log_and_report(exc, f"предпросмотр аудитории, тип={target.get('type')}, лимит={limit}")
        return "⚠️ Предпросмотр аудитории недоступен."


async def materialize_all_user_ids(limit: int = 1000) -> List[int]:
    """
    Материализация «ALL» через membership’ы бота (chat_id=BOT_ID).
    Пагинируем list_memberships_by_chat(limit/offset) до исчерпания.
    """
    out: List[int] = []
    seen = set()
    offset = 0
    total_rows = 0
    batches = 0
    try:
        while True:
            rows = await db_api_client.list_memberships_by_chat(config.BOT_ID, limit=limit, offset=offset)
            rows = rows or []
            if not rows:
                break
            batches += 1
            total_rows += len(rows)
            ids = []
            for r in rows:
                uid = (r.get("user_id") if isinstance(r, dict) else None)
                if isinstance(uid, int):
                    ids.append(uid)
            for v in ids:
                if v not in seen:
                    seen.add(v)
                    out.append(v)
            if len(rows) < limit:
                break
            offset += limit

        logging.info(
            "Материализация ALL: завершено, уникальных пользователей=%s, батчей=%s, просмотрено строк=%s",
            len(out), batches, total_rows,
            extra={"user_id": config.BOT_ID},
        )
        return out

    except Exception as exc:
        logging.error(
            "Материализация ALL не выполнена: chat_id=%s, ошибка=%s",
            config.BOT_ID, exc,
            extra={"user_id": config.BOT_ID},
        )
        await log_and_report(exc, f"материализация ALL, chat_id={config.BOT_ID}")
        return []


# ---------- KIND-АУДИТОРИИ (по подпискам) ----------

async def iter_audience_kind(kind: str) -> AsyncIterator[int]:
    """
    Перебор user_id, подписанных на тип рассылки:
      - берём всех участников «чата бота» (chat_id = BOT_ID)
      - фильтруем по user_subscriptions.<flag>
    """
    flag_name = KIND_FLAG.get(kind)
    if not flag_name:
        log.warning("iter_audience_kind: неизвестный kind=%s", kind, extra={"user_id": config.BOT_ID})
        return

    try:
        memberships = await db_api_client.list_memberships_by_chat(config.BOT_ID)
    except Exception as exc:
        log.error("iter_audience_kind: ошибка получения memberships: %s", exc, extra={"user_id": config.BOT_ID})
        return

    for m in (memberships or []):
        uid = m.get("user_id") if isinstance(m, dict) else None
        if not isinstance(uid, int):
            continue
        try:
            subs = await db_api_client.get_user_subscriptions(uid)
        except Exception as exc:
            log.error("iter_audience_kind: не удалось прочитать подписки: user_id=%s, err=%s", uid, exc, extra={"user_id": uid})
            continue
        if subs.get(flag_name):
            yield uid


# ---------- РАЗВОРАЧИВАНИЕ TARGET ДЛЯ РАССЫЛОК ----------

async def resolve_audience(target: Optional[Dict[str, Any]]) -> List[int]:
    """
    Материализует аудиторию рассылки в список user_id.
    Поддерживаемые формы:
      - {"type":"ids","user_ids":[...]}  — основная
      - {"type":"ids","ids":[...]}       — альтернативное поле
      - {"type":"kind","kind":"news|meetings|important"}
      - {"type":"sql","sql":"SELECT ... AS user_id"}  — пока не материализуем (только предупреждаем)
    """
    if not target:
        log.warning("resolve_audience: target отсутствует")
        return []

    t = target.get("type")
    if t == "ids":
        raw = target.get("user_ids")
        if raw is None:
            raw = target.get("ids")  # обратная совместимость
        ids = _normalize_ids_list(raw)
        log.info("resolve_audience(ids): %s шт.", len(ids), extra={"user_id": config.BOT_ID})
        return ids

    if t == "kind":
        kind = (target.get("kind") or "").strip()
        if not kind:
            log.warning("resolve_audience(kind): пустой kind")
            return []
        out: List[int] = []
        async for uid in iter_audience_kind(kind):
            out.append(uid)
        log.info("resolve_audience(kind=%s): %s шт.", kind, len(out), extra={"user_id": config.BOT_ID})
        return out

    if t == "sql":
        try:
            prev = await db_api_client.audience_preview({"type": "sql", "sql": target.get("sql")}, limit=1000)
            total = prev.get("total")
            log.warning(
                "resolve_audience(sql): SQL-аудитория не материализуется на отправке (preview only), total=%s",
                total, extra={"user_id": config.BOT_ID}
            )
        except Exception as exc:
            log.error("resolve_audience(sql): ошибка превью: %s", exc, extra={"user_id": config.BOT_ID})
        return []

    log.warning("resolve_audience: неизвестный тип target=%s", t, extra={"user_id": config.BOT_ID})
    return []


__all__ = [
    "normalize_ids",
    "audience_preview_text",
    "materialize_all_user_ids",
    "resolve_audience",
    "iter_audience_kind",
    "KIND_FLAG",
]
