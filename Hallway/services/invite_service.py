# Hallway/services/invite_service.py
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Sequence

from aiogram.exceptions import TelegramBadRequest

from storage import get_all_invite_links, save_invite_link
from common.utils.chatlink import to_int_or_none, is_url, eq_chat_id, parse_exp_aware


async def generate_invite_links(
    bot,
    user,
    uid: int,
    PRIVATE_DESTINATIONS: Sequence[dict],
    verify_user=None,
    ERROR_LOG_CHANNEL_ID: int | None = None,
    only_chat_ids: set[int] | None = None,
):
    """
    Генерирует инвайты для PRIVATE_DESTINATIONS.
    Если only_chat_ids задан — создаёт/обновляет ТОЛЬКО для этих chat_id (числовых).
    Возвращает:
      - links: list[tuple[title, url, desc]]
      - buttons: list[[{"text": title, "url": url}]]
    """
    try:
        existing_links = await get_all_invite_links(uid)
    except Exception as e:
        logging.error(f"user_id={uid} – ошибка чтения ссылок из БД: {e}", extra={"user_id": uid})
        existing_links = []

    now_utc = datetime.now(timezone.utc)
    links: list[tuple[str, str, str]] = []
    buttons: list[list[dict]] = []

    for dest in PRIVATE_DESTINATIONS:
        if not all(k in dest for k in ("title", "chat_id", "description")):
            logging.error(f"user_id={uid} – некорректный PRIVATE_DESTINATIONS: {dest}", extra={"user_id": uid})
            continue

        title = dest["title"]
        desc = dest.get("description", "")
        raw_chat_id = dest["chat_id"]
        num_chat_id = to_int_or_none(raw_chat_id)

        # Фильтр по only_chat_ids (если задан)
        if only_chat_ids is not None:
            if num_chat_id is None or num_chat_id not in only_chat_ids:
                continue

        try:
            # URL — используем напрямую
            if is_url(raw_chat_id):
                url = str(raw_chat_id)
                links.append((title, url, desc))
                buttons.append([{"text": title, "url": url}])
                logging.info(f"user_id={uid} – {title}: используем прямой URL", extra={"user_id": uid})
                continue

            # Числовой chat_id — ищем актуальную ссылку в БД
            if num_chat_id is not None:
                existing = next(
                    (x for x in existing_links if eq_chat_id(x.get("chat_id"), num_chat_id)),
                    None,
                )

                if existing:
                    exp = parse_exp_aware(existing.get("expires_at"))
                    if exp and exp > now_utc:
                        invite_link = existing.get("invite_link")
                        if invite_link:
                            links.append((title, invite_link, desc))
                            buttons.append([{"text": title, "url": invite_link}])
                            logging.info(f"user_id={uid} – {title}: актуальная ссылка найдена", extra={"user_id": uid})
                            continue
                        else:
                            logging.warning(f"user_id={uid} – {title}: пустой invite_link в БД", extra={"user_id": uid})
                    else:
                        logging.info(f"user_id={uid} – {title}: ссылка устарела/без срока – создаём новую", extra={"user_id": uid})

                # Создаём новую ссылку
                try:
                    invite = await bot.create_chat_invite_link(
                        chat_id=num_chat_id,
                        member_limit=1,
                        creates_join_request=False,
                        name=f"Invite for {user.username or user.id}",
                    )
                    invite_link = invite.invite_link

                    # сохраняем
                    created_at = now_utc.isoformat()
                    expires_at = (now_utc + timedelta(hours=1)).isoformat()

                    try:
                        await save_invite_link(uid, num_chat_id, invite_link, created_at, expires_at)
                    except Exception as se:
                        logging.error(
                            f"user_id={uid} – {title}: ошибка сохранения ссылки: {se}",
                            extra={"user_id": uid},
                        )

                    links.append((title, invite_link, desc))
                    buttons.append([{"text": title, "url": invite_link}])

                    if verify_user:
                        try:
                            verify_user(uid, invite_link)
                        except Exception as ve:
                            logging.warning(f"user_id={uid} – {title}: verify_user упал: {ve}", extra={"user_id": uid})

                    logging.info(f"user_id={uid} – {title}: новая ссылка создана", extra={"user_id": uid})

                except TelegramBadRequest as e:
                    text_err = str(e).lower()
                    logging.error(f"user_id={uid} – {title}: TelegramBadRequest: {e}", extra={"user_id": uid})
                    # Попытка освободить лимит
                    if any(kw in text_err for kw in ("limit", "too many requests", "invite links limit")):
                        try:
                            old_links = await bot.get_chat_invite_links(chat_id=num_chat_id, limit=100)
                            if old_links:
                                oldest = old_links[0].invite_link
                                await bot.revoke_chat_invite_link(chat_id=num_chat_id, invite_link=oldest)
                                logging.info(
                                    f"user_id={uid} – {title}: отозвана старая ссылка {oldest}",
                                    extra={"user_id": uid},
                                )
                                invite = await bot.create_chat_invite_link(
                                    chat_id=num_chat_id,
                                    member_limit=1,
                                    creates_join_request=False,
                                    name=f"Invite for {user.username or user.id}",
                                )
                                invite_link = invite.invite_link
                                links.append((title, invite_link, desc))
                                buttons.append([{"text": title, "url": invite_link}])
                                logging.info(
                                    f"user_id={uid} – {title}: новая ссылка создана после отзыва",
                                    extra={"user_id": uid},
                                )
                                if ERROR_LOG_CHANNEL_ID:
                                    try:
                                        await bot.send_message(
                                            ERROR_LOG_CHANNEL_ID,
                                            f"Отозвали старую ссылку для чата {num_chat_id} из-за лимита.",
                                        )
                                    except Exception:
                                        pass
                        except Exception as e2:
                            logging.warning(
                                f"user_id={uid} – {title}: ошибка при отзыве/пересоздании: {e2}",
                                extra={"user_id": uid},
                            )
                except Exception as e:
                    logging.error(
                        f"user_id={uid} – {title}: ошибка создания инвайта: {e}",
                        extra={"user_id": uid},
                    )

            else:
                logging.error(
                    f"user_id={uid} – {title}: chat_id не число и не URL: {raw_chat_id!r}",
                    extra={"user_id": uid},
                )

        except Exception as e:
            logging.error(
                f"user_id={uid} – {title}: непредвиденная ошибка: {e}",
                extra={"user_id": uid},
            )
            if ERROR_LOG_CHANNEL_ID:
                try:
                    await bot.send_message(
                        ERROR_LOG_CHANNEL_ID,
                        f"Ошибка при создании ссылки для {user.full_name} (ID {uid}) в чате {raw_chat_id}: {e}",
                    )
                except Exception:
                    pass

    return links, buttons
