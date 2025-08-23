# services/audience_service.py
# Аудитории: нормализация, превью, материализация «всем»

from __future__ import annotations

import logging
from typing import Any, Dict, List

import config
from services.db_api import db_api_client
from utils.common import log_and_report  # отчёт в ERROR_LOG_CHANNEL_ID

log = logging.getLogger(__name__)


def normalize_ids(text: str) -> List[int]:
    """Преобразует строку с ID в список уникальных int, сохраняя порядок."""
    out: List[int] = []
    seen = set()
    for chunk in (text or "").replace(",", " ").split():
        if chunk.isdigit():
            v = int(chunk)
            if v not in seen:
                seen.add(v)
                out.append(v)
    return out


async def audience_preview_text(target: Dict[str, Any], limit: int = 10_000) -> str:
    """
    Предпросмотр аудитории (total + пример).
    Логи: кратко и по делу — какой тип, какой лимит, сколько всего нашли.
    """
    try:
        prev = await db_api_client.audience_preview(target, limit=limit)
        total = prev.get("total", 0)
        sample = prev.get("sample") or []
        sample_txt = ", ".join(map(str, sample[:10])) if sample else ""
        tail = f"\nПример ID: <code>{sample_txt}</code>" if sample_txt else ""

        logging.info(
            f"Предпросмотр аудитории выполнен: тип={target.get('type')}, лимит={limit}, всего={total}",
            extra={"user_id": config.BOT_ID},
        )
        return f"👤 Всего в аудитории: <b>{total}</b>{tail}"
    except Exception as exc:
        logging.error(
            f"Предпросмотр аудитории не выполнен: тип={target.get('type')}, лимит={limit}, ошибка={exc}",
            extra={"user_id": config.BOT_ID},
        )
        await log_and_report(exc, f"предпросмотр аудитории, тип={target.get('type')}, лимит={limit}")
        return "⚠️ Предпросмотр аудитории недоступен."


async def materialize_all_user_ids(limit: int = 1000) -> List[int]:
    """
    Материализация «Все (ALL)» через membership’ы бота (chat_id = BOT_ID).
    Логи: старт, прогресс по батчам, завершение с количеством.
    """
    try:
        logging.info(
            f"Материализация ALL: старт для chat_id={config.BOT_ID}, шаг={limit}",
            extra={"user_id": config.BOT_ID},
        )

        ids: List[int] = []
        offset = 0
        total_rows = 0
        batches = 0

        while True:
            try:
                rows = await db_api_client.list_memberships_by_chat(
                    config.BOT_ID,
                    limit=limit,
                    offset=offset,
                )
            except TypeError:
                # Сервер без пагинации — один запрос
                rows = await db_api_client.list_memberships_by_chat(config.BOT_ID)

            if not rows:
                break

            batches += 1
            total_rows += len(rows)

            for r in rows:
                uid = r.get("user_id") if isinstance(r, dict) else None
                if isinstance(uid, int):
                    ids.append(uid)

            # Конец пагинации
            if not isinstance(rows, list) or len(rows) < limit:
                break

            offset += limit
            logging.info(
                f"Материализация ALL: обработан батч №{batches}, всего строк={total_rows}",
                extra={"user_id": config.BOT_ID},
            )

        # uniq с сохранением порядка
        seen = set()
        out: List[int] = []
        for v in ids:
            if v not in seen:
                seen.add(v)
                out.append(v)

        logging.info(
            f"Материализация ALL: завершено, уникальных пользователей={len(out)}, батчей={batches}, просмотрено строк={total_rows}",
            extra={"user_id": config.BOT_ID},
        )
        return out

    except Exception as exc:
        logging.error(
            f"Материализация ALL не выполнена: chat_id={config.BOT_ID}, ошибка={exc}",
            extra={"user_id": config.BOT_ID},
        )
        await log_and_report(exc, f"материализация ALL, chat_id={config.BOT_ID}")
        return []
