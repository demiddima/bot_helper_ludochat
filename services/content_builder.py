# services/content_builder.py
# Сбор и нормализация медиа под формат отправителя (text/caption/entities/album)

from __future__ import annotations

import logging
import asyncio
from typing import Any, Dict, List, Optional

import config
from utils.common import log_and_report  # отчёт в ERROR_LOG_CHANNEL_ID

log = logging.getLogger(__name__)


def _take_caption(src: Dict[str, Any]) -> Optional[str]:
    return src.get("caption") or None


def _take_entities(src: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    ents = src.get("caption_entities")
    return ents if ents else None


def make_media_items(collected: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Нормализует контент в единый формат:
      • текст → payload['text'] (HTML)
      • подписи → payload['caption'] + payload['caption_entities']
      • альбом → payload['items'] (каждый элемент с caption/entities)
    """
    try:
        items: List[Dict[str, Any]] = []

        # Текст (как HTML-блок)
        text_html = (collected or {}).get("text_html")
        if text_html:
            items.append({"type": "html", "payload": {"text": text_html}, "position": 0})

        # Одиночные медиа
        single_media = (collected or {}).get("single_media") or []
        for it in single_media:
            payload = {"file_id": it["file_id"]}
            cap = _take_caption(it)
            if cap:
                payload["caption"] = cap
            ents = _take_entities(it)
            if ents:
                payload["caption_entities"] = ents
            items.append({"type": it["type"], "payload": payload, "position": len(items)})

        # Альбом
        album = (collected or {}).get("album") or []
        if album:
            norm_items: List[Dict[str, Any]] = []
            for el in album[:10]:
                t = el.get("type")
                file_id = el.get("file_id") or (el.get("payload") or {}).get("file_id")
                norm = {"type": t, "payload": {"file_id": file_id}}

                cap = _take_caption(el)
                if cap:
                    norm["payload"]["caption"] = cap
                ents = _take_entities(el)
                if ents:
                    norm["payload"]["caption_entities"] = ents

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
            "Сбор медиа не выполнен: ошибка=%s",
            exc,
            extra={"user_id": config.BOT_ID},
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(log_and_report(exc, "сбор медиа"))
        except Exception:
            pass
        return []
