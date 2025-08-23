# services/content_builder.py
# Сбор и нормализация медиа под формат отправителя (text/caption/album)

from __future__ import annotations

import logging
import asyncio
from typing import Any, Dict, List

import config
from utils.common import log_and_report  # отчёт в ERROR_LOG_CHANNEL_ID

log = logging.getLogger(__name__)


def make_media_items(collected: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Нормализует контент в единый формат:
      • текст → payload['text']
      • подписи → payload['caption']
      • альбом → payload['items'] (каждый элемент с caption)
    Логи: что собрали — текст есть/нет, сколько одиночных, сколько в альбоме, всего объектов.
    """
    try:
        items: List[Dict[str, Any]] = []

        # Текст
        text_html = (collected or {}).get("text_html")
        if text_html:
            items.append({"type": "html", "payload": {"text": text_html}, "position": 0})

        # Одиночные медиа
        single_media = (collected or {}).get("single_media") or []
        for it in single_media:
            payload = {"file_id": it["file_id"]}
            cap = it.get("caption_html") or it.get("caption")
            if cap:
                payload["caption"] = cap
            items.append({"type": it["type"], "payload": payload, "position": len(items)})

        # Альбом
        album = (collected or {}).get("album") or []
        if album:
            norm_items: List[Dict[str, Any]] = []
            for el in album[:10]:
                t = el.get("type")
                file_id = el.get("file_id") or (el.get("payload") or {}).get("file_id")
                cap = (
                    el.get("caption")
                    or el.get("caption_html")
                    or (el.get("payload") or {}).get("caption")
                    or (el.get("payload") or {}).get("caption_html")
                )
                norm = {"type": t, "payload": {"file_id": file_id}}
                if cap:
                    norm["payload"]["caption"] = cap
                norm_items.append(norm)
            items.append({"type": "album", "payload": {"items": norm_items}, "position": len(items)})

        logging.info(
            "Сбор медиа завершён: текст=%s, одиночных=%s, в_альбоме=%s, всего_объектов=%s",
            "да" if bool(text_html) else "нет",
            len(single_media),
            len(album),
            len(items),
            extra={"user_id": config.BOT_ID},
        )
        return items

    except Exception as exc:
        logging.error(
            f"Сбор медиа не выполнен: ошибка={exc}",
            extra={"user_id": config.BOT_ID},
        )
        # Отчёт в фоновом таске (если есть цикл)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(log_and_report(exc, "сбор медиа"))
        except Exception:
            pass
        return []
