# services/broadcasts.py
# Бизнес-логика рассылок: аудитория, отправка, выбор «пора»

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Iterable, List, Dict, Any, Optional

import config
from aiogram import Bot
from aiogram.types import InputMediaPhoto, InputMediaVideo, InputMediaDocument
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest

from services.db_api_client import db_api_client  # HTTP-клиент к БД-сервису

log = logging.getLogger(__name__)

KIND_FLAG = {
    "news": "news_enabled",
    "meetings": "meetings_enabled",
    "important": "important_enabled",
}

def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # сравниваем как naive UTC

def _parse_dt(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1]
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None

async def get_due_broadcasts(limit: int = 200) -> list[dict]:
    items = await db_api_client.list_broadcasts(limit=limit, offset=0)
    now = _now_utc()
    due = []
    for b in items:
        if b.get("status") != "scheduled":
            continue
        sch = _parse_dt(b.get("scheduled_at"))
        if sch is None:
            continue
        if sch <= now:
            due.append(b)
    due.sort(key=lambda x: _parse_dt(x.get("scheduled_at")) or now)
    return due

async def iter_audience_kind(kind: str) -> Iterable[int]:
    """
    Аудитория = все пользователи в memberships по chat_id=BOT_ID,
    отфильтрованные по флагу подписки на данный kind.
    """
    memberships = await db_api_client.list_memberships_by_chat(config.BOT_ID)
    flag_name = KIND_FLAG[kind]
    for m in memberships:
        uid = m.get("user_id")
        if not uid:
            continue
        try:
            # FIX: был вызов несуществующей get_user_subscriptions(...)
            subs = await db_api_client.get_user_subscriptions(uid)
            if subs.get(flag_name):
                yield uid
        except Exception as e:
            log.error("[iter_audience_kind] user_id=%s – ошибка чтения подписки: %s", uid, e)

async def _send_html(bot: Bot, user_id: int, html: str) -> bool:
    try:
        await bot.send_message(user_id, html, parse_mode="HTML", disable_web_page_preview=True)
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        try:
            await bot.send_message(user_id, html, parse_mode="HTML", disable_web_page_preview=True)
            return True
        except Exception as e2:
            log.warning("[send_html] retry failed user=%s: %s", user_id, e2)
            return False
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        log.info("[send_html] skip user=%s: %s", user_id, e)
        return False
    except Exception as e:
        log.error("[send_html] user=%s unexpected: %s", user_id, e)
        return False

async def _send_media(bot: Bot, user_id: int, media: List[Dict[str, Any]]) -> bool:
    if not media:
        return False
    try:
        item = media[0]
        mtype = item.get("type")
        payload = item.get("payload", {}) or item.get("payload_json", {})

        if mtype == "html":
            return await _send_html(bot, user_id, payload.get("text", ""))

        if mtype == "photo":
            await bot.send_photo(user_id, payload.get("file_id"), caption=payload.get("caption"))
            return True

        if mtype == "video":
            await bot.send_video(user_id, payload.get("file_id"), caption=payload.get("caption"))
            return True

        if mtype == "document":
            await bot.send_document(user_id, payload.get("file_id"), caption=payload.get("caption"))
            return True

        if mtype == "album":
            items = payload.get("items", [])
            media_group = []
            for it in items[:10]:
                ip = it.get("payload", {})
                if it.get("type") == "photo" and ip.get("file_id"):
                    media_group.append(InputMediaPhoto(media=ip["file_id"], caption=ip.get("caption")))
                elif it.get("type") == "video" and ip.get("file_id"):
                    media_group.append(InputMediaVideo(media=ip["file_id"], caption=ip.get("caption")))
                elif it.get("type") == "document" and ip.get("file_id"):
                    media_group.append(InputMediaDocument(media=ip["file_id"]))
            if media_group:
                await bot.send_media_group(user_id, media_group)
                return True
            return False

        if "text" in payload:
            return await _send_html(bot, user_id, payload.get("text", ""))

        return False
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        try:
            return await _send_media(bot, user_id, media)
        except Exception as e2:
            log.warning("[send_media] retry failed user=%s: %s", user_id, e2)
            return False
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        log.info("[send_media] skip user=%s: %s", user_id, e)
        return False
    except Exception as e:
        log.error("[send_media] user=%s unexpected: %s", user_id, e)
        return False

async def _resolve_audience(target: Optional[Dict[str, Any]]) -> List[int]:
    if not target:
        return []
    t = target.get("type")
    if t == "ids":
        ids = target.get("user_ids") or []
        out = []
        for v in ids:
            try:
                out.append(int(v))
            except Exception:
                continue
        return list(dict.fromkeys(out))
    if t == "kind":
        kind = target.get("kind")
        out = []
        async for uid in iter_audience_kind(kind):
            out.append(uid)
        return out
    if t == "sql":
        prev = await db_api_client.audience_preview({"type": "sql", "sql": target.get("sql")}, limit=100000)
        log.warning("[resolve_audience] SQL target требует материализации на бэке. total=%s sample=%s", prev.get("total"), len(prev.get("sample") or []))
        return []
    return []

async def send_broadcast(bot: Bot, broadcast: dict, throttle_per_sec: Optional[int] = None) -> tuple[int, int]:
    bid = broadcast["id"]
    rate = throttle_per_sec or getattr(config, "BROADCAST_RATE_PER_SEC", 29)
    rate = max(1, int(rate))
    window = 1.0 / rate

    try:
        media = await db_api_client.get_broadcast_media(bid)
    except Exception:
        media = []
    try:
        target = await db_api_client.get_broadcast_target(bid)
    except Exception:
        target = None

    if not media:
        html = broadcast.get("content_html") or ""
        if html:
            media = [{"type": "html", "payload": {"text": html}}]

    audience = await _resolve_audience(target)
    sent = 0
    failed = 0

    for uid in audience:
        ok = await _send_media(bot, uid, media)
        if ok:
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(window)

    return sent, failed

async def mark_broadcast_sent(broadcast_id: int) -> dict:
    return await db_api_client.update_broadcast(broadcast_id, status="sent")

async def run_broadcast_worker(bot: Bot, interval_seconds: int = 20):
    log.info("[broadcast_worker] started (interval=%ss)", interval_seconds)
    while True:
        try:
            due = await get_due_broadcasts(limit=200)
            if due:
                log.info("[broadcast_worker] found %s due broadcasts", len(due))
            for b in due:
                bid = b["id"]
                try:
                    sent, failed = await send_broadcast(bot, b)
                    log.info("[broadcast_worker] id=%s sent=%s failed=%s", bid, sent, failed)
                    await mark_broadcast_sent(bid)
                except Exception as e:
                    log.exception("[broadcast_worker] id=%s failed to send: %s", bid, e)
            await asyncio.sleep(interval_seconds)
        except Exception as e:
            log.exception("[broadcast_worker] loop error: %s", e)
            await asyncio.sleep(interval_seconds)
