# generate_invite_links.py
# Обновлён: Корпоративный стиль логирования, [function] – user_id=… – текст, try/except для всех рисковых участков

import logging
from aiogram.exceptions import TelegramBadRequest
from datetime import datetime, timezone, timedelta
from storage import get_all_invite_links, save_invite_link

async def generate_invite_links(bot, user, uid, PRIVATE_DESTINATIONS, verify_user, ERROR_LOG_CHANNEL_ID):
    links = []
    buttons = []
    func_name = "generate_invite_links"

    for dest in PRIVATE_DESTINATIONS:
        if not all(k in dest for k in ("title", "chat_id", "description")):
            logging.error(
                f"user_id={uid} – Некорректный PRIVATE_DESTINATIONS: {dest}",
                extra={"user_id": uid}
            )
            continue

        chat_id = dest["chat_id"]
        title = dest["title"]
        desc = dest["description"]

        try:
            # 1) Получаем все ссылки из БД
            try:
                existing_links = await get_all_invite_links(uid)
            except Exception as e:
                logging.error(
                    f"user_id={uid} – Ошибка при получении ссылок из БД: {e}",
                    extra={"user_id": uid}
                )
                continue

            # 2) Проверяем срок действия существующей ссылки
            existing = next((x for x in existing_links if x["chat_id"] == chat_id), None)
            if existing and existing.get("expires_at"):
                try:
                    exp = datetime.fromisoformat(existing["expires_at"]).replace(tzinfo=timezone.utc)
                    now = datetime.now(timezone.utc)
                    if exp > now:
                        links.append((title, existing["invite_link"], desc))
                        buttons.append([{"text": title, "url": existing["invite_link"]}])
                        logging.info(
                            f"user_id={uid} – Ссылка для «{title}» актуальна, используем её",
                            extra={"user_id": uid}
                        )
                        continue
                    else:
                        logging.info(
                            f"user_id={uid} – Ссылка для «{title}» устарела, генерируем новую",
                            extra={"user_id": uid}
                        )
                except Exception as e:
                    logging.warning(
                        f"user_id={uid} – Ошибка при проверке срока ссылки «{title}»: {e}",
                        extra={"user_id": uid}
                    )

            # 3) Генерируем новую ссылку, если chat_id — число
            if isinstance(chat_id, int):
                try:
                    invite = await bot.create_chat_invite_link(
                        chat_id=chat_id,
                        member_limit=1,
                        creates_join_request=False,
                        name=f"Invite for {user.username or user.id}"
                    )
                    invite_link = invite.invite_link
                    links.append((title, invite_link, desc))
                    buttons.append([{"text": title, "url": invite_link}])

                    try:
                        save_result = await save_invite_link(
                            uid,
                            chat_id,
                            invite_link,
                            datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
                            (datetime.utcnow() + timedelta(hours=1)).isoformat()
                        )
                        logging.info(
                            f"user_id={uid} – Сгенерирована и сохранена ссылка для «{title}»: {invite_link} (результат: {save_result})",
                            extra={"user_id": uid}
                        )
                    except Exception as e:
                        logging.error(
                            f"user_id={uid} – Ошибка при сохранении ссылки в БД для «{title}»: {e}",
                            extra={"user_id": uid}
                        )
                except TelegramBadRequest as e:
                    text_err = str(e).lower()
                    logging.error(
                        f"user_id={uid} – TelegramBadRequest для «{title}»: {e}",
                        extra={"user_id": uid}
                    )
                    if any(kw in text_err for kw in ("limit", "too many requests", "invite links limit")):
                        try:
                            old_links = await bot.get_chat_invite_links(chat_id=chat_id, limit=100)
                            if old_links:
                                oldest = old_links[0].invite_link
                                await bot.revoke_chat_invite_link(chat_id=chat_id, invite_link=oldest)
                                logging.info(
                                    f"user_id={uid} – Отозвана старая ссылка {oldest} в чате {chat_id}",
                                    extra={"user_id": uid}
                                )
                                try:
                                    await bot.send_message(
                                        ERROR_LOG_CHANNEL_ID,
                                        f"Отозвана старая ссылка в чате {chat_id} для освобождения лимита."
                                    )
                                except Exception as ee:
                                    logging.warning(
                                        f"user_id={uid} – Не удалось уведомить об отзыве ссылки {chat_id}: {ee}",
                                        extra={"user_id": uid}
                                    )
                                invite = await bot.create_chat_invite_link(
                                    chat_id=chat_id,
                                    member_limit=1,
                                    creates_join_request=False,
                                    name=f"Invite for {user.username or user.id}"
                                )
                                invite_link = invite.invite_link
                                verify_user(uid, invite_link)
                                links.append((title, invite_link, desc))
                                buttons.append([{"text": title, "url": invite_link}])
                                logging.info(
                                    f"user_id={uid} – Сгенерирована новая ссылка после отзыва: {invite_link}",
                                    extra={"user_id": uid}
                                )
                        except Exception as e2:
                            logging.warning(
                                f"user_id={uid} – Ошибка при отзыве/повторной генерации ссылки: {e2}",
                                extra={"user_id": uid}
                            )
                except Exception as e:
                    logging.error(
                        f"user_id={uid} – Ошибка при создании новой invite-ссылки для {chat_id}: {e}",
                        extra={"user_id": uid}
                    )

            # 4) Если chat_id — URL, используем напрямую
            elif isinstance(chat_id, str) and chat_id.startswith("http"):
                links.append((title, chat_id, desc))
                buttons.append([{"text": title, "url": chat_id}])
                logging.info(
                    f"user_id={uid} – Используем прямую ссылку для «{title}»: {chat_id}",
                    extra={"user_id": uid}
                )

        except Exception as e:
            logging.error(
                f"user_id={uid} – Непредвиденная ошибка при обработке «{title}»: {e}",
                extra={"user_id": uid}
            )
            try:
                await bot.send_message(
                    ERROR_LOG_CHANNEL_ID,
                    f"Ошибка при создании ссылки для {user.full_name} (ID {uid}) в чате {chat_id}: {e}"
                )
            except Exception as ee:
                logging.warning(
                    f"user_id={uid} – Не удалось отправить уведомление об ошибке invite: {ee}",
                    extra={"user_id": uid}
                )

    return links, buttons
