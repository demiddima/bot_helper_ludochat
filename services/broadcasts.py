# services/broadcasts.py
# Бизнес-логика рассылок: аудитория, отправка, выбор «пора»

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Iterable, List, Dict, Any, Optional

import config
from aiogram import Bot
from aiogram.types import InputMediaPhoto, InputMediaVideo, InputMediaDocument
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest

from services.db_api_client import db_api_client  # HTTP-клиент к БД-сервису
from utils.time_msk import now_msk_naive, from_iso_naive  # МСК-naive хелперы
from utils.common import log_and_report  # отчёты в ERROR_LOG_CHANNEL_ID

log = logging.getLogger(__name__)

KIND_FLAG = {
    "news": "news_enabled",
    "meetings": "meetings_enabled",
    "important": "important_enabled",
}


# --- Время: работаем в МСК-naive целиком ---

def _now_msk() -> datetime:
    """Текущее московское время (naive)."""
    return now_msk_naive()


def _parse_dt_msk(dt_str: Optional[str]) -> Optional[datetime]:
    """
    Строка из API → naive datetime (ожидаем ISO/`YYYY-MM-DD HH:MM:SS` без TZ).
    Если прилетит с 'Z' — обрежем и распарсим.
    """
    if not dt_str:
        return None
    return from_iso_naive(dt_str.rstrip("Z"))


def _is_blank(s: Optional[str]) -> bool:
    return not s or not str(s).strip()


async def get_due_broadcasts(limit: int = 200) -> list[dict]:
    """
    Забираем рассылки и отбираем те, у которых scheduled_at <= now (оба в МСК-naive).
    """
    items = await db_api_client.list_broadcasts(limit=limit, offset=0)
    now = _now_msk()
    due: list[dict] = []
    for b in items:
        if b.get("status") != "scheduled":
            continue
        sch = _parse_dt_msk(b.get("scheduled_at"))
        if sch is None:
            continue
        if sch <= now:
            due.append(b)
    # стабильная отправка по возрастанию времени
    due.sort(key=lambda x: _parse_dt_msk(x.get("scheduled_at")) or now)
    return due


# --- Аудитории ---

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
            subs = await db_api_client.get_user_subscriptions(uid)
            if subs.get(flag_name):
                yield uid
        except Exception as exc:
            logging.error(
                "Не удалось прочитать подписки: user_id=%s, причина=%s",
                uid, exc, extra={"user_id": uid}
            )


# --- Отправка сообщений пользователю ---

async def _send_html(bot: Bot, user_id: int, html: str) -> bool:
    # гвард на пустой текст — не шлём в Telegram
    if _is_blank(html):
        logging.error(
            "Отправка текста невозможна: user_id=%s, причина=пустой текст",
            user_id, extra={"user_id": user_id}
        )
        return False
    try:
        await bot.send_message(user_id, html, parse_mode="HTML", disable_web_page_preview=True)
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        try:
            await bot.send_message(user_id, html, parse_mode="HTML", disable_web_page_preview=True)
            return True
        except Exception as e2:
            logging.error(
                "Повторная отправка текста не выполнена: user_id=%s, ошибка=%s",
                user_id, e2, extra={"user_id": user_id}
            )
            return False
    except TelegramBadRequest as e:
        # Контентная проблема (например, слишком длинная подпись) — эскалируем
        logging.error(
            "Отправка текста не выполнена: user_id=%s, ошибка=%s",
            user_id, e, extra={"user_id": user_id}
        )
        try:
            await log_and_report(e, f"отправка текста, user_id={user_id}")
        except Exception:
            pass
        return False
    except TelegramForbiddenError as e:
        # Пользователь недоступен — ожидаемый кейс
        logging.info(
            "Пользователь недоступен/запретил сообщения: user_id=%s, причина=%s",
            user_id, e, extra={"user_id": user_id}
        )
        return False
    except Exception as e:
        logging.error(
            "Неизвестная ошибка при отправке текста: user_id=%s, ошибка=%s",
            user_id, e, extra={"user_id": user_id}
        )
        try:
            await log_and_report(e, f"неизвестная ошибка текста, user_id={user_id}")
        except Exception:
            pass
        return False


async def _send_media(bot: Bot, user_id: int, media: List[Dict[str, Any]]) -> bool:
    if not media:
        return False
    try:
        item = media[0]
        mtype = item.get("type")
        payload = item.get("payload", {}) or item.get("payload_json", {})

        if mtype == "html":
            text = payload.get("text", "")
            if _is_blank(text):
                logging.error(
                    "Отправка текста невозможна: user_id=%s, причина=пустой payload.text",
                    user_id, extra={"user_id": user_id}
                )
                return False
            return await _send_html(bot, user_id, text)

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
            logging.error(
                "Повторная отправка медиа не выполнена: user_id=%s, ошибка=%s",
                user_id, e2, extra={"user_id": user_id}
            )
            return False
    except TelegramBadRequest as e:
        logging.error(
            "Отправка медиа не выполнена из-за контента: user_id=%s, ошибка=%s",
            user_id, e, extra={"user_id": user_id}
        )
        try:
            await log_and_report(e, f"отправка медиа, user_id={user_id}")
        except Exception:
            pass
        return False
    except TelegramForbiddenError as e:
        logging.info(
            "Пользователь недоступен/запретил сообщения: user_id=%s, причина=%s",
            user_id, e, extra={"user_id": user_id}
        )
        return False
    except Exception as e:
        logging.error(
            "Неизвестная ошибка при отправке медиа: user_id=%s, ошибка=%s",
            user_id, e, extra={"user_id": user_id}
        )
        try:
            await log_and_report(e, f"неизвестная ошибка медиа, user_id={user_id}")
        except Exception:
            pass
        return False


# --- Разворачивание аудитории ---

async def _resolve_audience(target: Optional[Dict[str, Any]]) -> List[int]:
    if not target:
        return []
    t = target.get("type")
    if t == "ids":
        ids = target.get("user_ids") or []
        out: List[int] = []
        for v in ids:
            try:
                out.append(int(v))
            except Exception:
                continue
        # uniq & keep order
        return list(dict.fromkeys(out))
    if t == "kind":
        kind = target.get("kind")
        out: List[int] = []
        async for uid in iter_audience_kind(kind):
            out.append(uid)
        return out
    if t == "sql":
        # Пока только превью. Для исполнения нужен бэкенд-эндпоинт materialize/exec.
        prev = await db_api_client.audience_preview({"type": "sql", "sql": target.get("sql")}, limit=100000)
        logging.warning(
            "SQL-аудитория не материализована: total=%s, sample=%s",
            prev.get("total"), len(prev.get("sample") or []),
            extra={"user_id": config.BOT_ID},
        )
        return []
    return []


# --- Основной цикл отправки одной рассылки ---

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

    # удаляем пустые html-элементы; ниже попробуем fallback на content_html
    if media:
        cleaned: List[Dict[str, Any]] = []
        for it in media:
            if it.get("type") == "html":
                txt = ((it.get("payload") or {}).get("text") or "").strip()
                if not txt:
                    logging.error(
                        "Контент рассылки пуст: id=%s, удалён пустой html-элемент",
                        bid, extra={"user_id": config.BOT_ID}
                    )
                    continue
            cleaned.append(it)
        media = cleaned

    if not media:
        html = (broadcast.get("content_html") or "").strip()
        if html:
            media = [{"type": "html", "payload": {"text": html}}]

    if not media:
        logging.error(
            "Рассылка не отправлена: id=%s, причина=нет контента (пустой текст и нет медиа)",
            bid, extra={"user_id": config.BOT_ID}
        )
        return 0, 0

    audience = await _resolve_audience(target)
    if not audience:
        logging.warning(
            "Рассылка не отправлена: пустая аудитория — id=%s",
            bid, extra={"user_id": config.BOT_ID}
        )
        return 0, 0

    logging.info(
        "Начинаю отправку: id=%s, аудитория=%s, скорость=%s msg/с",
        bid, len(audience), rate, extra={"user_id": config.BOT_ID}
    )

    sent = 0
    failed = 0

    for uid in audience:
        ok = await _send_media(bot, uid, media)
        if ok:
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(window)

    if sent == 0 and failed > 0:
        logging.error(
            "Рассылка не доставлена никому: id=%s, failed=%s",
            bid, failed, extra={"user_id": config.BOT_ID}
        )
        try:
            await log_and_report(Exception("broadcast failed"), f"рассылка не доставлена: id={bid}, failed={failed}")
        except Exception:
            pass
    elif failed > 0:
        logging.warning(
            "Рассылка доставлена частично: id=%s, sent=%s, failed=%s",
            bid, sent, failed, extra={"user_id": config.BOT_ID}
        )
    else:
        logging.info(
            "Рассылка доставлена полностью: id=%s, sent=%s",
            bid, sent, extra={"user_id": config.BOT_ID}
        )

    return sent, failed


async def mark_broadcast_sent(broadcast_id: int) -> dict:
    return await db_api_client.update_broadcast(broadcast_id, status="sent")


# --- Фоновый воркер: выбирает «пора» и шлёт ---

async def run_broadcast_worker(bot: Bot, interval_seconds: int = 20):
    logging.info(
        "Воркер рассылок запущен: интервал=%sс", interval_seconds, extra={"user_id": config.BOT_ID}
    )
    while True:
        try:
            due = await get_due_broadcasts(limit=200)
            if due:
                logging.info(
                    "Найдено рассылок к отправке: %s", len(due), extra={"user_id": config.BOT_ID}
                )
            for b in due:
                bid = b["id"]
                try:
                    sent, failed = await send_broadcast(bot, b)
                    if sent > 0:
                        logging.info(
                            "Отмечаю как отправленную: id=%s, sent=%s, failed=%s",
                            bid, sent, failed, extra={"user_id": config.BOT_ID}
                        )
                        await mark_broadcast_sent(bid)
                    else:
                        logging.error(
                            "Не отмечаем как отправленную: id=%s, sent=%s, failed=%s",
                            bid, sent, failed, extra={"user_id": config.BOT_ID}
                        )
                except Exception as exc:
                    logging.error(
                        "Ошибка при отправке рассылки: id=%s, ошибка=%s",
                        bid, exc, extra={"user_id": config.BOT_ID}
                    )
                    try:
                        await log_and_report(exc, f"воркер отправки, id={bid}")
                    except Exception:
                        pass
            await asyncio.sleep(interval_seconds)
        except Exception as exc:
            logging.error(
                "Критическая ошибка цикла воркера: %s", exc, extra={"user_id": config.BOT_ID}
            )
            try:
                await log_and_report(exc, "цикл воркера")
            except Exception:
                pass
            await asyncio.sleep(interval_seconds)
