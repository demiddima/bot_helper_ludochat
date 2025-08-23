# services/broadcasts/sender.py
# Отправка в Telegram: HTML/медиа/альбомы, лимиты, ретраи.

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from aiogram import Bot
from aiogram.types import (
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
    MessageEntity,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest

from utils.common import log_and_report

log = logging.getLogger(__name__)

CAPTION_LIMIT = 1024  # Максимальная длина подписи к медиа в Telegram


def _looks_like_html(s: str) -> bool:
    return "<" in s and ">" in s


def _to_entities(raw: Optional[List[Dict[str, Any]]]) -> Optional[List[MessageEntity]]:
    if not raw:
        return None
    out: List[MessageEntity] = []
    for e in raw:
        out.append(e if isinstance(e, MessageEntity) else MessageEntity.model_validate(e))
    return out


def _unsubscribe_kb(text: str = "Настроить рассылки") -> InlineKeyboardMarkup:
    """Одна кнопка с callback_data, открывающая меню подписок."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data="subs:open")]
        ]
    )


async def send_html(bot: Bot, user_id: int, html: str) -> bool:
    """Отправка текстового HTML-сообщения (с кнопкой «Отписаться от рассылки»)."""
    if not html or not str(html).strip():
        log.error("Отправка текста отменена: пустой контент (user_id=%s)", user_id, extra={"user_id": user_id})
        return False
    try:
        log.info("Отправляем HTML-текст пользователю (user_id=%s)", user_id, extra={"user_id": user_id})
        await bot.send_message(
            user_id,
            html,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=_unsubscribe_kb(),
        )
        log.info("HTML-текст успешно отправлен (user_id=%s)", user_id, extra={"user_id": user_id})
        return True

    except TelegramRetryAfter as e:
        log.warning(
            "Лимит Telegram: подождём %ss и попробуем снова (user_id=%s)",
            e.retry_after, user_id, extra={"user_id": user_id}
        )
        await asyncio.sleep(e.retry_after + 1)
        try:
            await bot.send_message(
                user_id,
                html,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=_unsubscribe_kb(),
            )
            log.info("HTML-текст отправлен со второй попытки (user_id=%s)", user_id, extra={"user_id": user_id})
            return True
        except Exception as e2:
            log.error(
                "Повторная отправка текста не удалась (user_id=%s): %s",
                user_id, e2, extra={"user_id": user_id}
            )
            return False

    except TelegramBadRequest as e:
        log.error(
            "Неверные параметры/контент при отправке текста (user_id=%s): %s",
            user_id, e, extra={"user_id": user_id}
        )
        try:
            await log_and_report(e, f"send_message HTML, user_id={user_id}")
        except Exception:
            pass
        return False

    except TelegramForbiddenError as e:
        log.info(
            "Пользователь недоступен или закрыл ЛС — текст не отправлен (user_id=%s): %s",
            user_id, e, extra={"user_id": user_id}
        )
        return False

    except Exception as e:
        log.error(
            "Неожиданная ошибка при отправке текста (user_id=%s): %s",
            user_id, e, extra={"user_id": user_id}
        )
        try:
            await log_and_report(e, f"send_message HTML unknown, user_id={user_id}")
        except Exception:
            pass
        return False


async def send_media(bot: Bot, user_id: int, media: List[Dict[str, Any]]) -> bool:
    """
    Отправка первого элемента из списка media:
      - html → текстовое сообщение
      - photo|video|document → медиа (с подписью/без)
      - album → медиагруппа (в проекте не планируется)
      - payload.text → как HTML-сообщение (fallback)
    Во всех случаях добавляем кнопку «Отписаться от рассылки».
    """
    if not media:
        log.error("Отправка медиа отменена: media-пакет пуст (user_id=%s)", user_id, extra={"user_id": user_id})
        return False

    try:
        item = media[0]
        mtype = item.get("type")
        payload = item.get("payload", {}) or item.get("payload_json", {})
        log.info("Готовим отправку элемента типа '%s' (user_id=%s)", mtype, user_id, extra={"user_id": user_id})

        if mtype == "html":
            text = payload.get("text", "")
            return await send_html(bot, user_id, text)

        if mtype in {"photo", "video", "document"}:
            file_id: str = payload.get("file_id")
            caption: Optional[str] = payload.get("caption")
            ents_raw = payload.get("caption_entities")
            ents = _to_entities(ents_raw)

            if not file_id:
                log.error("Медиа без file_id — пропускаем (type=%s, user_id=%s)", mtype, user_id, extra={"user_id": user_id})
                return False

            # Слишком длинная подпись → медиа без подписи, текст отдельным сообщением (с кнопкой)
            if caption and len(caption) > CAPTION_LIMIT:
                log.info(
                    "Подпись длиной %s символов превышает лимит %s — отправим отдельно (user_id=%s)",
                    len(caption), CAPTION_LIMIT, user_id, extra={"user_id": user_id}
                )
                if mtype == "photo":
                    await bot.send_photo(user_id, file_id, caption=None, parse_mode=None)
                elif mtype == "video":
                    await bot.send_video(user_id, file_id, caption=None, parse_mode=None)
                else:
                    await bot.send_document(user_id, file_id, caption=None, parse_mode=None)

                if ents:
                    await bot.send_message(
                        user_id, caption, entities=ents, parse_mode=None,
                        reply_markup=_unsubscribe_kb()
                    )
                else:
                    await bot.send_message(
                        user_id, caption,
                        parse_mode=("HTML" if _looks_like_html(caption) else None),
                        reply_markup=_unsubscribe_kb()
                    )
                log.info("Медиа отправлено, длинная подпись выслана отдельным сообщением (user_id=%s)", user_id, extra={"user_id": user_id})
                return True

            # Обычный случай — подпись краткая → кнопку ставим прямо на медиа
            if mtype == "photo":
                await bot.send_photo(
                    user_id, file_id,
                    caption=caption,
                    caption_entities=ents if ents else None,
                    parse_mode=None if ents else ("HTML" if (caption and _looks_like_html(caption)) else None),
                    reply_markup=_unsubscribe_kb(),
                )
                log.info("Фото успешно отправлено (user_id=%s)", user_id, extra={"user_id": user_id})
                return True

            if mtype == "video":
                await bot.send_video(
                    user_id, file_id,
                    caption=caption,
                    caption_entities=ents if ents else None,
                    parse_mode=None if ents else ("HTML" if (caption and _looks_like_html(caption)) else None),
                    reply_markup=_unsubscribe_kb(),
                )
                log.info("Видео успешно отправлено (user_id=%s)", user_id, extra={"user_id": user_id})
                return True

            if mtype == "document":
                await bot.send_document(
                    user_id, file_id,
                    caption=caption,
                    caption_entities=ents if ents else None,
                    parse_mode=None if ents else ("HTML" if (caption and _looks_like_html(caption)) else None),
                    reply_markup=_unsubscribe_kb(),
                )
                log.info("Документ успешно отправлен (user_id=%s)", user_id, extra={"user_id": user_id})
                return True

        if mtype == "album":
            # В проекте альбомы не планируются. На всякий случай оставим прежнюю реализацию без кнопки.
            items = payload.get("items", [])[:10]
            if not items:
                log.error("Альбом пуст — отправлять нечего (user_id=%s)", user_id, extra={"user_id": user_id})
                return False

            media_group = []
            overflow: List[Tuple[str, Optional[List[MessageEntity]]]] = []

            for it in items:
                t = it.get("type")
                ip = it.get("payload", {})
                fid = ip.get("file_id")
                cap = ip.get("caption")
                ents = _to_entities(ip.get("caption_entities"))

                if not fid:
                    log.warning("Элемент альбома без file_id — пропускаем (type=%s, user_id=%s)", t, user_id, extra={"user_id": user_id})
                    continue

                parse_mode = None
                if cap and len(cap) > CAPTION_LIMIT:
                    overflow.append((cap, ents))
                    cap, ents = None, None
                elif cap and not ents and _looks_like_html(cap):
                    parse_mode = "HTML"

                if t == "photo":
                    media_group.append(InputMediaPhoto(media=fid, caption=cap, caption_entities=ents, parse_mode=parse_mode))
                elif t == "video":
                    media_group.append(InputMediaVideo(media=fid, caption=cap, caption_entities=ents, parse_mode=parse_mode))
                elif t == "document":
                    media_group.append(InputMediaDocument(media=fid))
                else:
                    log.warning("Неизвестный тип в альбоме — пропускаем (type=%s, user_id=%s)", t, user_id, extra={"user_id": user_id})

            if media_group:
                log.info("Отправляем медиагруппу из %s элементов (user_id=%s)", len(media_group), user_id, extra={"user_id": user_id})
                sent_messages = await bot.send_media_group(user_id, media_group)
                if overflow:
                    for txt, ents in overflow:
                        if ents:
                            await bot.send_message(user_id, txt, entities=ents, parse_mode=None)
                        else:
                            await bot.send_message(user_id, txt, parse_mode=("HTML" if _looks_like_html(txt) else None))
                log.info("Медиагруппа успешно отправлена (user_id=%s)", user_id, extra={"user_id": user_id})
                return True

            log.error("Не удалось собрать валидную медиагруппу — ничего не отправлено (user_id=%s)", user_id, extra={"user_id": user_id})
            return False

        # Fallback: payload содержит текст → отправляем как HTML (с кнопкой)
        if "text" in payload:
            log.info("В payload найден текст — отправляем как HTML (user_id=%s)", user_id, extra={"user_id": user_id})
            return await send_html(bot, user_id, payload.get("text", ""))

        log.error("Неизвестный или пустой payload — отправка отменена (type=%s, user_id=%s)", mtype, user_id, extra={"user_id": user_id})
        return False

    except TelegramRetryAfter as e:
        log.warning(
            "Лимит Telegram при отправке медиа: подождём %ss и попробуем снова (user_id=%s)",
            e.retry_after, user_id, extra={"user_id": user_id}
        )
        await asyncio.sleep(e.retry_after + 1)
        return await send_media(bot, user_id, media)

    except TelegramForbiddenError as e:
        log.info(
            "Пользователь недоступен/запретил сообщения — медиа не отправлено (user_id=%s): %s",
            user_id, e, extra={"user_id": user_id}
        )
        return False

    except TelegramBadRequest as e:
        log.error(
            "Неверные параметры/контент при отправке медиа (user_id=%s): %s",
            user_id, e, extra={"user_id": user_id}
        )
        try:
            await log_and_report(e, f"media badrequest, user_id={user_id}")
        except Exception:
            pass
        return False

    except Exception as e:
        log.error(
            "Неожиданная ошибка при отправке медиа (user_id=%s): %s",
            user_id, e, extra={"user_id": user_id}
        )
        try:
            await log_and_report(e, f"media unknown, user_id={user_id}")
        except Exception:
            pass
        return False


__all__ = ["send_media", "send_html", "CAPTION_LIMIT"]
